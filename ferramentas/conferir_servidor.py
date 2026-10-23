#!/usr/bin/env python3
"""Confere, DEPOIS do push, que o servidor de mídia serve o que o manifesto
publicado promete (FM1): um HEAD em cada entrada do manifesto em
https://midia.manhadefe.com.br/ — 200 e Content-Length igual aos bytes do
manifesto — e, com a novela publicada, um HEAD em cada vídeo pela base
`videos` do índice (a URL que o app vai pedir; o vídeo compartilhado pelas
duas tradições é conferido uma vez). Com --midia, confere antes que o
manifesto publicado é o manifesto.json local (senão o push não chegou ao
Pages, ou falta commit). Lista o que falhou e sai com 1; nada falhou, 0.
Entra no roteiro do DIA DA PUBLICAÇÃO da temporada, depois do push e dos
~10 min de propagação.

Nunca escreve nada: só HEAD e GET nas URLs públicas.

Uso:
  python ferramentas/conferir_servidor.py --midia .               # tudo, e o manifesto local
  python ferramentas/conferir_servidor.py --midia . --so-novela   # só o que é da novela
  python ferramentas/conferir_servidor.py --base https://midia.manhadefe.com.br/
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

BASE_PADRAO = 'https://midia.manhadefe.com.br/'
AGENTE = 'manhadefe-conferir-servidor'
TRADICOES = ('catolico', 'evangelico')
INDICE_DA_NOVELA = 'novela/temporadas.json'
# O que é da novela no manifesto: o índice, as temporadas e as legendas
# (novela/), e a capa e as vozes dos capítulos.
_DA_NOVELA = re.compile(r'novela/.+|imagens/t\d+c\d+\.webp|narracao/(?:catolico|evangelico)/t\d+c\d+\.m4a',
                        re.ASCII)


# ---------------------------------------------------------------------------
# O HTTP (os pontos que os testes trocam por dublês)
# ---------------------------------------------------------------------------

def cabeca(url, tempo=20):
    """(status, Content-Length ou None) de um HEAD em `url`; o erro HTTP
    vira (código, None), o de rede sobe."""
    pedido = urllib.request.Request(url, method='HEAD', headers={'User-Agent': AGENTE})
    try:
        with urllib.request.urlopen(pedido, timeout=tempo) as resposta:  # noqa: S310 — só http(s)
            tamanho = resposta.headers.get('Content-Length')
            status = getattr(resposta, 'status', 200)
    except urllib.error.HTTPError as e:
        return e.code, None
    return status, (int(tamanho) if tamanho is not None and tamanho.strip().isdigit() else None)


def baixar(url, tempo=60):
    """Os bytes de um GET em `url`; erro HTTP ou de rede sobe."""
    pedido = urllib.request.Request(url, headers={'User-Agent': AGENTE})
    with urllib.request.urlopen(pedido, timeout=tempo) as resposta:  # noqa: S310 — só http(s)
        return resposta.read()


# ---------------------------------------------------------------------------

def _milhar(n):
    return f'{n:,}'.replace(',', '.')


def _descrever(erro):
    if isinstance(erro, urllib.error.HTTPError):
        return f'HTTP {erro.code}'
    return f'{type(erro).__name__}: {erro}'[:300]


def _json_publicado(url):
    """(o JSON de `url`, None) ou (None, o problema)."""
    try:
        bruto = baixar(url)
    except Exception as e:  # noqa: BLE001 — qualquer erro vira texto
        return None, _descrever(e)
    try:
        return json.loads(bruto.decode('utf-8')), None
    except (ValueError, UnicodeDecodeError) as e:
        return None, f'não é um JSON válido ({e})'


def ler_manifesto_publicado(base):
    """(o manifesto, os bytes dele, None) ou (None, None, o problema)."""
    url = base + 'manifesto.json'
    try:
        bruto = baixar(url)
    except Exception as e:  # noqa: BLE001
        return None, None, f'manifesto.json: {_descrever(e)} (em {url})'
    try:
        dados = json.loads(bruto.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        return None, None, f'manifesto.json: não é um JSON válido ({e})'
    arquivos = dados.get('arquivos') if isinstance(dados, dict) else None
    if not isinstance(arquivos, dict):
        return None, None, 'manifesto.json: não é um JSON de manifesto (sem "arquivos")'
    return dados, bruto, None


def comparar_com_o_local(bruto, midia, base):
    """(a falha ou None, a nota): o manifesto publicado é o manifesto.json
    de `midia`? Diferente = o push não chegou ao Pages, ou falta commit —
    o resto da conferência ainda roda, mas a saída é 1."""
    local = Path(midia) / 'manifesto.json'
    if not local.exists():
        return None, f'sem manifesto.json local em {midia}: nada a comparar'
    de_casa = local.read_bytes()
    if de_casa == bruto:
        return None, 'o manifesto publicado é o deste repositório'
    detalhe = ''
    try:
        publicado = json.loads(bruto.decode('utf-8'))['arquivos']
        daqui = json.loads(de_casa.decode('utf-8'))['arquivos']
        so_local = sorted(set(daqui) - set(publicado))
        so_publicado = sorted(set(publicado) - set(daqui))
        mudados = sorted(c for c in set(daqui) & set(publicado) if daqui[c] != publicado[c])
        partes = [f'{len(lista)} {rotulo}: {", ".join(lista[:5])}{"…" if len(lista) > 5 else ""}'
                  for rotulo, lista in (('só aqui', so_local), ('só no servidor', so_publicado),
                                        ('com outros bytes/sha', mudados)) if lista]
        detalhe = '; '.join(partes) or 'o mesmo conteúdo em outra forma'
    except (ValueError, KeyError, TypeError, AttributeError):
        detalhe = 'o local não é um manifesto válido'
    return (f'o manifesto publicado em {base} não é o deste repositório ({detalhe}) — o push '
            'chegou ao Pages? Confira commit e push; a propagação leva ~10 min'), None


def conferir_objeto(url, esperado):
    """None se `url` serve o objeto (200 e Content-Length = `esperado`);
    senão o motivo."""
    try:
        status, tamanho = cabeca(url)
    except Exception as e:  # noqa: BLE001
        return _descrever(e)
    if status != 200:
        return f'HTTP {status}'
    if tamanho != esperado:
        dado = 'nenhum' if tamanho is None else _milhar(tamanho)
        return f'Content-Length {dado} — o manifesto/JSON diz {_milhar(esperado)} bytes'
    return None


def conferir_todos(alvos, paralelo):
    """`alvos`: [(rótulo, url, bytes)] -> as falhas "rótulo: motivo", na
    ordem dos alvos (os HEADs em paralelo)."""
    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as pool:
        motivos = list(pool.map(lambda alvo: conferir_objeto(alvo[1], alvo[2]), alvos))
    return [f'{rotulo}: {motivo}' for (rotulo, _, _), motivo in zip(alvos, motivos) if motivo]


def alvos_do_manifesto(base, manifesto, so_novela):
    """[(chave, url, bytes)] das entradas do manifesto (só as da novela com
    `so_novela`); a entrada sem bytes inteiros vira falha."""
    alvos, falhas = [], []
    for chave, dados in sorted(manifesto['arquivos'].items()):
        if so_novela and not _DA_NOVELA.fullmatch(chave):
            continue
        tamanho = dados.get('bytes') if isinstance(dados, dict) else None
        if not isinstance(tamanho, int) or isinstance(tamanho, bool):
            falhas.append(f'{chave}: o manifesto não diz os bytes')
            continue
        alvos.append((chave, base + chave, tamanho))
    return alvos, falhas


def alvos_dos_videos(base, manifesto):
    """([(rótulo, url, bytes)] dos vídeos pela base `videos` do índice —
    o compartilhado pelas duas tradições uma vez só —, [falhas], a nota
    quando não há novela publicada, e a base)."""
    if INDICE_DA_NOVELA not in manifesto['arquivos']:
        return [], [], f'sem novela publicada (o manifesto não cita {INDICE_DA_NOVELA})', None
    indice, erro = _json_publicado(base + INDICE_DA_NOVELA)
    if erro:
        return [], [f'{INDICE_DA_NOVELA}: {erro}'], None, None
    videos = indice.get('videos') if isinstance(indice, dict) else None
    if (not isinstance(videos, str) or not videos.endswith('/')
            or urlparse(videos).scheme not in ('http', 'https') or not urlparse(videos).netloc):
        return [], [f'{INDICE_DA_NOVELA}: a base "videos" ({videos}) não é uma URL terminada em /'], \
            None, None
    falhas, vistos = [], {}
    for resumo in (indice.get('temporadas') if isinstance(indice.get('temporadas'), list) else []):
        arquivo = resumo.get('arquivo') if isinstance(resumo, dict) else None
        if not isinstance(arquivo, str):
            falhas.append(f'{INDICE_DA_NOVELA}: uma temporada sem "arquivo"')
            continue
        temporada, erro = _json_publicado(base + arquivo)
        if erro:
            falhas.append(f'{arquivo}: {erro}')
            continue
        capitulos = temporada.get('capitulos') if isinstance(temporada, dict) else None
        for cap in capitulos if isinstance(capitulos, list) else []:
            id_ = cap.get('id') if isinstance(cap, dict) else None
            video = cap.get('video') if isinstance(cap, dict) else None
            for t in TRADICOES:
                v = video.get(t) if isinstance(video, dict) else None
                if (not isinstance(v, dict) or not isinstance(v.get('arquivo'), str)
                        or not isinstance(v.get('bytes'), int) or isinstance(v.get('bytes'), bool)):
                    falhas.append(f'{arquivo}: capítulo {id_} sem video.{t} (arquivo e bytes)')
                    continue
                url = videos + v['arquivo']
                if url in vistos:
                    vistos[url][1].append(t)
                    continue
                vistos[url] = (id_, [t], v['bytes'])
    alvos = [(f'{url} ({id_}, {" e ".join(ts)})', url, tamanho)
             for url, (id_, ts, tamanho) in vistos.items()]
    return alvos, falhas, None, videos


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--base', default=BASE_PADRAO,
                    help=f'a base pública do servidor de mídia (padrão: {BASE_PADRAO})')
    ap.add_argument('--midia', help='raiz de mídia local: confere que o manifesto publicado é o '
                                    'manifesto.json dela (o push chegou?). Sem ela, não compara')
    ap.add_argument('--so-novela', action='store_true',
                    help='só o que é da novela: novela/, as capas e as vozes dos capítulos, e os vídeos')
    ap.add_argument('--paralelo', type=int, default=8, help='HEADs ao mesmo tempo (padrão: 8)')
    args = ap.parse_args(argv)
    base = args.base.rstrip('/') + '/'
    manifesto, bruto, erro = ler_manifesto_publicado(base)
    if erro:
        print(f'servidor {base}: {erro} — nada mais foi conferido')
        return 1
    falhas = []
    if args.midia:
        falha, nota = comparar_com_o_local(bruto, args.midia, base)
        if falha:
            falhas.append(falha)
        else:
            print(f'manifesto local: {nota}')
    else:
        print('manifesto local: não comparado (passe --midia . para conferir que o push chegou)')
    entradas, falhas_das_entradas = alvos_do_manifesto(base, manifesto, args.so_novela)
    falhas += falhas_das_entradas + conferir_todos(entradas, args.paralelo)
    videos, falhas_dos_videos, nota, base_dos_videos = alvos_dos_videos(base, manifesto)
    falhas += falhas_dos_videos + conferir_todos(videos, args.paralelo)
    dos_videos = (f'{len(videos)} vídeo(s) conferido(s) em {base_dos_videos}' if base_dos_videos
                  else nota or 'os vídeos não puderam ser listados')
    print(f'servidor {base}: {len(entradas)} entrada(s) do manifesto conferida(s) por HEAD '
          f'(200 e Content-Length = bytes); {dos_videos}')
    if falhas:
        print(f'{len(falhas)} falha(s):')
        for falha in falhas:
            print(f'  - {falha}')
        return 1
    print('tudo no ar.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
