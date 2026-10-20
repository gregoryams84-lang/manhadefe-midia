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
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

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


def video(destino, largura, altura, segundos, frequencia):
    _ffmpeg('-f', 'lavfi', '-i', f'testsrc=size={largura}x{altura}:rate=25:duration={segundos}',
            '-f', 'lavfi', '-i', f'sine=frequency={frequencia}:sample_rate=44100:duration={segundos}',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
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


def teste_base_videos_vem_da_url_publica_do_arquivo_de_chaves_com_o_prefixo():
    with tempfile.TemporaryDirectory() as tmp:
        chaves = Path(tmp) / 'R2.txt'
        chaves.write_text(R2_FALSO.replace(chr(10), chr(13) + chr(10)), encoding='utf-8')
        pasta = entrega_valida(tmp)
        midia = Path(tmp) / 'midia'
        codigo, saida = publicar(pasta, midia, '--r2', str(chaves), '--r2-prefixo', 'teste/midia',
                                 videos_base=None)
        assert codigo == 0, saida
        indice = json.loads((midia / 'novela' / 'temporadas.json').read_text(encoding='utf-8'))
        assert indice['videos'] == 'https://pub-exemplo123.r2.dev/teste/midia/'
        # A chave no R2 leva o prefixo; o `arquivo` do JSON, não (o prefixo
        # está na base).
        assert 'teste/midia/video/t1/01-catolico.mp4' in saida
        temporada = json.loads((midia / 'novela' / 't1.json').read_text(encoding='utf-8'))
        assert temporada['capitulos'][0]['video']['catolico']['arquivo'] == 'video/t1/01-catolico.mp4'
        # As chaves secretas nunca aparecem.
        for segredo in ('0123456789abcdef0123456789abcdef', 'fedcba9876543210',
                        'tokenfalso', '00112233445566778899aabbccddeeff'):
            assert segredo not in saida


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

    def head_object(self, Bucket, Key):  # noqa: N803 (o nome é o do boto3)
        assert Bucket == 'manhadefe-video', Bucket
        if Key not in self.objetos:
            raise self.NaoExiste()
        tamanho, sha = self.objetos[Key]
        return {'ContentLength': tamanho, 'Metadata': {'sha256': sha}}

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):  # noqa: N803
        assert Bucket == 'manhadefe-video', Bucket
        self.envios.append((Key, ExtraArgs))
        self.objetos[Key] = (Path(Filename).stat().st_size, ExtraArgs['Metadata']['sha256'])


def teste_subir_videos_pula_o_que_ja_esta_la_com_o_mesmo_tamanho_e_sha256():
    with tempfile.TemporaryDirectory() as tmp:
        a, b, c = (Path(tmp) / f'{n}.mp4' for n in 'abc')
        for arquivo, conteudo in ((a, b'aaaa'), (b, b'bbbbbb'), (c, b'cc')):
            arquivo.write_bytes(conteudo)
        envios = [('x/a.mp4', a, 4, sha256_de(a)), ('x/b.mp4', b, 6, sha256_de(b)),
                  ('x/c.mp4', c, 2, sha256_de(c))]
        cliente = ClienteFalso({'x/b.mp4': (6, sha256_de(b)),        # igual: pula
                                'x/c.mp4': (2, 'outro-sha')})        # mesmo tamanho, outro sha
        resultado = pt.subir_videos(cliente, envios)
        assert resultado == [('x/a.mp4', 4, 'subiu'), ('x/b.mp4', 6, 'já estava'),
                             ('x/c.mp4', 2, 'subiu')], resultado
        assert [k for k, _ in cliente.envios] == ['x/a.mp4', 'x/c.mp4']
        for chave, extra in cliente.envios:
            assert extra == {'ContentType': 'video/mp4',
                             'Metadata': {'sha256': dict((e[0], e[3]) for e in envios)[chave]}}


class Dubles:
    """Troca, durante um teste, o cliente do R2, o dart e os comandos por
    dublês que registram o que a ferramenta pediu e fazem o que cada
    comando faria no disco."""

    def __init__(self, tmp, stt=0, lint=0, manifesto_com_novela=True):
        self.tmp = Path(tmp)
        self.cliente = ClienteFalso()
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

    @contextlib.contextmanager
    def instalados(self):
        antes = pt.rodar, pt.criar_cliente_r2, pt.localizar_dart
        pt.rodar = self.rodar
        pt.criar_cliente_r2 = lambda chaves: self.cliente
        pt.localizar_dart = lambda: 'dart'
        try:
            yield self
        finally:
            pt.rodar, pt.criar_cliente_r2, pt.localizar_dart = antes

    def publicar(self, pasta, midia, *extra):
        saida = io.StringIO()
        with self.instalados(), contextlib.redirect_stdout(saida):
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


def teste_sem_voz_pula_a_voz_e_lint_com_erro_sai_com_1():
    with tempfile.TemporaryDirectory() as tmp:
        dubles = Dubles(tmp, lint=1)
        midia = dubles.midia()
        codigo, saida = dubles.publicar(entrega_valida(tmp), midia, '--sem-voz')
        assert codigo == 1, saida
        assert dubles.ferramentas() == ['gerar_manifesto.dart', 'lint_conteudo.dart']
        assert 'lint' in saida


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
