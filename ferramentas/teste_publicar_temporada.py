#!/usr/bin/env python3
"""Testes de publicar_temporada.py. Nada sobe ao R2, nenhuma voz é gerada e
o Dart não roda: a entrega é sintética (vídeos `testsrc` 720x1280 com áudio
senoidal, capa 1080x1350 e SRT gerados aqui pelo ffmpeg, medidos pelo
ffprobe de verdade), a publicação roda com --simular numa pasta temporária,
e o caminho real (R2, voz, manifesto e lint) roda com dublês no lugar do
boto3 e dos comandos.

  python ferramentas/teste_publicar_temporada.py          # sem pytest
  python -m pytest ferramentas/teste_publicar_temporada.py

Os arquivos sintéticos são gerados uma vez por processo e copiados para
cada entrega; cada teste tem a sua pasta temporária.
"""
import atexit
import contextlib
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import urllib.error
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publicar_temporada as pt  # noqa: E402

BASE = 'https://videos.exemplo.invalid/'

REFLEXAO = ('José guardava os sonhos no peito e esperava. Os irmãos não entendiam a túnica '
            'nem a paciência dele. Hoje, olhe para a sua casa com calma. Existe alguém '
            'esperando uma palavra boa? Diga essa palavra antes do fim do dia, sem pressa '
            'e sem medo.')  # 45 palavras

SRT_VALIDO = ('1\n00:00:00,200 --> 00:00:01,800\nNo princípio, a promessa.\n\n'
              '2\n00:00:01,800 --> 00:00:03,600\nE a esperança de José.\n')


# ---------------------------------------------------------------------------
# Mídia sintética (uma vez por processo)
# ---------------------------------------------------------------------------

_MIDIA = {}


def _ffmpeg(*args):
    r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'ffmpeg falhou: {r.stderr.strip()[:400]}')


def video(destino, largura, altura, segundos, frequencia, pix_fmt='yuv420p'):
    _ffmpeg('-f', 'lavfi', '-i', f'testsrc=size={largura}x{altura}:rate=25:duration={segundos}',
            '-f', 'lavfi', '-i', f'sine=frequency={frequencia}:sample_rate=44100:duration={segundos}',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', pix_fmt,
            '-c:a', 'aac', '-b:a', '64k', '-shortest', str(destino))
    return destino


def capa(destino, largura, altura):
    _ffmpeg('-f', 'lavfi', '-i', f'testsrc2=size={largura}x{altura}:rate=1', '-frames:v', '1',
            '-c:v', 'libwebp', '-quality', '60', str(destino))
    return destino


def midia_sintetica():
    """{nome: Path} dos arquivos que as entregas dos testes copiam."""
    if not _MIDIA:
        pasta = Path(tempfile.mkdtemp(prefix='publicar-temporada-midia-'))
        atexit.register(shutil.rmtree, str(pasta), True)
        _MIDIA.update(
            catolico=video(pasta / 'catolico.mp4', 720, 1280, 4, 440),
            evangelico=video(pasta / 'evangelico.mp4', 720, 1280, 4, 660),
            estreito=video(pasta / 'estreito.mp4', 640, 1280, 4, 440),
            longo=video(pasta / 'longo.mp4', 720, 1280, 7, 440),
            cinco=video(pasta / 'cinco.mp4', 720, 1280, 5, 660),
            # Outro vídeo válido de 4 s (outro conteúdo, outro sha256).
            outro=video(pasta / 'outro.mp4', 720, 1280, 4, 550),
            # h264 High 4:4:4, High 10 e High 4:2:2: o ffprobe diz h264, mas
            # muito Android não toca.
            yuv444=video(pasta / 'yuv444.mp4', 720, 1280, 4, 440, pix_fmt='yuv444p'),
            yuv420p10=video(pasta / 'yuv420p10.mp4', 720, 1280, 4, 440, pix_fmt='yuv420p10le'),
            yuv422=video(pasta / 'yuv422.mp4', 720, 1280, 4, 440, pix_fmt='yuv422p'),
            # O mesmo 4:2:0 de 8 bits, com a faixa cheia de cor (R8-M): passa.
            yuvj420p=video(pasta / 'yuvj420p.mp4', 720, 1280, 4, 440, pix_fmt='yuvj420p'),
            capa=capa(pasta / 'capa.webp', 1080, 1350),
            capa_errada=capa(pasta / 'capa-errada.webp', 1000, 1350))
    return _MIDIA


# ---------------------------------------------------------------------------
# A entrega
# ---------------------------------------------------------------------------

def capitulo(n, data, duracao=4):
    return {'n': n, 'data': data, 'titulo': f'O sonhador, parte {n}',
            'gancho': 'Um pai, doze filhos e uma túnica.',
            'referenciaBiblica': 'Gênesis 37,3',
            'versiculo': 'Israel amava José mais do que todos os outros filhos.',
            'reflexao': REFLEXAO,
            'oracao': 'Senhor, cuida da minha família e ensina-nos a amar. Amém.',
            'duracaoS': duracao}


def datas(inicio, quantas):
    from datetime import date, timedelta
    d = date.fromisoformat(inicio)
    return [(d + timedelta(days=i)).isoformat() for i in range(quantas)]


def entrega_valida(tmp, capitulos=2, inicio='2026-11-10', id_='t1', titulo='José do Egito',
                   nome='entrega'):
    """Uma entrega que passa: `capitulos` capítulos de 4 s a partir de
    `inicio`; só o capítulo 1 tem legenda."""
    m = midia_sintetica()
    pasta = Path(tmp) / nome
    pasta.mkdir(parents=True)
    temporada = {'id': id_, 'titulo': titulo, 'inicio': inicio,
                 'capitulos': [capitulo(n, d) for n, d in enumerate(datas(inicio, capitulos), 1)]}
    escrever_temporada(pasta, temporada)
    for n in range(1, capitulos + 1):
        shutil.copyfile(m['catolico'], pasta / f'{n:02d}-catolico.mp4')
        shutil.copyfile(m['evangelico'], pasta / f'{n:02d}-evangelico.mp4')
        shutil.copyfile(m['capa'], pasta / f'{n:02d}.webp')
    (pasta / '01.srt').write_text(SRT_VALIDO, encoding='utf-8', newline='')
    # Um arquivo que não é da entrega (como o "LEIA" do ensaio): ignorado.
    (pasta / 'LEIA.txt').write_text('não publicar', encoding='utf-8')
    return pasta


def escrever_temporada(pasta, temporada):
    (Path(pasta) / 'temporada.json').write_text(
        json.dumps(temporada, ensure_ascii=False, indent=2), encoding='utf-8')


def editar_temporada(pasta, mudar):
    temporada = json.loads((Path(pasta) / 'temporada.json').read_text(encoding='utf-8'))
    mudar(temporada)
    escrever_temporada(pasta, temporada)


def publicar(pasta, midia, *extra, videos_base=BASE):
    """main() em --simular; devolve (código, o que imprimiu)."""
    argv = [str(pasta), '--simular', '--midia', str(midia)]
    if videos_base:
        argv += ['--videos-base', videos_base]
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        codigo = pt.main(argv + list(extra))
    return codigo, saida.getvalue()


def deve_recusar(pasta, midia, *trechos, extra=()):
    """A publicação simulada sai com 1, lista cada trecho pedido e não
    escreve nada em `midia`."""
    antes = sorted(p.relative_to(midia).as_posix() for p in Path(midia).rglob('*')) \
        if Path(midia).exists() else None
    codigo, saida = publicar(pasta, midia, *extra)
    assert codigo == 1, (codigo, saida)
    for trecho in trechos:
        assert trecho in saida, (trecho, saida)
    depois = sorted(p.relative_to(midia).as_posix() for p in Path(midia).rglob('*')) \
        if Path(midia).exists() else None
    assert depois == antes, f'escreveu algo: {antes} -> {depois}'
    return saida


def sha256_de(caminho):
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# A publicação simulada que passa
# ---------------------------------------------------------------------------

def teste_simular_escreve_a_temporada_no_formato_do_app_com_bytes_e_sha256():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        midia = Path(tmp) / 'midia'
        codigo, saida = publicar(pasta, midia)
        assert codigo == 0, saida
        bruto = (midia / 'novela' / 't1.json').read_bytes()
        assert not bruto.startswith(b'\xef\xbb\xbf') and b'\r' not in bruto
        assert bruto.decode('utf-8').startswith('{\n  "id": "t1",\n'), 'indentação de 2 espaços'
        temporada = json.loads(bruto.decode('utf-8'))
        assert (temporada['id'], temporada['titulo'], temporada['inicio']) == \
               ('t1', 'José do Egito', '2026-11-10')
        c1, c2 = temporada['capitulos']
        assert (c1['id'], c1['n'], c1['data']) == ('t1c1', 1, '2026-11-10')
        assert (c2['id'], c2['n'], c2['data']) == ('t1c2', 2, '2026-11-11')
        assert c1['capa'] == 'assets/images/cartoes/t1c1.webp'
        assert c2['capa'] == 'assets/images/cartoes/t1c2.webp'
        assert c1['legenda'] == 'novela/t1c1.srt'
        assert 'legenda' not in c2, 'sem SRT, sem legenda'
        for c in (c1, c2):
            for campo in ('titulo', 'gancho', 'referenciaBiblica', 'versiculo', 'reflexao',
                          'oracao', 'duracaoS'):
                assert c[campo] == capitulo(c['n'], c['data'])[campo], campo
            for tradicao in ('catolico', 'evangelico'):
                v = c['video'][tradicao]
                fonte = pasta / f'{c["n"]:02d}-{tradicao}.mp4'
                assert v == {'arquivo': f'video/t1/{c["n"]:02d}-{tradicao}.mp4',
                             'bytes': fonte.stat().st_size, 'sha256': sha256_de(fonte)}, v
        # O índice: a base dos vídeos e a temporada.
        indice = json.loads((midia / 'novela' / 'temporadas.json').read_text(encoding='utf-8'))
        assert indice == {'versao': 1, 'videos': BASE, 'temporadas': [
            {'id': 't1', 'titulo': 'José do Egito', 'inicio': '2026-11-10', 'fim': '2026-11-11',
             'capitulos': 2, 'arquivo': 'novela/t1.json'}]}
        # Capas e legendas copiadas com o nome do capítulo.
        assert (midia / 'imagens' / 't1c1.webp').read_bytes() == (pasta / '01.webp').read_bytes()
        assert (midia / 'imagens' / 't1c2.webp').read_bytes() == (pasta / '02.webp').read_bytes()
        assert (midia / 'novela' / 't1c1.srt').read_bytes() == (pasta / '01.srt').read_bytes()
        # Só isso: nada de voz, de manifesto nem de vídeo na raiz de mídia.
        escritos = sorted(p.relative_to(midia).as_posix() for p in midia.rglob('*') if p.is_file())
        assert escritos == ['imagens/t1c1.webp', 'imagens/t1c2.webp', 'novela/t1.json',
                            'novela/t1c1.srt', 'novela/temporadas.json'], escritos
        # O resumo diz o que faria e lembra a regra do push.
        assert 'subiria' in saida and 'video/t1/01-catolico.mp4' in saida
        assert 'texto_narrado.dart' in saida and 'gerar_manifesto.dart' in saida
        assert 'lint_conteudo.dart' in saida and BASE in saida
        assert 'push SÓ com OK do Gregory' in saida


def teste_simular_tira_o_bom_da_legenda_copiada():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        (pasta / '01.srt').write_bytes(b'\xef\xbb\xbf' + SRT_VALIDO.encode('utf-8'))
        midia = Path(tmp) / 'midia'
        assert publicar(pasta, midia)[0] == 0
        assert (midia / 'novela' / 't1c1.srt').read_bytes() == SRT_VALIDO.encode('utf-8')


def teste_indice_mantem_as_outras_temporadas_em_ordem_e_substitui_a_de_mesmo_id():
    with tempfile.TemporaryDirectory() as tmp:
        midia = Path(tmp) / 'midia'
        (midia / 'novela').mkdir(parents=True)
        base_do_indice = 'https://pub-exemplo.r2.dev/'
        (midia / 'novela' / 'temporadas.json').write_text(json.dumps({
            'versao': 1, 'videos': base_do_indice, 'temporadas': [
                {'id': 't2', 'titulo': 'Natal', 'inicio': '2026-12-17', 'fim': '2026-12-23',
                 'capitulos': 7, 'arquivo': 'novela/t2.json'},
                # A versão anterior da t1: outras datas e 3 capítulos.
                {'id': 't1', 'titulo': 'Rascunho', 'inicio': '2026-11-01', 'fim': '2026-11-03',
                 'capitulos': 3, 'arquivo': 'novela/t1.json'}]}), encoding='utf-8')
        # Sobras da versão anterior: o capítulo 3 sumiu e o 2 perdeu a legenda.
        (midia / 'imagens').mkdir()
        for sobra in ('imagens/t1c3.webp', 'novela/t1c2.srt', 'novela/t1c3.srt',
                      'narracao/catolico/t1c3.m4a', 'narracao/evangelico/t1c3.m4a'):
            (midia / sobra).parent.mkdir(parents=True, exist_ok=True)
            (midia / sobra).write_bytes(b'velho')
        # E arquivos de outros que nunca são tocados.
        (midia / 'imagens' / 't2c3.webp').write_bytes(b'outra temporada')
        (midia / 'imagens' / 'comum-001.webp').write_bytes(b'cartao')
        pasta = entrega_valida(tmp)
        codigo, saida = publicar(pasta, midia, videos_base=None)
        assert codigo == 0, saida
        indice = json.loads((midia / 'novela' / 'temporadas.json').read_text(encoding='utf-8'))
        assert indice['videos'] == base_do_indice, 'sem --videos-base, a base do índice existente'
        assert [(t['id'], t['titulo'], t['inicio'], t['fim'], t['capitulos'])
                for t in indice['temporadas']] == [
            ('t1', 'José do Egito', '2026-11-10', '2026-11-11', 2),
            ('t2', 'Natal', '2026-12-17', '2026-12-23', 7)]
        for sobra in ('imagens/t1c3.webp', 'novela/t1c2.srt', 'novela/t1c3.srt',
                      'narracao/catolico/t1c3.m4a', 'narracao/evangelico/t1c3.m4a'):
            assert not (midia / sobra).exists(), sobra
        assert (midia / 'imagens' / 't2c3.webp').read_bytes() == b'outra temporada'
        assert (midia / 'imagens' / 'comum-001.webp').read_bytes() == b'cartao'


R2_FALSO = """Use this token for authenticating against the Cloudflare API:
Token value
tokenfalso1234567890abcdefghijklmnopqrstuvwxyzABCDEFG
Click to copy

Use the following credentials for S3 clients:
Access Key ID
0123456789abcdef0123456789abcdef
Click to copy

Secret Access Key
fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210
Click to copy

Use jurisdiction-specific endpoints for S3 clients:
Default
https://00112233445566778899aabbccddeeff.r2.cloudflarestorage.com
Click to copy

Public Development URL (19/10/2026): https://pub-exemplo123.r2.dev
"""


def teste_simular_nunca_le_o_arquivo_de_chaves_e_usa_o_marcador_da_url_publica():
    """R8-F: sem --videos-base e sem índice, a simulação usa o marcador
    "<Public Development URL>/" + prefixo; o arquivo de chaves nunca é lido
    (a URL de desenvolvimento do R2 não vai ao resumo nem aos JSONs)."""
    with tempfile.TemporaryDirectory() as tmp:
        chaves = Path(tmp) / 'R2.txt'
        chaves.write_text(R2_FALSO.replace(chr(10), chr(13) + chr(10)), encoding='utf-8')
        pasta = entrega_valida(tmp)
        midia = Path(tmp) / 'midia'
        lidas = []
        reais = pt.ler_chaves_r2, pt.url_publica_de
        pt.ler_chaves_r2 = lambda *a: lidas.append('ler_chaves_r2') or reais[0](*a)
        pt.url_publica_de = lambda *a: lidas.append('url_publica_de') or reais[1](*a)
        try:
            codigo, saida = publicar(pasta, midia, '--r2', str(chaves), '--r2-prefixo',
                                     'teste/midia', videos_base=None)
            # Nem um --r2 que daria erro ao ler (uma pasta) atrapalha: não é lido.
            codigo2, saida2 = publicar(pasta, Path(tmp) / 'midia2', '--r2', str(tmp),
                                       videos_base=None)
        finally:
            pt.ler_chaves_r2, pt.url_publica_de = reais
        assert codigo == 0, saida
        assert codigo2 == 0, saida2
        assert lidas == [], lidas
        indice = json.loads((midia / 'novela' / 'temporadas.json').read_text(encoding='utf-8'))
        assert indice['videos'] == '<Public Development URL>/teste/midia/'
        indice2 = json.loads((Path(tmp) / 'midia2' / 'novela' / 'temporadas.json')
                             .read_text(encoding='utf-8'))
        assert indice2['videos'] == '<Public Development URL>/'
        assert 'pub-exemplo123' not in saida + saida2
        assert all(b'pub-exemplo123' not in p.read_bytes() for p in midia.rglob('*') if p.is_file())
        # A chave no R2 leva o prefixo; o `arquivo` do JSON, não (o prefixo
        # está na base).
        assert 'teste/midia/video/t1/01-catolico.mp4' in saida
        temporada = json.loads((midia / 'novela' / 't1.json').read_text(encoding='utf-8'))
        assert temporada['capitulos'][0]['video']['catolico']['arquivo'] == 'video/t1/01-catolico.mp4'
        # As chaves secretas nunca aparecem.
        for segredo in ('0123456789abcdef0123456789abcdef', 'fedcba9876543210',
                        'tokenfalso', '00112233445566778899aabbccddeeff'):
            assert segredo not in saida


# Os valores de R2_FALSO, para conferir que nenhum chega à tela.
CONTA = '00112233445566778899aabbccddeeff'
ENDPOINT = f'https://{CONTA}.r2.cloudflarestorage.com'
CHAVE_DE_ACESSO = '0123456789abcdef0123456789abcdef'
SEGREDO = 'fedcba9876543210' * 4
O_QUE_IDENTIFICA_A_CONTA = (ENDPOINT, f'{CONTA}.r2.cloudflarestorage.com', CONTA, CHAVE_DE_ACESSO,
                            SEGREDO, 'r2.cloudflarestorage.com')


def chaves_falsas():
    return pt.ChavesR2(endpoint=ENDPOINT, access_key_id=CHAVE_DE_ACESSO, secret_access_key=SEGREDO,
                       url_publica='https://pub-exemplo123.r2.dev')


def nada_da_conta_em(texto):
    for valor in O_QUE_IDENTIFICA_A_CONTA:
        assert valor.lower() not in texto.lower(), (valor, texto)


def teste_limpar_mensagem_tira_endpoint_host_conta_e_chaves():
    """R8-A: a função única que limpa toda mensagem do R2, do botocore ou da
    rede — o endpoint inteiro, o host dele (em qualquer caixa, com o balde
    na frente), o id da conta e as chaves viram marcadores."""
    texto = (f'Could not connect to the endpoint URL: "{ENDPOINT}/manhadefe-video/x.mp4"; '
             f'host {CONTA.upper()}.R2.CloudflareStorage.com; '
             f'virtual manhadefe-video.{CONTA}.r2.cloudflarestorage.com:443; conta {CONTA}; '
             f'Credential={CHAVE_DE_ACESSO}/20261020/auto/s3/aws4_request; segredo {SEGREDO}; '
             'outra conta https://ffff0000ffff0000ffff0000ffff0000.r2.cloudflarestorage.com/y')
    limpo = pt.limpar_mensagem(texto, chaves_falsas())
    nada_da_conta_em(limpo)
    assert 'ffff0000ffff0000' not in limpo, limpo
    assert '"<endpoint do R2>/manhadefe-video/x.mp4"' in limpo, limpo
    assert 'conta <conta>;' in limpo and 'Credential=<chave>/20261020' in limpo, limpo
    assert 'segredo <chave>' in limpo, limpo
    # Sem as chaves (não lidas), o host genérico sai do mesmo jeito.
    nada_da_conta_em(pt.limpar_mensagem(f'em {ENDPOINT}/x', None))
    # A descrição: o nome do tipo, o Error.Code do ClientError, a mensagem limpa.
    from botocore.exceptions import ClientError
    erro = ClientError({'Error': {'Code': 'AccessDenied', 'Message': f'negado em {ENDPOINT}'}},
                       'PutObject')
    descricao = pt.descrever_erro(erro, chaves_falsas())
    assert descricao.startswith('ClientError (AccessDenied): '), descricao
    nada_da_conta_em(descricao)


def teste_chaves_do_r2_lidas_pelo_rotulo_sem_vazar_valor():
    with tempfile.TemporaryDirectory() as tmp:
        arquivo = Path(tmp) / 'R2.txt'
        arquivo.write_text(R2_FALSO, encoding='utf-8')
        chaves = pt.ler_chaves_r2(arquivo)
        assert chaves.access_key_id == '0123456789abcdef0123456789abcdef'
        assert chaves.secret_access_key == 'fedcba9876543210' * 4
        assert chaves.endpoint == 'https://00112233445566778899aabbccddeeff.r2.cloudflarestorage.com'
        assert chaves.url_publica == 'https://pub-exemplo123.r2.dev'
        for texto in (repr(chaves), str(chaves)):
            assert '0123456789abcdef' not in texto and 'fedcba98' not in texto
        # Sem um rótulo: o erro diz o rótulo, nunca um valor.
        arquivo.write_text(R2_FALSO.replace('Secret Access Key', 'Outra coisa'), encoding='utf-8')
        try:
            pt.ler_chaves_r2(arquivo)
        except ValueError as e:
            assert 'Secret Access Key' in str(e)
            assert 'fedcba98' not in str(e) and '0123456789abcdef' not in str(e)
        else:
            raise AssertionError('deveria ter recusado')


# ---------------------------------------------------------------------------
# O que a conferência recusa (tudo antes de qualquer escrita)
# ---------------------------------------------------------------------------

def teste_recusa_resolucao_errada_e_lista_todos_os_problemas():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        m = midia_sintetica()
        shutil.copyfile(m['estreito'], pasta / '02-evangelico.mp4')
        shutil.copyfile(m['capa_errada'], pasta / '01.webp')
        saida = deve_recusar(pasta, Path(tmp) / 'midia', '02-evangelico.mp4', '640x1280',
                             '01.webp', '1000x1350')
        assert '2 problema(s)' in saida, saida


def teste_recusa_pix_fmt_diferente_de_yuv420p_e_versoes_identicas():
    """R8-J: h264 que não é yuv420p (High 10, 4:4:4) passa no codec_name e não
    toca em muito Android; e o católico igual ao evangélico (mesmo sha256) é
    entrega trocada — a spec manda o bispo num e o pastor no outro."""
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        shutil.copyfile(midia_sintetica()['yuv444'], pasta / '01-catolico.mp4')
        shutil.copyfile(pasta / '02-catolico.mp4', pasta / '02-evangelico.mp4')
        saida = deve_recusar(pasta, Path(tmp) / 'midia', '01-catolico.mp4', 'yuv444p', 'yuv420p',
                             'cap. 2', '02-catolico.mp4 e 02-evangelico.mp4', 'mesmo sha256')
        assert '2 problema(s)' in saida, saida


def teste_yuvj420p_passa_com_aviso_e_10_bits_4_2_2_e_4_4_4_continuam_recusados():
    """R8-M: yuvj420p é o mesmo h264 de 8 bits 4:2:0, só com a faixa cheia de
    cor (comum em exportação de imagem/IA): passa, com um AVISO — na
    conferência e no resumo — que sugere exportar em yuv420p. Nunca recusa.
    Qualquer outro pix_fmt (10 bits, 4:2:2, 4:4:4) continua erro."""
    sugestao = 'exporte em yuv420p: -vf scale=out_range=tv -pix_fmt yuv420p'
    m = midia_sintetica()
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        shutil.copyfile(m['yuvj420p'], pasta / '01-catolico.mp4')
        avisos = []
        entrega, problemas = pt.conferir_entrega(pasta, avisos=avisos)
        assert entrega is not None and problemas == [], problemas
        assert len(avisos) == 1, avisos
        assert '01-catolico.mp4' in avisos[0] and 'yuvj420p' in avisos[0], avisos
        assert sugestao in avisos[0], avisos
        codigo, saida = publicar(pasta, Path(tmp) / 'midia')
        assert codigo == 0, saida
        assert sugestao in saida.split('== resumo')[1], 'o aviso vai ao resumo'
        # Com outro problema na entrega, o aviso sai junto — e não conta.
        editar_temporada(pasta, lambda t: t['capitulos'][1].update(oracao='Senhor, cuida de nós.'))
        saida = deve_recusar(pasta, Path(tmp) / 'midia-com-problema', 'Amém.', sugestao)
        assert '1 problema(s)' in saida, saida
        editar_temporada(pasta, lambda t: t['capitulos'][1].update(
            oracao='Senhor, cuida da minha família e ensina-nos a amar. Amém.'))
        # 10 bits, 4:2:2 e 4:4:4: erro, como antes.
        for nome, pix_fmt in (('yuv420p10', 'yuv420p10le'), ('yuv422', 'yuv422p'),
                              ('yuv444', 'yuv444p')):
            shutil.copyfile(m[nome], pasta / '01-catolico.mp4')
            saida = deve_recusar(pasta, Path(tmp) / f'midia-{nome}', '01-catolico.mp4',
                                 f'pix_fmt {pix_fmt}', 'tem de ser yuv420p')
            assert '1 problema(s)' in saida, saida


def teste_recusa_duracao_fora_de_2_segundos():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        m = midia_sintetica()
        shutil.copyfile(m['longo'], pasta / '01-catolico.mp4')
        shutil.copyfile(m['longo'], pasta / '01-evangelico.mp4')
        deve_recusar(pasta, Path(tmp) / 'midia', '01-catolico.mp4', '01-evangelico.mp4',
                     'duracaoS')


def teste_recusa_versoes_com_duracoes_diferentes():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        # 5 s cabe nos 2 s de folga de duracaoS = 4, mas as duas versões ficam
        # 1 s diferentes.
        shutil.copyfile(midia_sintetica()['cinco'], pasta / '02-evangelico.mp4')
        saida = deve_recusar(pasta, Path(tmp) / 'midia', 'cap. 2', 'versões')
        assert '1 problema(s)' in saida, saida


@contextlib.contextmanager
def duracoes_trocadas(por_arquivo):
    """O ffprobe de verdade, com a duração de alguns arquivos trocada (nome ->
    segundos, como o ffprobe a daria): os limites exatos sem depender da
    precisão do encoder."""
    real = pt.sondar

    def sondar(arquivo):
        medida = real(arquivo)
        if medida is not None and Path(arquivo).name in por_arquivo:
            medida = dict(medida, duracao=por_arquivo[Path(arquivo).name])
        return medida

    pt.sondar = sondar
    try:
        yield
    finally:
        pt.sondar = real


def teste_limites_exatos_da_duracao_2_s_e_entre_versoes_0_5_s():
    """R8-K (c): no limite passa, 1 ms além recusa — nos dois sentidos. As
    durações chegam do ffprobe como decimais (4.400000): 4,4 - 3,9 dá
    0,5000000000000004 em ponto flutuante e não pode recusar."""
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp, capitulos=1)   # duracaoS = 4
        (pasta / '01.srt').unlink()                # a legenda vai até 3,6 s

        def problemas(catolico, evangelico):
            with duracoes_trocadas({'01-catolico.mp4': catolico, '01-evangelico.mp4': evangelico}):
                entrega, lista = pt.conferir_entrega(pasta)
            assert entrega is not None
            return lista

        # duracaoS ± 2 s.
        assert problemas(6.0, 6.0) == []
        assert problemas(2.0, 2.0) == []
        acima = problemas(6.001, 6.001)
        assert len(acima) == 2 and all('6,001 s, mas duracaoS = 4' in p for p in acima), acima
        abaixo = problemas(1.999, 1.999)
        assert len(abaixo) == 2 and all('1,999 s, mas duracaoS = 4' in p for p in abaixo), abaixo
        # Católica x evangélica ± 0,5 s.
        assert 4.4 - 3.9 > 0.5, 'o caso de ponto flutuante que o teste quer cobrir'
        assert problemas(4.4, 3.9) == []
        assert problemas(3.9, 4.4) == []
        for catolico, evangelico in ((4.4, 3.899), (3.899, 4.4)):
            lista = problemas(catolico, evangelico)
            assert len(lista) == 1 and 'diferem 0,501 s' in lista[0], lista


def teste_recusa_video_maior_que_o_limite_que_e_parametro():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp, capitulos=1)
        entrega, problemas = pt.conferir_entrega(pasta, limite_de_bytes=1000)
        assert entrega is not None
        assert len(problemas) == 2, problemas
        assert all('1.000 bytes' in p for p in problemas), problemas
        # Com o limite padrão (25 MB), a mesma entrega passa.
        assert pt.conferir_entrega(pasta)[1] == []
        assert pt.LIMITE_DE_BYTES == 26_214_400


def _com_legenda(tmp, texto):
    pasta = entrega_valida(tmp)
    (pasta / '01.srt').write_text(texto, encoding='utf-8', newline='')
    return pasta


def teste_recusa_fala_com_duas_linhas():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = _com_legenda(tmp, SRT_VALIDO.replace('E a esperança de José.',
                                                     'E a esperança\nde José.'))
        deve_recusar(pasta, Path(tmp) / 'midia', '01.srt', 'fala 2', '2 linhas')


def teste_recusa_fala_com_mais_de_42_caracteres():
    with tempfile.TemporaryDirectory() as tmp:
        longa = 'O meu feixe se levantou, e os vossos se prostravam.'
        pasta = _com_legenda(tmp, SRT_VALIDO.replace('E a esperança de José.', longa))
        deve_recusar(pasta, Path(tmp) / 'midia', '01.srt', 'fala 2', f'{len(longa)} caracteres')
        # 42 em ponto passa.
        pasta2 = Path(tmp) / 'outra'
        shutil.copytree(pasta, pasta2)
        (pasta2 / '01.srt').write_text(SRT_VALIDO.replace('E a esperança de José.', 'x' * 42),
                                       encoding='utf-8', newline='')
        assert publicar(pasta2, Path(tmp) / 'midia2')[0] == 0


def teste_recusa_fala_com_menos_de_1_5_segundo():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = _com_legenda(tmp, SRT_VALIDO.replace('00:00:01,800 --> 00:00:03,600',
                                                     '00:00:01,800 --> 00:00:03,200'))
        deve_recusar(pasta, Path(tmp) / 'midia', '01.srt', 'fala 2', '1,4 s')


def teste_limite_exato_da_fala_1_5_s():
    """R8-K (c): 1,5 s em ponto passa; 1 ms a menos recusa."""
    um_e_meio = '1\n00:00:00,000 --> 00:00:01,500\nUm.\n'
    assert pt.conferir_legenda(um_e_meio, 4.0) == []
    assert pt.conferir_legenda(um_e_meio.replace('01,500', '01,499'), 4.0) == \
        ['fala 1 dura 1,499 s — o mínimo é 1,5 s']


def teste_linha_em_branco_antes_da_primeira_fala():
    """R8-L: a recusa diz onde está a linha (não "depois da fala 0")."""
    problemas = pt.conferir_legenda(chr(10) + SRT_VALIDO, 4.0)
    assert len(problemas) == 1, problemas
    assert problemas[0].startswith('linha em branco antes da primeira fala'), problemas
    assert 'fala 0' not in problemas[0]


def teste_recusa_legenda_que_o_app_nao_le_inteira():
    """O parser do app (video_player) para no primeiro bloco com menos de
    três linhas — uma linha em branco a mais no meio basta —, não abre a
    legenda cujo bloco não começa por número e pula a fala com o tempo fora
    do formato. E a fala não pode passar do fim do vídeo nem sobrepor a
    anterior."""
    with tempfile.TemporaryDirectory() as tmp:
        texto = ('1\n00:00:00,200 --> 00:00:01,800\nUm.\n\n\n'
                 '2\n00:00:01,800 --> 00:00:03,600\nDois.\n\n'
                 'três\n00:00:03,600 --> 00:00:05,600\nTrês.\n\n'
                 '4\n0:00:05,600 --> 00:00:07,600\nQuatro.\n\n'
                 '5\n00:00:01,000 --> 00:00:03,500\nCinco.\n')
        pasta = _com_legenda(tmp, texto)
        deve_recusar(pasta, Path(tmp) / 'midia', 'linha em branco', 'não começa por número',
                     'depois do fim do vídeo', 'formato', 'antes do fim da fala anterior')


def teste_recusa_data_que_pula_um_dia_e_data_que_nao_existe():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp, capitulos=3, inicio='2026-11-28')
        editar_temporada(pasta, lambda t: t['capitulos'][1].update(data='2026-11-30'))
        deve_recusar(pasta, Path(tmp) / 'midia', 'cap. 2', '2026-11-30', '2026-11-29')
        editar_temporada(pasta, lambda t: t['capitulos'][2].update(data='2026-11-31'))
        deve_recusar(pasta, Path(tmp) / 'midia', '2026-11-31')


def teste_recusa_id_e_numeracao_fora_do_formato():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)

        def mudar(t):
            t['id'] = 'jose-do-egito'
            t['capitulos'][1]['n'] = 3
            t['capitulos'][0]['duracaoS'] = 4.0
        editar_temporada(pasta, mudar)
        deve_recusar(pasta, Path(tmp) / 'midia', 'jose-do-egito', 'n=3', 'duracaoS')


def teste_recusa_textos_fora_da_medida():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)

        def mudar(t):
            c1, c2 = t['capitulos']
            c1['versiculo'] = 'v' * 181
            c1['reflexao'] = 'Curta demais para a medida.'
            c1['oracao'] = 'Senhor, cuida de nós.'
            c2['referenciaBiblica'] = 'Gênesis 37'
            c2['reflexao'] = REFLEXAO.replace('esperava.', 'esperava — e esperava — e esperava —')
        editar_temporada(pasta, mudar)
        deve_recusar(pasta, Path(tmp) / 'midia', '181 caracteres', '5 palavras', 'Amém.',
                     'Gênesis 37', '3 travessões')


def teste_reflexao_e_versiculo_medidos_no_texto_aparado():
    """R8-C: o app apara o texto (Capitulo.fromJson) e o lint mede o texto
    aparado — espaço nas pontas não é palavra nem caractere."""
    trinta_e_oito = ' '.join(['palavra'] * 38)
    assert pt.contar_palavras(trinta_e_oito) == 38
    assert pt.contar_palavras(' ' + trinta_e_oito + ' ') == 38
    assert pt.contar_palavras(chr(10) + '  ' + trinta_e_oito + chr(9) + ' ') == 38
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)

        def mudar(t):
            t['capitulos'][0]['reflexao'] = ' ' + trinta_e_oito + ' '
            t['capitulos'][1]['versiculo'] = '  ' + 'v' * 180 + ' '   # 180 aparado: passa
        editar_temporada(pasta, mudar)
        saida = deve_recusar(pasta, Path(tmp) / 'midia', 'cap. 1', '38 palavras')
        assert '1 problema(s)' in saida, saida


def teste_recusa_arquivo_que_falta_e_arquivo_que_sobra():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        (pasta / '02-evangelico.mp4').unlink()
        (pasta / '02.webp').unlink()
        shutil.copyfile(pasta / '01-catolico.mp4', pasta / '03-catolico.mp4')
        deve_recusar(pasta, Path(tmp) / 'midia', '02-evangelico.mp4', '02.webp',
                     '03-catolico.mp4')


def teste_recusa_sobreposicao_com_temporada_existente():
    with tempfile.TemporaryDirectory() as tmp:
        midia = Path(tmp) / 'midia'
        (midia / 'novela').mkdir(parents=True)
        (midia / 'novela' / 'temporadas.json').write_text(json.dumps({
            'versao': 1, 'videos': BASE, 'temporadas': [
                {'id': 't2', 'titulo': 'Outra', 'inicio': '2026-11-11', 'fim': '2026-11-17',
                 'capitulos': 7, 'arquivo': 'novela/t2.json'}]}), encoding='utf-8')
        pasta = entrega_valida(tmp)  # t1, 10 e 11/11
        deve_recusar(pasta, midia, 'sobrepõem', 't2')
        # Começando no dia seguinte ao fim da t2, passa.
        editar_temporada(pasta, lambda t: (t.update(inicio='2026-11-18'),
                                           t['capitulos'][0].update(data='2026-11-18'),
                                           t['capitulos'][1].update(data='2026-11-19')))
        assert publicar(pasta, midia)[0] == 0


def _resumo(id_, inicio, fim, capitulos):
    return {'id': id_, 'titulo': id_, 'inicio': inicio, 'fim': fim, 'capitulos': capitulos,
            'arquivo': f'novela/{id_}.json'}


def teste_indice_final_inteiro_conferido_antes_de_escrever():
    """R8-E: o app recusa o índice INTEIRO (IndiceDeTemporadas.fromJson) —
    a lista final, com as que já estavam, é conferida antes de qualquer
    escrita, não só a temporada nova contra as outras."""
    with tempfile.TemporaryDirectory() as tmp:
        midia = Path(tmp) / 'midia'
        (midia / 'novela').mkdir(parents=True)

        def indice(*temporadas):
            (midia / 'novela' / 'temporadas.json').write_text(json.dumps({
                'versao': 1, 'videos': BASE, 'temporadas': list(temporadas)}), encoding='utf-8')

        pasta = entrega_valida(tmp)   # t1, 10 e 11/11: não toca nenhuma das outras
        # Duas que já estavam se sobrepõem entre si.
        indice(_resumo('t2', '2026-12-01', '2026-12-07', 7),
               _resumo('t3', '2026-12-07', '2026-12-13', 7))
        deve_recusar(pasta, midia, 'sobrepõem', 't2 (2026-12-01 a 2026-12-07)',
                     't3 (2026-12-07 a 2026-12-13)')
        # O mesmo id duas vezes (em datas que não se tocam).
        indice(_resumo('t2', '2026-12-01', '2026-12-07', 7),
               _resumo('t2', '2026-12-20', '2026-12-26', 7))
        deve_recusar(pasta, midia, 'o id t2 aparece 2 vezes')
        # Arrumado, passa — e a temporada nova fica entre as outras, em ordem.
        indice(_resumo('t2', '2026-12-01', '2026-12-07', 7),
               _resumo('t0', '2026-10-21', '2026-10-22', 2))
        assert publicar(pasta, midia)[0] == 0
        final = json.loads((midia / 'novela' / 'temporadas.json').read_text(encoding='utf-8'))
        assert [t['id'] for t in final['temporadas']] == ['t0', 't1', 't2']


def teste_conferir_indice_tem_as_regras_do_app():
    """A função pura: cada regra do IndiceDeTemporadas.fromJson, listada."""
    ok = {'versao': 1, 'videos': BASE, 'temporadas': [
        _resumo('t1', '2026-11-10', '2026-11-16', 7), _resumo('t2', '2026-11-17', '2026-11-23', 7)]}
    assert pt.conferir_indice(ok) == []
    errado = json.loads(json.dumps(ok))
    errado['videos'] = 'https://videos.exemplo.invalid/novela'
    errado['temporadas'][0]['fim'] = '2026-11-17'          # 7 capítulos: o fim é dia 16
    errado['temporadas'][1]['arquivo'] = 'novela/outra.json'
    problemas = pt.conferir_indice(errado)
    assert len(problemas) == 4, problemas
    for trecho in ('termina em /', 't1 termina em 2026-11-17', '2026-11-16', 'novela/t2.json',
                   'sobrepõem'):
        assert any(trecho in p for p in problemas), (trecho, problemas)


def teste_simular_recusa_o_repositorio_real_e_sem_midia():
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        # Um "repositório real" de mentira: um padrão deste teste nunca é o real.
        real = Path(tmp) / 'midia-real'
        real.mkdir()
        padrao = pt.MIDIA_PADRAO
        pt.MIDIA_PADRAO = real
        try:
            for argv, trecho in (([str(pasta), '--simular'], '--midia'),
                                 ([str(pasta), '--simular', '--midia', str(real)], 'repositório real'),
                                 ([str(pasta), '--simular', '--midia', str(real / 'novela')],
                                  'repositório real')):
                try:
                    pt.main(argv + ['--videos-base', BASE])
                except SystemExit as e:
                    assert e.code != 0 and trecho in str(e.code), str(e.code)
                else:
                    raise AssertionError(f'deveria ter recusado {argv}')
        finally:
            pt.MIDIA_PADRAO = padrao
        assert not any(real.iterdir()), 'nada escrito no "real"'
    # E o padrão de verdade é este repositório.
    assert pt.MIDIA_PADRAO == Path(pt.__file__).resolve().parents[1]
    try:
        pt.conferir_raiz_da_simulacao(str(pt.MIDIA_PADRAO))
    except SystemExit as e:
        assert 'repositório real' in str(e.code)
    else:
        raise AssertionError('deveria ter recusado o repositório real')


def teste_simular_recusa_qualquer_repositorio_git_e_o_repositorio_do_app():
    """R8-G: rodando o script de uma CÓPIA, o "repositório real" dele é a
    cópia — a trava tem de reconhecer qualquer pasta com .git (ela ou uma
    acima dela; num worktree o .git é um arquivo) e o repositório do app,
    antes de qualquer escrita."""
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        repo = Path(tmp) / 'outro-repo'
        (repo / '.git').mkdir(parents=True)
        worktree = Path(tmp) / 'worktree'
        worktree.mkdir()
        (worktree / '.git').write_text('gitdir: ../outro-repo/.git/worktrees/x', encoding='utf-8')
        app = Path(tmp) / 'app-do-gregory'
        app.mkdir()
        recusas = ((repo, '.git'), (repo / 'novela', '.git'), (worktree, '.git'),
                   (app, 'repositório do app'), (app / 'build' / 'midia', 'repositório do app'))
        antes = sorted(p.relative_to(tmp).as_posix() for p in Path(tmp).rglob('*'))
        real = pt.REPOSITORIO_DO_APP
        pt.REPOSITORIO_DO_APP = app
        try:
            for midia, trecho in recusas:
                try:
                    publicar(pasta, midia)
                except SystemExit as e:
                    assert e.code != 0 and trecho in str(e.code), (midia, str(e.code))
                else:
                    raise AssertionError(f'deveria ter recusado {midia}')
            # O --app apontado também é o repositório do app.
            outro_app = Path(tmp) / 'outro-app'
            try:
                publicar(pasta, outro_app, '--app', str(outro_app))
            except SystemExit as e:
                assert 'repositório do app' in str(e.code), str(e.code)
            else:
                raise AssertionError('deveria ter recusado --midia igual a --app')
        finally:
            pt.REPOSITORIO_DO_APP = real
        assert sorted(p.relative_to(tmp).as_posix() for p in Path(tmp).rglob('*')) == antes, \
            'nada escrito'
    # O padrão de verdade é o app do Gregory, onde quer que o script esteja.
    assert pt.REPOSITORIO_DO_APP == Path('C:/Users/robot/dev/manha-de-fe-app')


# ---------------------------------------------------------------------------
# O caminho real, com dublês: R2, voz, manifesto e lint
# ---------------------------------------------------------------------------

class ClienteFalso:
    """O mínimo do cliente S3 que a ferramenta usa: head_object e upload_file."""

    class NaoExiste(Exception):
        response = {'Error': {'Code': '404'}}

    def __init__(self, existentes=None):
        self.objetos = dict(existentes or {})  # chave -> (bytes, sha256)
        self.envios = []
        self.apagados = []

    def head_object(self, Bucket, Key):  # noqa: N803 (o nome é o do boto3)
        assert Bucket == 'manhadefe-video', Bucket
        if Key not in self.objetos:
            raise self.NaoExiste()
        tamanho, sha = self.objetos[Key]
        return {'ContentLength': tamanho, 'Metadata': {} if sha is None else {'sha256': sha}}

    # A ferramenta nunca apaga no R2 (R8-B): se apagasse, o teste veria aqui.
    def delete_object(self, Bucket, Key):  # noqa: N803
        self.apagados.append(Key)
        self.objetos.pop(Key, None)

    def delete_objects(self, Bucket, Delete):  # noqa: N803
        for objeto in Delete.get('Objects', []):
            self.delete_object(Bucket, objeto['Key'])

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):  # noqa: N803
        assert Bucket == 'manhadefe-video', Bucket
        self.envios.append((Key, ExtraArgs))
        self.objetos[Key] = (Path(Filename).stat().st_size, ExtraArgs['Metadata']['sha256'])


class ClienteQueFalha(ClienteFalso):
    """Lança `erro` na primeira chamada de `metodo` feita depois de
    `depois_de` envios bem-sucedidos (0: logo a primeira)."""

    def __init__(self, metodo, erro, depois_de=0):
        super().__init__()
        self.metodo, self.erro, self.depois_de = metodo, erro, depois_de

    def _talvez_falhe(self, metodo):
        if metodo == self.metodo and len(self.envios) >= self.depois_de:
            raise self.erro

    def head_object(self, Bucket, Key):  # noqa: N803
        self._talvez_falhe('head_object')
        return super().head_object(Bucket, Key)

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):  # noqa: N803
        self._talvez_falhe('upload_file')
        return super().upload_file(Filename, Bucket, Key, ExtraArgs)


def teste_planejar_videos_escolhe_a_chave_sem_nunca_sobrescrever():
    """R8-B, a função pura: (1) a chave do JSON publicado, se o objeto lá é
    este; (2) a fixa — ausente: novo; igual: já estava; (3) a fixa com outro
    conteúdo: trocado — sem a opção, recusa (chave, capítulo e data); com
    ela, a chave versionada ...-<sha8>.mp4 (lá com este conteúdo: reusa; com
    outro: problema)."""
    with tempfile.TemporaryDirectory() as tmp:
        entrega, problemas = pt.conferir_entrega(entrega_valida(tmp))
        assert problemas == []
        c1, e1, c2, e2 = pt.videos_da_entrega(entrega)
        r2 = {'video/t1/01-catolico.mp4': (c1.bytes, 'a' * 64),        # outro conteúdo
              'video/t1/01-evangelico.mp4': (e1.bytes, e1.sha256),     # este
              # 02-catolico: ausente
              'video/t1/02-evangelico.mp4': (e2.bytes, None)}          # sem o sha256: outro

        def planejar(publicados=None, substituir=False):
            videos = pt.videos_da_entrega(entrega)
            problemas, recusas = pt.planejar_videos(entrega, videos, publicados or {}, r2.get,
                                                    substituir, prefixo='teste/midia/')
            return videos, problemas, recusas

        videos, problemas, recusas = planejar()
        assert problemas == [], problemas
        assert recusas == ['teste/midia/video/t1/01-catolico.mp4 (cap. 1, t1c1, 2026-11-10)',
                           'teste/midia/video/t1/02-evangelico.mp4 (cap. 2, t1c2, 2026-11-11)'], recusas
        videos, problemas, recusas = planejar(substituir=True)
        assert problemas == recusas == []
        assert [(v.chave, v.estado, v.sobe) for v in videos] == [
            (f'video/t1/01-catolico-{c1.sha256[:8]}.mp4', pt.TROCADO, True),
            ('video/t1/01-evangelico.mp4', pt.JA_ESTAVA, False),
            ('video/t1/02-catolico.mp4', pt.NOVO, True),
            (f'video/t1/02-evangelico-{e2.sha256[:8]}.mp4', pt.TROCADO, True)]
        assert videos[0].velha == 'video/t1/01-catolico.mp4'
        assert re.fullmatch(r'video/t1/01-catolico-[0-9a-f]{8}\.mp4', videos[0].chave)
        # A versionada já lá: com este conteúdo, reusa (não sobe); com outro, problema.
        r2[f'video/t1/01-catolico-{c1.sha256[:8]}.mp4'] = (c1.bytes, c1.sha256)
        r2[f'video/t1/02-evangelico-{e2.sha256[:8]}.mp4'] = (e2.bytes, 'b' * 64)
        videos, problemas, recusas = planejar(substituir=True)
        assert (videos[0].estado, videos[0].sobe) == (pt.TROCADO, False)
        assert len(problemas) == 1 and f'02-evangelico-{e2.sha256[:8]}.mp4' in problemas[0], problemas
        # A chave que o JSON publicado dá, com este conteúdo: já estava — sem a opção.
        publicados = {(1, 'catolico'): {'arquivo': f'video/t1/01-catolico-{c1.sha256[:8]}.mp4',
                                        'bytes': c1.bytes, 'sha256': c1.sha256}}
        videos, problemas, recusas = planejar(publicados)
        assert (videos[0].chave, videos[0].estado, videos[0].sobe) == \
            (f'video/t1/01-catolico-{c1.sha256[:8]}.mp4', pt.JA_ESTAVA, False)
        assert recusas == ['teste/midia/video/t1/02-evangelico.mp4 (cap. 2, t1c2, 2026-11-11)']


def teste_republicar_video_trocado_sem_a_opcao_recusa_antes_de_subir_ou_escrever():
    """R8-B: o vídeo no ar com outro sha256 nunca é sobrescrito. Sem
    --substituir-videos, a publicação lista chave, capítulo e data e sai com
    1 — nada sobe, nada é escrito, nada roda."""
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp)
        midia = dubles.midia()
        pasta = entrega_valida(tmp)
        dubles.cliente.objetos['video/t1/02-catolico.mp4'] = (123, 'a' * 64)
        objetos, antes = dict(dubles.cliente.objetos), _arvore(midia)
        codigo, saida = dubles.publicar(pasta, midia, '--sem-voz')
        assert codigo == 1, saida
        assert 'video/t1/02-catolico.mp4 (cap. 2, t1c2, 2026-11-11)' in saida, saida
        assert '--substituir-videos' in saida
        assert dubles.cliente.envios == [] and dubles.cliente.objetos == objetos
        assert _arvore(midia) == antes and dubles.comandos == []


def teste_com_substituir_videos_sobe_na_chave_versionada_e_o_velho_fica_intocado():
    """R8-B: com a opção, o vídeo trocado sobe em video/<t>/<nn>-<tradicao>-
    <sha8>.mp4 e o JSON aponta para ela; o objeto velho fica intocado (o
    aparelho com o JSON velho baixa o velho; com o novo, o novo). O resumo
    separa novo, já estava e trocado. Publicar de novo, sem a opção, reusa
    a chave que o JSON publicado já dá. Nada é apagado no R2, nunca."""
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp)
        midia = dubles.midia()
        pasta = entrega_valida(tmp)
        velho = (123, 'a' * 64)
        dubles.cliente.objetos['teste/midia/video/t1/02-catolico.mp4'] = velho
        extra = ('--sem-voz', '--r2-prefixo', 'teste/midia/')
        codigo, saida = dubles.publicar(pasta, midia, *extra, '--substituir-videos')
        assert codigo == 0, saida
        sha = sha256_de(pasta / '02-catolico.mp4')
        nova = f'video/t1/02-catolico-{sha[:8]}.mp4'
        assert [k for k, _ in dubles.cliente.envios] == [
            'teste/midia/video/t1/01-catolico.mp4', 'teste/midia/video/t1/01-evangelico.mp4',
            'teste/midia/' + nova, 'teste/midia/video/t1/02-evangelico.mp4']
        assert dubles.cliente.objetos['teste/midia/video/t1/02-catolico.mp4'] == velho
        assert dubles.cliente.apagados == []
        t1 = json.loads((midia / 'novela' / 't1.json').read_text(encoding='utf-8'))
        assert t1['capitulos'][1]['video']['catolico'] == {
            'arquivo': nova, 'bytes': (pasta / '02-catolico.mp4').stat().st_size, 'sha256': sha}
        assert t1['capitulos'][0]['video']['catolico']['arquivo'] == 'video/t1/01-catolico.mp4'
        assert 'novo: 3, já estava: 0, trocado (chave nova): 1' in saida, saida
        assert f'teste/midia/{nova}' in saida and 'intocado' in saida
        # De novo, sem a opção: o JSON publicado já dá a chave nova, com este
        # conteúdo — já estava; nada sobe.
        enviados = len(dubles.cliente.envios)
        codigo, saida = dubles.publicar(pasta, midia, *extra)
        assert codigo == 0, saida
        assert len(dubles.cliente.envios) == enviados
        assert 'novo: 0, já estava: 4, trocado (chave nova): 0' in saida, saida
        t1 = json.loads((midia / 'novela' / 't1.json').read_text(encoding='utf-8'))
        assert t1['capitulos'][1]['video']['catolico']['arquivo'] == nova
        assert dubles.cliente.apagados == []
    # E o código nem tem como apagar no R2.
    fonte = Path(pt.__file__).read_text(encoding='utf-8')
    assert 'delete_object' not in fonte and 'delete_objects' not in fonte


def teste_url_publica_confere_cada_video_antes_de_escrever():
    """R8-D: depois de subir — e também para o que já estava —, um HEAD na
    URL PÚBLICA <base><chave> (a que o app vai pedir) confere o
    Content-Length = bytes. A base que não serve o objeto para antes de
    escrever os JSONs locais; o erro de rede sai limpo."""
    extra = ('--sem-voz', '--r2-prefixo', 'teste/midia/')
    base = 'https://pub-exemplo123.r2.dev/teste/midia/'
    esperadas = [f'{base}video/t1/{nn}-{t}.mp4' for nn in ('01', '02')
                 for t in ('catolico', 'evangelico')]
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp)
        midia = dubles.midia()
        pasta = entrega_valida(tmp)
        codigo, saida = dubles.publicar(pasta, midia, *extra)
        assert codigo == 0, saida
        assert dubles.urls == esperadas, dubles.urls
        # De novo: tudo já estava, e o HEAD público confere do mesmo jeito.
        dubles.urls.clear()
        codigo, saida = dubles.publicar(pasta, midia, *extra)
        assert codigo == 0 and 'já estava: 4' in saida, saida
        assert dubles.urls == esperadas, dubles.urls
    from urllib.error import URLError
    falhas = (({'teste/midia/video/t1/02-evangelico.mp4': 99}, '02-evangelico.mp4'),
              (URLError(f'sem rota para {ENDPOINT}'), 'URLError'))
    for publico, trecho in falhas:
        with tempfile.TemporaryDirectory() as tmp:
            dubles = Dubles(tmp)
            dubles.publico = publico
            midia = dubles.midia()
            pasta = entrega_valida(tmp)
            antes = _arvore(midia)
            codigo, saida = dubles.publicar(pasta, midia, *extra)
            assert codigo == 1, saida
            assert trecho in saida and 'URL pública' in saida, saida
            nada_da_conta_em(saida)
            assert _arvore(midia) == antes, 'nada escrito'
            assert dubles.comandos == []
    # Uma base que não é a do balde (o objeto não está onde o app vai
    # pedir): 404, nada escrito.
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp)
        midia = dubles.midia()
        codigo, saida = dubles.publicar(entrega_valida(tmp), midia, '--sem-voz',
                                        '--videos-base', 'https://outro.exemplo.invalid/outra-pasta/')
        assert codigo == 1 and 'HTTPError: HTTP Error 404' in saida, saida
        assert 'https://outro.exemplo.invalid/outra-pasta/video/t1/01-catolico.mp4' in saida
        assert not (midia / 'novela').exists()


def teste_consultar_url_publica_faz_head_e_le_o_content_length():
    """O HEAD de verdade, com o urlopen trocado por um dublê (nenhum socket):
    método HEAD na URL pedida, com tempo-limite; o Content-Length vira int;
    sem ele, None."""
    pedidos = []

    class Resposta:
        def __init__(self, headers):
            self.headers = headers

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def urlopen(pedido, timeout=None):
        pedidos.append((pedido.full_url, pedido.get_method(), timeout))
        return Resposta({'Content-Length': '250865'} if 'com' in pedido.full_url else {})

    real = pt.urllib.request.urlopen
    pt.urllib.request.urlopen = urlopen
    try:
        assert pt.consultar_url_publica('https://x.invalid/com.mp4') == 250865
        assert pt.consultar_url_publica('https://x.invalid/sem.mp4') is None
    finally:
        pt.urllib.request.urlopen = real
    assert pedidos == [('https://x.invalid/com.mp4', 'HEAD', 20),
                       ('https://x.invalid/sem.mp4', 'HEAD', 20)], pedidos


def teste_simular_nao_faz_head_na_url_publica():
    def nunca(url):
        raise AssertionError(f'a simulação fez HEAD em {url}')
    real = pt.consultar_url_publica
    pt.consultar_url_publica = nunca
    try:
        with tempfile.TemporaryDirectory() as tmp:
            codigo, saida = publicar(entrega_valida(tmp), Path(tmp) / 'midia')
            assert codigo == 0, saida
    finally:
        pt.consultar_url_publica = real


def teste_base_de_producao_recusa_teste_e_avisa_r2_dev():
    """R8-D: sem --r2-prefixo (produção), a base com "teste/" é recusada; a
    *.r2.dev só avisa — hoje ela ainda é a base real, até o DNS ir para a
    Cloudflare. Com prefixo (ensaio), nenhuma das duas."""
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        deve_recusar(pasta, Path(tmp) / 'm1', 'teste/', 'produção',
                     extra=('--videos-base', 'https://pub-x.r2.dev/teste/midia/'))
        codigo, saida = publicar(pasta, Path(tmp) / 'm2', videos_base='https://pub-x.r2.dev/')
        assert codigo == 0, saida
        assert 'aviso:' in saida and 'r2.dev' in saida, saida
        codigo, saida = publicar(pasta, Path(tmp) / 'm3', '--r2-prefixo', 'teste/midia/',
                                 videos_base='https://pub-x.r2.dev/teste/midia/')
        assert codigo == 0 and 'aviso:' not in saida, saida
        codigo, saida = publicar(pasta, Path(tmp) / 'm4', videos_base='https://video.manhadefe.com.br/')
        assert codigo == 0 and 'aviso:' not in saida, saida


def teste_simular_preve_o_trocado_pelo_json_publicado():
    """Na simulação o R2 não é consultado: o estado vem do novela/<t>.json
    publicado na pasta — o vídeo que mudou é trocado e recusa sem a opção,
    como a rodada real recusaria; com ela, a chave versionada."""
    with tempfile.TemporaryDirectory() as tmp:
        pasta = entrega_valida(tmp)
        midia = Path(tmp) / 'midia'
        assert publicar(pasta, midia)[0] == 0          # a versão "publicada"
        shutil.copyfile(midia_sintetica()['outro'], pasta / '01-catolico.mp4')
        deve_recusar(pasta, midia, 'video/t1/01-catolico.mp4 (cap. 1, t1c1, 2026-11-10)',
                     '--substituir-videos')
        codigo, saida = publicar(pasta, midia, '--substituir-videos')
        assert codigo == 0, saida
        sha = sha256_de(pasta / '01-catolico.mp4')
        t1 = json.loads((midia / 'novela' / 't1.json').read_text(encoding='utf-8'))
        assert t1['capitulos'][0]['video']['catolico']['arquivo'] == \
            f'video/t1/01-catolico-{sha[:8]}.mp4'
        assert 'novo: 0, já estava: 3, trocado (chave nova): 1' in saida, saida


def teste_cliente_do_r2_e_o_do_boto3_no_endpoint_da_conta_sem_rede():
    """O único pedaço do envio que roda o boto3 de verdade aqui: montar o
    cliente não toca a rede."""
    chaves = pt.ChavesR2(endpoint='https://00112233445566778899aabbccddeeff.r2.cloudflarestorage.com',
                         access_key_id='a' * 32, secret_access_key='b' * 64, url_publica=None)
    cliente = pt.criar_cliente_r2(chaves)
    assert cliente.meta.endpoint_url == chaves.endpoint
    assert cliente.meta.region_name == 'auto'
    assert cliente.meta.config.request_checksum_calculation == 'when_required'
    assert cliente.meta.config.response_checksum_validation == 'when_required'
    assert callable(cliente.head_object) and callable(cliente.upload_file)


class Dubles:
    """Troca, durante um teste, o cliente do R2, o dart e os comandos por
    dublês que registram o que a ferramenta pediu e fazem o que cada
    comando faria no disco."""

    def __init__(self, tmp, stt=0, lint=0, manifesto_com_novela=True):
        self.tmp = Path(tmp)
        self.cliente = ClienteFalso()
        # Quem monta o cliente (o teste troca para montar um que falha).
        self.criar_cliente = lambda chaves: self.cliente
        # O HEAD na URL pública: responde pelo balde falso (o caminho da URL
        # é a chave no R2); `publico` troca o Content-Length de uma chave ou
        # é um erro que todo HEAD lança.
        self.urls = []
        self.publico = {}
        self.comandos = []
        self.stt, self.lint = stt, lint
        # False: o gerar_manifesto de um app anterior à Task 7, que não
        # conhece a pasta novela/.
        self.manifesto_com_novela = manifesto_com_novela
        self.app = self.tmp / 'app'
        for arquivo in ('pubspec.yaml', 'tool/midia/texto_narrado.dart',
                        'tool/midia/gerar_manifesto.dart', 'tool/lint_conteudo.dart'):
            (self.app / arquivo).parent.mkdir(parents=True, exist_ok=True)
            (self.app / arquivo).write_text('', encoding='utf-8')
        self.chaves = self.tmp / 'R2.txt'
        self.chaves.write_text(R2_FALSO, encoding='utf-8')

    def midia(self):
        """Uma raiz de mídia como a cópia que o coordenador usa: com as
        ferramentas (a voz roda a cópia dela, que grava nela)."""
        midia = self.tmp / 'midia'
        for script in ('narrar.py', 'conferir_stt.py'):
            (midia / 'ferramentas' / script).parent.mkdir(parents=True, exist_ok=True)
            (midia / 'ferramentas' / script).write_text('', encoding='utf-8')
        return midia

    def rodar(self, cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        self.comandos.append((cmd, cwd))
        if 'tool/midia/texto_narrado.dart' in cmd:
            saida = next(c.split('=', 1)[1] for c in cmd if c.startswith('--saida='))
            novela = Path(next(c.split('=', 1)[1] for c in cmd if c.startswith('--temporadas=')))
            linhas = []
            for t in sorted(novela.glob('t*.json')):
                if t.name == 'temporadas.json':
                    continue
                for c in json.loads(t.read_text(encoding='utf-8'))['capitulos']:
                    for tradicao in ('catolico', 'evangelico'):
                        linhas.append(json.dumps({'id': c['id'], 'tradicao': tradicao,
                                                  'caminho': f'narracao/{tradicao}/{c["id"]}.m4a',
                                                  'texto': c['reflexao']}, ensure_ascii=False))
            Path(saida).parent.mkdir(parents=True, exist_ok=True)
            Path(saida).write_text(chr(10).join(linhas) + chr(10), encoding='utf-8')
            return 0
        if cmd[1].endswith('narrar.py'):
            midia = Path(cmd[1]).parents[1]
            for id_ in cmd[cmd.index('--ids') + 1].split(','):
                for tradicao in ('catolico', 'evangelico'):
                    (midia / 'narracao' / tradicao).mkdir(parents=True, exist_ok=True)
                    (midia / 'narracao' / tradicao / f'{id_}.m4a').write_bytes(b'voz')
            return 0
        if cmd[1].endswith('conferir_stt.py'):
            return self.stt
        if 'tool/midia/gerar_manifesto.dart' in cmd:
            raiz = Path(cmd[-1])
            pastas = {'narracao': '.m4a', 'imagens': '.webp', 'novela': ('.json', '.srt')}
            if not self.manifesto_com_novela:
                pastas.pop('novela')
            arquivos = {p.relative_to(raiz).as_posix(): {'bytes': p.stat().st_size,
                                                          'sha256': sha256_de(p)}
                        for pasta, extensao in pastas.items() for p in (raiz / pasta).rglob('*')
                        if p.is_file() and p.name.endswith(extensao)}
            (raiz / 'manifesto.json').write_text(json.dumps({'versao': 1, 'arquivos': arquivos}),
                                                 encoding='utf-8')
            return 0
        if 'tool/lint_conteudo.dart' in cmd:
            return self.lint
        raise AssertionError(f'comando inesperado: {cmd}')

    def head_publico(self, url):
        self.urls.append(url)
        if isinstance(self.publico, Exception):
            raise self.publico
        chave = urlparse(url).path.lstrip('/')
        if chave not in self.cliente.objetos:
            raise urllib.error.HTTPError(url, 404, 'Not Found', {}, None)
        return self.publico.get(chave, self.cliente.objetos[chave][0])

    @contextlib.contextmanager
    def instalados(self):
        antes = pt.rodar, pt.criar_cliente_r2, pt.localizar_dart, pt.consultar_url_publica
        pt.rodar = self.rodar
        pt.criar_cliente_r2 = lambda chaves: self.criar_cliente(chaves)
        pt.localizar_dart = lambda: 'dart'
        pt.consultar_url_publica = self.head_publico
        try:
            yield self
        finally:
            pt.rodar, pt.criar_cliente_r2, pt.localizar_dart, pt.consultar_url_publica = antes

    def publicar(self, pasta, midia, *extra):
        """main() no caminho real com os dublês; devolve (código, tudo o que
        foi ao terminal — stdout e stderr)."""
        saida = io.StringIO()
        with self.instalados(), contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
            codigo = pt.main([str(pasta), '--midia', str(midia), '--app', str(self.app),
                              '--r2', str(self.chaves), *extra])
        return codigo, saida.getvalue()

    def ferramentas(self):
        """O nome de cada comando rodado, na ordem."""
        nomes = []
        for cmd, _ in self.comandos:
            nome = next((Path(c).name for c in cmd if c.endswith(('.dart', '.py'))), cmd[0])
            nomes.append(nome)
        return nomes


def teste_publicacao_com_dubles_sobe_ao_r2_gera_voz_confere_e_roda_manifesto_e_lint():
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp)
        midia = dubles.midia()
        pasta = entrega_valida(tmp)
        codigo, saida = dubles.publicar(pasta, midia, '--r2-prefixo', 'teste/midia/',
                                        '--motor', 'microsoft')
        assert codigo == 0, saida
        assert [k for k, _ in dubles.cliente.envios] == [
            'teste/midia/video/t1/01-catolico.mp4', 'teste/midia/video/t1/01-evangelico.mp4',
            'teste/midia/video/t1/02-catolico.mp4', 'teste/midia/video/t1/02-evangelico.mp4']
        assert dubles.ferramentas() == ['texto_narrado.dart', 'narrar.py', 'conferir_stt.py',
                                        'gerar_manifesto.dart', 'lint_conteudo.dart']
        (texto, cwd_texto), (narrar, _), (stt, _), (manifesto, _), (lint, _) = dubles.comandos
        assert f'--saida={midia / "ferramentas" / "narracao" / "narracoes.jsonl"}' in texto
        assert f'--temporadas={midia / "novela"}' in texto and str(dubles.app) == texto[-1]
        assert Path(cwd_texto) == dubles.app, 'o dart roda na raiz do app'
        # A voz roda a cópia das ferramentas DENTRO da raiz de mídia (é ela
        # que grava em <midia>/narracao/).
        assert Path(narrar[1]) == midia / 'ferramentas' / 'narrar.py'
        assert narrar[2:] == ['--motor', 'microsoft', '--ids', 't1c1,t1c2', '--refazer']
        assert Path(stt[1]) == midia / 'ferramentas' / 'conferir_stt.py'
        assert stt[2:] == ['--stt', 'whisper', '--ids', 't1c1,t1c2']
        assert manifesto[-1] == str(midia)
        assert lint[-1] == f'--manifesto={midia / "manifesto.json"}'
        assert (midia / 'novela' / 't1.json').exists() and (midia / 'manifesto.json').exists()
        # Sem --videos-base e sem índice, a base é a Public Development URL
        # do arquivo de chaves, com o prefixo (só no caminho real: a
        # simulação nunca lê o arquivo).
        indice = json.loads((midia / 'novela' / 'temporadas.json').read_text(encoding='utf-8'))
        assert indice['videos'] == 'https://pub-exemplo123.r2.dev/teste/midia/'
        assert 'https://pub-exemplo123.r2.dev/teste/midia/' in saida
        assert 'push SÓ com OK do Gregory' in saida
        assert '0123456789abcdef' not in saida and 'fedcba98' not in saida
        # Rodar de novo: os vídeos já estão lá com o mesmo sha256 — nada sobe.
        dubles.comandos.clear()
        enviados = len(dubles.cliente.envios)
        codigo, saida = dubles.publicar(pasta, midia, '--r2-prefixo', 'teste/midia/',
                                        '--motor', 'microsoft')
        assert codigo == 0, saida
        assert len(dubles.cliente.envios) == enviados
        assert 'já estava' in saida


def teste_voz_reprovada_para_antes_do_manifesto():
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp, stt=1)
        midia = dubles.midia()
        codigo, saida = dubles.publicar(entrega_valida(tmp), midia, '--motor', 'microsoft')
        assert codigo == 1, saida
        assert dubles.ferramentas() == ['texto_narrado.dart', 'narrar.py', 'conferir_stt.py']
        assert not (midia / 'manifesto.json').exists()
        assert 'reprov' in saida
        # Fora de um repositório git, não há comando a dar: a lista, e à mão.
        assert 'NÃO rode o gerar_manifesto nem faça commit' in saida
        assert 'não é um repositório git' in saida and 'novela/t1.json' in saida


def _git(pasta, *args):
    r = subprocess.run(['git', '-c', 'user.name=teste', '-c', 'user.email=teste@exemplo.invalid',
                        '-c', 'core.autocrlf=false', *args],
                       cwd=str(pasta), capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


def teste_stt_reprovado_lista_o_que_foi_escrito_e_os_comandos_exatos_para_desfazer():
    """R8-H: a voz reprovada para antes do manifesto, mas os JSONs, as capas,
    as legendas e a voz já estão no disco. A mensagem lista cada caminho,
    diz em destaque "NÃO rode o gerar_manifesto nem faça commit" e dá os
    comandos exatos — git checkout -- <versionados> e git clean -f --
    <novos> —, que, rodados como impressos, devolvem a raiz de mídia ao
    commit. Sem quarentena: nada é movido."""
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp, stt=1)
        midia = dubles.midia()
        # A raiz de mídia é um repositório com uma versão anterior publicada:
        # o índice (com outra temporada) e a capa do capítulo 1.
        (midia / 'novela').mkdir()
        (midia / 'novela' / 'temporadas.json').write_text(json.dumps({
            'versao': 1, 'videos': 'https://pub-exemplo123.r2.dev/',
            'temporadas': [_resumo('t2', '2026-12-01', '2026-12-07', 7)]}), encoding='utf-8')
        (midia / 'imagens').mkdir()
        (midia / 'imagens' / 't1c1.webp').write_bytes(b'capa velha')
        # Como o .gitignore do repositório de mídia: o jsonl e os logs da voz.
        (midia / '.gitignore').write_text('ferramentas/narracao/narracoes.jsonl' + chr(10)
                                          + 'ferramentas/narracao/*.log.jsonl' + chr(10),
                                          encoding='utf-8')
        _git(midia, 'init', '-q')
        _git(midia, 'add', '--', '.gitignore', 'ferramentas/narrar.py', 'ferramentas/conferir_stt.py',
             'novela/temporadas.json', 'imagens/t1c1.webp')
        _git(midia, 'commit', '-q', '-m', 'a versão anterior')
        codigo, saida = dubles.publicar(entrega_valida(tmp), midia)
        assert codigo == 1, saida
        assert 'reprov' in saida and 'NÃO rode o gerar_manifesto nem faça commit' in saida, saida
        versionados = {'imagens/t1c1.webp', 'novela/temporadas.json'}
        novos = {'novela/t1.json', 'novela/t1c1.srt', 'imagens/t1c2.webp',
                 'narracao/catolico/t1c1.m4a', 'narracao/evangelico/t1c1.m4a',
                 'narracao/catolico/t1c2.m4a', 'narracao/evangelico/t1c2.m4a'}
        for caminho in versionados | novos:
            assert caminho in saida, caminho
        linhas = [linha.strip() for linha in saida.splitlines()]
        checkout = next(linha for linha in linhas if linha.startswith('git checkout -- '))
        clean = next(linha for linha in linhas if linha.startswith('git clean -f -- '))
        assert set(checkout.split()[3:]) == versionados, checkout
        assert set(clean.split()[4:]) == novos, clean
        assert not (midia / 'manifesto.json').exists()
        assert _git(midia, 'status', '--porcelain') != ''
        # Os comandos, rodados como impressos, devolvem a raiz de mídia ao commit.
        for comando in (checkout, clean):
            r = subprocess.run(comando.split(), cwd=str(midia), capture_output=True, text=True)
            assert r.returncode == 0, (comando, r.stderr)
        assert _git(midia, 'status', '--porcelain') == ''
        assert (midia / 'imagens' / 't1c1.webp').read_bytes() == b'capa velha'


def teste_sem_voz_pula_a_voz_e_lint_com_erro_sai_com_1():
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp, lint=1)
        midia = dubles.midia()
        codigo, saida = dubles.publicar(entrega_valida(tmp), midia, '--sem-voz')
        assert codigo == 1, saida
        assert dubles.ferramentas() == ['gerar_manifesto.dart', 'lint_conteudo.dart']
        assert 'lint' in saida
        # Parou depois de escrever: o mesmo aviso, com o manifesto refeito na lista.
        assert 'NÃO rode o gerar_manifesto nem faça commit' in saida
        assert 'manifesto.json' in saida and 'novela/t1.json' in saida


def teste_manifesto_que_nao_lista_a_temporada_para_antes_do_lint():
    """O gerar_manifesto de um app anterior à Task 7 não conhece novela/: o
    app não baixaria a temporada, e o lint antigo nem olharia. Para antes do
    lint e diz por quê."""
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp, manifesto_com_novela=False)
        midia = dubles.midia()
        codigo, saida = dubles.publicar(entrega_valida(tmp), midia, '--sem-voz')
        assert codigo == 1, saida
        assert dubles.ferramentas() == ['gerar_manifesto.dart']
        assert 'novela/temporadas.json' in saida and 'novela/t1c1.srt' in saida
        assert 'Task 7' in saida


def teste_publicacao_real_confere_as_ferramentas_antes_de_escrever():
    """Sem as ferramentas da voz na raiz de mídia, sem o arquivo de chaves e
    com um app sem o lint: tudo listado, nada enviado nem escrito."""
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp)
        (dubles.app / 'tool' / 'lint_conteudo.dart').unlink()
        dubles.chaves.unlink()
        midia = Path(tmp) / 'midia-sem-ferramentas'
        midia.mkdir()
        codigo, saida = dubles.publicar(entrega_valida(tmp), midia)
        assert codigo == 1, saida
        assert 'narrar.py' in saida and 'R2.txt' in saida and 'lint_conteudo.dart' in saida
        assert dubles.cliente.envios == [] and dubles.comandos == []
        assert not any(midia.iterdir())


def _arvore(pasta):
    return sorted(p.relative_to(pasta).as_posix() for p in Path(pasta).rglob('*'))


def teste_erro_do_r2_nunca_vai_cru_a_tela_e_nada_e_escrito():
    """R8-A: a falha de rede ou do R2 traz o endpoint da conta na mensagem
    (EndpointConnectionError, ClientError, o ValueError do endpoint
    inválido). Em todo caminho — montar o cliente, consultar (HEAD), enviar,
    conferir depois do envio — a saída mostra o tipo e a mensagem limpa,
    nada da conta, e nada é escrito na raiz de mídia."""
    from botocore.exceptions import ClientError, EndpointConnectionError
    conexao = EndpointConnectionError(
        endpoint_url=f'{ENDPOINT}/manhadefe-video/teste/midia/video/t1/01-catolico.mp4')
    negado = ClientError({'Error': {'Code': 'AccessDenied',
                                    'Message': f'a conta {CONTA} em {CONTA}.r2.cloudflarestorage.com '
                                               f'recusou a chave {CHAVE_DE_ACESSO}'}}, 'PutObject')
    casos = (('cliente', 0, ValueError(f'Invalid endpoint: {ENDPOINT}'), 'ValueError'),
             ('head_object', 0, conexao, 'EndpointConnectionError'),
             ('upload_file', 0, negado, 'ClientError (AccessDenied)'),
             ('head_object', 1, conexao, 'EndpointConnectionError'))   # depois de um envio
    for metodo, depois_de, erro, nome in casos:
        assert CONTA in str(erro), 'o dublê traz a conta na mensagem'
        with tempfile.TemporaryDirectory() as tmp:
            dubles = Dubles(tmp)
            midia = dubles.midia()
            if metodo == 'cliente':
                def falha(chaves, erro=erro):
                    raise erro
                dubles.criar_cliente = falha
            else:
                dubles.cliente = ClienteQueFalha(metodo, erro, depois_de)
            pasta = entrega_valida(tmp)
            antes = _arvore(midia)
            codigo, saida = dubles.publicar(pasta, midia, '--r2-prefixo', 'teste/midia/')
            assert codigo == 1, (metodo, saida)
            assert nome in saida, (nome, saida)
            nada_da_conta_em(saida)
            assert _arvore(midia) == antes, (metodo, 'escreveu na raiz de mídia')
            assert dubles.comandos == [], 'nem voz nem manifesto'


# ---------------------------------------------------------------------------
# A temporada de teste t0 (o passeio no emulador da Task 9)
# ---------------------------------------------------------------------------

def teste_temporada_de_teste_t0_passa_na_conferencia_do_publicar():
    import temporada_de_teste as tt
    with tempfile.TemporaryDirectory() as tmp:
        saida = Path(tmp) / 't0'
        assert tt.main([str(saida), '--inicio', '2026-10-21']) == 0
        assert sorted(p.name for p in saida.iterdir()) == [
            '01-catolico.mp4', '01-evangelico.mp4', '01.srt', '01.webp',
            '02-catolico.mp4', '02-evangelico.mp4', '02.srt', '02.webp', 'temporada.json']
        temporada = json.loads((saida / 'temporada.json').read_text(encoding='utf-8'))
        assert temporada['id'] == 't0'
        assert [c['data'] for c in temporada['capitulos']] == ['2026-10-21', '2026-10-22']
        # Os textos são os de dois cartões reais do app.
        for c, cartao in zip(temporada['capitulos'], ('comum-001', 'comum-002')):
            real = json.loads((pt.APP_PADRAO / 'assets' / 'content' / 'cartoes' / f'{cartao}.json')
                              .read_text(encoding='utf-8'))
            for campo in ('referenciaBiblica', 'versiculo', 'reflexao', 'oracao'):
                assert c[campo] == real[campo], (cartao, campo)
            assert c['duracaoS'] == 10
        # As duas versões de cada capítulo são vídeos diferentes (o passeio
        # vê qual tocou).
        assert sha256_de(saida / '01-catolico.mp4') != sha256_de(saida / '01-evangelico.mp4')
        # Passa na conferência e na publicação simulada.
        entrega, problemas = pt.conferir_entrega(saida)
        assert entrega is not None and problemas == [], problemas
        codigo, texto = publicar(saida, Path(tmp) / 'midia')
        assert codigo == 0, texto
        indice = json.loads((Path(tmp) / 'midia' / 'novela' / 'temporadas.json')
                            .read_text(encoding='utf-8'))
        assert [(t['id'], t['inicio'], t['fim']) for t in indice['temporadas']] == \
               [('t0', '2026-10-21', '2026-10-22')]
        # Pasta de saída com arquivos: recusa, sem misturar entregas.
        try:
            tt.main([str(saida), '--inicio', '2026-10-21'])
        except SystemExit as e:
            assert e.code != 0 and 'vazia' in str(e.code), e.code
        else:
            raise AssertionError('deveria ter recusado a pasta com arquivos')


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
