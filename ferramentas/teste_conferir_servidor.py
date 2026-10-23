#!/usr/bin/env python3
"""Testes de conferir_servidor.py (FM1). Nenhum HEAD nem GET de verdade: o
servidor é um dublê (um dicionário de URL -> resposta) no lugar de
`cabeca` e `baixar`; o único pedaço real do HTTP (o HEAD pelo urllib) roda
com o urlopen trocado, sem abrir socket.

  python ferramentas/teste_conferir_servidor.py          # sem pytest
"""
import contextlib
import io
import json
import sys
import tempfile
import traceback
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conferir_servidor as cs  # noqa: E402

BASE = 'https://midia.exemplo.invalid/'
VIDEOS = 'https://video.exemplo.invalid/'


def manifesto(chaves):
    """Um manifesto como o gerar_manifesto escreve: chave -> bytes e sha256."""
    return {'versao': 1, 'geradoEm': '2026-11-08T12:00:00Z',
            'arquivos': {chave: {'bytes': tamanho, 'sha256': 'a' * 64}
                         for chave, tamanho in chaves.items()}}


def temporada(id_, inicio, capitulos, compartilhado=False):
    """Um novela/<t>.json mínimo para a conferência dos vídeos: com
    `compartilhado`, as duas tradições apontam o mesmo arquivo (FM5)."""
    from datetime import date, timedelta
    primeiro = date.fromisoformat(inicio)
    lista = []
    for n in range(1, capitulos + 1):
        nn = f'{n:02d}'
        video = {t: {'arquivo': f'video/{id_}/{nn}-{t}.mp4', 'bytes': 1000 * n + len(t),
                     'sha256': 'b' * 64} for t in ('catolico', 'evangelico')}
        if compartilhado:
            video['evangelico'] = dict(video['catolico'])
        lista.append({'id': f'{id_}c{n}', 'n': n, 'data': (primeiro + timedelta(days=n - 1)).isoformat(),
                      'video': video})
    return {'id': id_, 'titulo': id_, 'inicio': inicio, 'capitulos': lista}


class Servidor:
    """O servidor de mentira: `arquivos` é URL -> bytes (um GET devolve o
    conteúdo; um HEAD, 200 e o tamanho); `cabecas` troca a resposta do HEAD
    de uma URL ((status, Content-Length) ou uma exceção); `pedidos` registra
    tudo o que foi pedido."""

    def __init__(self):
        self.arquivos = {}
        self.cabecas = {}
        self.pedidos = []

    def publicar(self, base, chave, conteudo):
        self.arquivos[base + chave] = conteudo if isinstance(conteudo, bytes) else \
            json.dumps(conteudo, ensure_ascii=False).encode('utf-8')

    def cabeca(self, url, tempo=20):
        self.pedidos.append(('HEAD', url))
        if url in self.cabecas:
            resposta = self.cabecas[url]
            if isinstance(resposta, Exception):
                raise resposta
            return resposta
        if url not in self.arquivos:
            return 404, None
        return 200, len(self.arquivos[url])

    def baixar(self, url, tempo=60):
        self.pedidos.append(('GET', url))
        if url not in self.arquivos:
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
        return self.arquivos[url]

    @contextlib.contextmanager
    def instalado(self):
        antes = cs.cabeca, cs.baixar
        cs.cabeca, cs.baixar = self.cabeca, self.baixar
        try:
            yield self
        finally:
            cs.cabeca, cs.baixar = antes


def servidor_completo():
    """Um servidor com o manifesto, o índice da novela (t1 com as duas
    versões, t2 com um vídeo compartilhado) e os vídeos na base `videos`."""
    s = Servidor()
    t1 = temporada('t1', '2026-11-10', 2)
    t2 = temporada('t2', '2026-12-17', 1, compartilhado=True)
    indice = {'versao': 1, 'videos': VIDEOS, 'temporadas': [
        {'id': 't1', 'titulo': 't1', 'inicio': '2026-11-10', 'fim': '2026-11-11', 'capitulos': 2,
         'arquivo': 'novela/t1.json'},
        {'id': 't2', 'titulo': 't2', 'inicio': '2026-12-17', 'fim': '2026-12-17', 'capitulos': 1,
         'arquivo': 'novela/t2.json'}]}
    conteudos = {'novela/temporadas.json': indice, 'novela/t1.json': t1, 'novela/t2.json': t2,
                 'novela/t1c1.srt': b'1\n00:00:00,000 --> 00:00:01,500\nUm.\n',
                 'imagens/t1c1.webp': b'capa' * 10, 'imagens/comum-001.webp': b'aquarela' * 5,
                 'narracao/catolico/t1c1.m4a': b'voz' * 7, 'narracao/evangelico/comum-001.m4a': b'v' * 9,
                 'terco/marcas.json': b'{}'}
    for chave, conteudo in conteudos.items():
        s.publicar(BASE, chave, conteudo)
    tamanhos = {chave: len(s.arquivos[BASE + chave]) for chave in conteudos}
    s.publicar(BASE, 'manifesto.json', manifesto(tamanhos))
    for t in (t1, t2):
        for c in t['capitulos']:
            for v in c['video'].values():
                s.arquivos[VIDEOS + v['arquivo']] = b'x' * v['bytes']
    return s


def rodar(*argv):
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        codigo = cs.main(list(argv))
    return codigo, saida.getvalue()


# ---------------------------------------------------------------------------

def teste_servidor_certo_confere_cada_entrada_do_manifesto_e_cada_video_e_sai_com_0():
    s = servidor_completo()
    with s.instalado():
        codigo, saida = rodar('--base', BASE)
    assert codigo == 0, saida
    cabecas = sorted(url for metodo, url in s.pedidos if metodo == 'HEAD')
    # Cada entrada do manifesto (9) e cada vídeo distinto (t1: 4; t2: 1, o
    # compartilhado conferido UMA vez) — nada mais.
    assert len([u for u in cabecas if u.startswith(BASE)]) == 9, cabecas
    videos = [u for u in cabecas if u.startswith(VIDEOS)]
    assert videos == sorted({VIDEOS + 'video/t1/01-catolico.mp4', VIDEOS + 'video/t1/01-evangelico.mp4',
                             VIDEOS + 'video/t1/02-catolico.mp4', VIDEOS + 'video/t1/02-evangelico.mp4',
                             VIDEOS + 'video/t2/01-catolico.mp4'}), videos
    gets = [url for metodo, url in s.pedidos if metodo == 'GET']
    assert gets == [BASE + 'manifesto.json', BASE + 'novela/temporadas.json',
                    BASE + 'novela/t1.json', BASE + 'novela/t2.json'], gets
    assert '9 entrada(s) do manifesto' in saida and '5 vídeo(s)' in saida, saida
    assert 'falha' not in saida.lower().replace('0 falha', ''), saida
    assert 'tudo no ar' in saida, saida


def teste_entrada_404_tamanho_diferente_e_erro_de_rede_sao_listados_e_sai_com_1():
    s = servidor_completo()
    del s.arquivos[BASE + 'imagens/t1c1.webp']                               # 404
    s.cabecas[BASE + 'narracao/catolico/t1c1.m4a'] = (200, 5)              # outro tamanho
    s.cabecas[BASE + 'terco/marcas.json'] = urllib.error.URLError('sem rota')   # rede
    s.cabecas[BASE + 'novela/t1c1.srt'] = (200, None)                      # sem Content-Length
    with s.instalado():
        codigo, saida = rodar('--base', BASE)
    assert codigo == 1, saida
    linhas = [l.strip() for l in saida.splitlines() if l.startswith('  - ')]
    assert len(linhas) == 4, saida
    assert any('imagens/t1c1.webp' in l and 'HTTP 404' in l for l in linhas), linhas
    assert any('narracao/catolico/t1c1.m4a' in l and 'Content-Length 5' in l and '21' in l
               for l in linhas), linhas
    assert any('terco/marcas.json' in l and 'URLError' in l for l in linhas), linhas
    assert any('novela/t1c1.srt' in l and 'nenhum' in l for l in linhas), linhas
    assert '4 falha(s)' in saida, saida
    # As outras entradas e os vídeos continuam conferidos (a lista é completa).
    assert '9 entrada(s) do manifesto' in saida and '5 vídeo(s)' in saida, saida


def teste_video_fora_do_ar_e_listado_pela_url_que_o_app_pede():
    s = servidor_completo()
    del s.arquivos[VIDEOS + 'video/t1/02-evangelico.mp4']
    s.cabecas[VIDEOS + 'video/t2/01-catolico.mp4'] = (200, 1)
    with s.instalado():
        codigo, saida = rodar('--base', BASE)
    assert codigo == 1, saida
    assert f'{VIDEOS}video/t1/02-evangelico.mp4' in saida and 'HTTP 404' in saida, saida
    assert f'{VIDEOS}video/t2/01-catolico.mp4' in saida and 'Content-Length 1' in saida, saida
    assert 't2c1' in saida, 'o capítulo na mensagem'
    assert '2 falha(s)' in saida, saida


def teste_manifesto_publicado_diferente_do_local_e_falha_que_diz_que_o_push_nao_chegou():
    s = servidor_completo()
    with tempfile.TemporaryDirectory() as tmp:
        midia = Path(tmp)
        # Igual ao publicado: passa.
        (midia / 'manifesto.json').write_bytes(s.arquivos[BASE + 'manifesto.json'])
        with s.instalado():
            codigo, saida = rodar('--base', BASE, '--midia', str(midia))
        assert codigo == 0, saida
        assert 'manifesto publicado é o deste repositório' in saida, saida
        # Diferente (uma entrada a mais no local): falha, e diz o quê.
        local = json.loads((midia / 'manifesto.json').read_text(encoding='utf-8'))
        local['arquivos']['novela/t3.json'] = {'bytes': 5, 'sha256': 'c' * 64}
        (midia / 'manifesto.json').write_text(json.dumps(local), encoding='utf-8')
        with s.instalado():
            codigo, saida = rodar('--base', BASE, '--midia', str(midia))
        assert codigo == 1, saida
        assert 'não é o deste repositório' in saida and 'push' in saida and 'novela/t3.json' in saida, saida
        # Sem manifesto local: nada a comparar, só o aviso.
        (midia / 'manifesto.json').unlink()
        with s.instalado():
            codigo, saida = rodar('--base', BASE, '--midia', str(midia))
        assert codigo == 0 and 'sem manifesto.json local' in saida, saida


def teste_manifesto_publicado_que_nao_baixa_ou_nao_le_para_na_hora():
    s = Servidor()
    with s.instalado():
        codigo, saida = rodar('--base', BASE)
    assert codigo == 1 and 'manifesto.json' in saida and 'HTTP 404' in saida, saida
    assert [m for m, _ in s.pedidos] == ['GET'], 'nenhum HEAD sem o manifesto'
    s.publicar(BASE, 'manifesto.json', b'{ isto nao e json')
    with s.instalado():
        codigo, saida = rodar('--base', BASE)
    assert codigo == 1 and 'manifesto.json' in saida and 'não é um JSON' in saida, saida


def teste_so_novela_confere_so_o_que_e_da_novela():
    s = servidor_completo()
    with s.instalado():
        codigo, saida = rodar('--base', BASE, '--so-novela')
    assert codigo == 0, saida
    cabecas = [url for metodo, url in s.pedidos if metodo == 'HEAD' and url.startswith(BASE)]
    assert sorted(cabecas) == sorted(BASE + c for c in (
        'novela/temporadas.json', 'novela/t1.json', 'novela/t2.json', 'novela/t1c1.srt',
        'imagens/t1c1.webp', 'narracao/catolico/t1c1.m4a')), cabecas
    assert '6 entrada(s) do manifesto' in saida and '5 vídeo(s)' in saida, saida


def teste_indice_da_novela_fora_do_ar_ou_sem_base_e_falha():
    s = servidor_completo()
    del s.arquivos[BASE + 'novela/temporadas.json']
    with s.instalado():
        codigo, saida = rodar('--base', BASE)
    assert codigo == 1 and 'novela/temporadas.json' in saida, saida
    assert not any(url.startswith(VIDEOS) for _, url in s.pedidos), 'sem índice, nenhum vídeo'
    s = servidor_completo()
    s.publicar(BASE, 'novela/temporadas.json', {'versao': 1, 'videos': 'sem-barra', 'temporadas': []})
    with s.instalado():
        codigo, saida = rodar('--base', BASE)
    assert codigo == 1 and 'videos' in saida and 'sem-barra' in saida, saida
    # Sem novela publicada (nenhum índice no manifesto): só o manifesto.
    s = Servidor()
    s.publicar(BASE, 'hinos/x.m4a', b'h' * 3)
    s.publicar(BASE, 'manifesto.json', manifesto({'hinos/x.m4a': 3}))
    with s.instalado():
        codigo, saida = rodar('--base', BASE)
    assert codigo == 0 and 'sem novela publicada' in saida, saida


def teste_base_sem_barra_e_arrumada_e_a_padrao_e_o_servidor_de_midia():
    s = servidor_completo()
    with s.instalado():
        codigo, saida = rodar('--base', BASE.rstrip('/'))
    assert codigo == 0, saida
    assert cs.BASE_PADRAO == 'https://midia.manhadefe.com.br/'


def teste_cabeca_faz_head_pelo_urllib_e_le_status_e_content_length():
    """O HEAD de verdade com o urlopen trocado (nenhum socket): método HEAD,
    tempo-limite, (status, Content-Length); o 404 vira (404, None) em vez
    de exceção; o erro de rede sobe."""
    pedidos = []

    class Resposta:
        def __init__(self, headers):
            self.headers, self.status = headers, 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def urlopen(pedido, timeout=None):
        pedidos.append((pedido.full_url, pedido.get_method(), timeout))
        if pedido.full_url.endswith('404.mp4'):
            raise urllib.error.HTTPError(pedido.full_url, 404, 'Not Found', {}, None)
        if pedido.full_url.endswith('rede.mp4'):
            raise urllib.error.URLError('sem rota')
        return Resposta({'Content-Length': '250865'} if 'com' in pedido.full_url else {})

    real = cs.urllib.request.urlopen
    cs.urllib.request.urlopen = urlopen
    try:
        assert cs.cabeca('https://x.invalid/com.mp4') == (200, 250865)
        assert cs.cabeca('https://x.invalid/sem.mp4') == (200, None)
        assert cs.cabeca('https://x.invalid/404.mp4') == (404, None)
        try:
            cs.cabeca('https://x.invalid/rede.mp4')
        except urllib.error.URLError:
            pass
        else:
            raise AssertionError('o erro de rede sobe')
    finally:
        cs.urllib.request.urlopen = real
    assert pedidos[0] == ('https://x.invalid/com.mp4', 'HEAD', 20), pedidos


# ---------------------------------------------------------------------------

def main():
    """Roda tudo sem pytest."""
    testes = [(nome, obj) for nome, obj in sorted(globals().items())
              if nome.startswith('teste_') and callable(obj)]
    falhas = 0
    for nome, teste in testes:
        try:
            teste()
            print(f'ok    {nome}')
        except Exception:  # noqa: BLE001
            falhas += 1
            print(f'FALHA {nome}')
            traceback.print_exc()
    print(f'{chr(10)}{len(testes) - falhas} ok, {falhas} falha(s)')
    return 1 if falhas else 0


if __name__ == '__main__':
    sys.exit(main())
