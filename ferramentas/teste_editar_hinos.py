#!/usr/bin/env python3
"""Testes de editar_hinos.py. Tudo roda em diretórios temporários com
ffmpeg/ffprobe de verdade: a pasta de entrada, o --midia e o --log são
temporários; nada é escrito em hinos/ deste repo nem na pasta do OneDrive.

  python -m pytest ferramentas/teste_editar_hinos.py
  python ferramentas/teste_editar_hinos.py          # sem pytest

Os testes leem o catálogo real do app (manha-de-fe-app, pasta-irmã deste
repo ou MANHA_DE_FE_APP), só leitura, e os 15 hinos já no ar em hinos/
deste repo (só leitura: copiados para um temporário quando o teste precisa
provar que não são tocados). O teste de voz só roda se o whisper-cli e o
modelo existirem; senão é pulado.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import traceback
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import editar_hinos as eh  # noqa: E402

APP_REAL = eh.APP_PADRAO
HINOS_NO_AR = eh.RAIZ / eh.PASTA_DOS_HINOS

# Os 15 nomes de 24/09/2026 como Gregory os escreveu (o iPhone grava alguns
# em NFD; aqui em NFC — o casamento tem de dar igual) e o slug certo de
# cada um, o que está em hinos/ desde o commit 8dbf52b.
OS_15_DE_24_09 = {
    'Ah se eu tivesse mil vozes.m4a': 'ah-se-eu-tivesse-mil-vozes',
    'Castelo forte.m4a': 'castelo-forte',
    'Coroai.m4a': 'coroai',
    'Crer e observar.m4a': 'crer-e-observar',
    'Cristo bom mestre.m4a': 'cristo-bom-mestre',
    'Demos Glória a Deus.m4a': 'demos-gloria-a-deus',
    'Deus cuidará de Ti.m4a': 'deus-cuidara-de-ti',
    'Ditoso dia.m4a': 'ditoso-dia',
    'Fonte de toda benção.m4a': 'fonte-de-toda-bencao',
    'Justo és senhor.m4a': 'justo-es-senhor-doxologia',
    'Mais perto ,Meu Deus, de Ti.m4a': 'mais-perto-meu-deus-de-ti-mais-perto-quero-estar',
    'Pão da Vida.m4a': 'pao-da-vida',
    'Que segurança.m4a': 'que-seguranca-blessed-assurance',
    'Santo santo Deus onipotente.m4a': 'santo-santo-santo-deus-onipotente',
    'Tudo entregarei.m4a': 'tudo-entregarei',
}


def app_real():
    faltando = [p for p in (APP_REAL / 'pubspec.yaml',
                            APP_REAL / 'assets' / 'content' / 'hinos')
                if not p.exists()]
    if faltando:
        raise RuntimeError(
            f'o repo do app não está em {APP_REAL} (falta {faltando[0]}). Os testes leem '
            'assets/content/hinos de manha-de-fe-app: clone-o como pasta-irmã de '
            'manhadefe-midia ou aponte a raiz dele em MANHA_DE_FE_APP.')
    return APP_REAL


class Pulado(Exception):
    """Teste pulado de propósito (o runner sem pytest o mostra como tal)."""


def pular(motivo):
    if 'pytest' in sys.modules:
        import pytest
        pytest.skip(motivo)
    raise Pulado(motivo)


def sha(caminho):
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def tom(destino, amplitude, pico, segundos=5.0):
    """Um seno de 440 Hz de `amplitude` (linear) com um pulso de 3 ms em
    `pico` (linear) aos 2,5 s, em PCM float (aceita amostra acima de 1.0 —
    é o que faz o pico verdadeiro passar de 0 dBTP). Sem fade nenhum: entra
    e corta seco."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    expressao = (f'if(between(t\\,2.5\\,2.503)\\,{pico:.4f}\\,'
                 f'{amplitude:.4f}*sin(2*PI*440*t))')
    eh._ffmpeg(['-y', '-f', 'lavfi', '-i', f'aevalsrc={expressao}:s=48000', '-t', f'{segundos}',
                '-c:a', 'pcm_f32le', str(destino)], 'tom de teste')
    return destino


def tom_alto(destino):
    """~ -12 LUFS com pico em ~ +1 dBTP (estoura)."""
    return tom(destino, amplitude=0.385, pico=1.0)


def tom_baixo(destino):
    """~ -27 LUFS com pico em ~ -1 dBTP: o loudnorm precisa subir 7 dB e o
    pulso passaria do teto — é o limitador quem segura."""
    return tom(destino, amplitude=0.069, pico=0.7)


def pastas(tmp):
    """(entrada, midia, log) temporários; a entrada já existe."""
    entrada = Path(tmp) / 'brutos'
    entrada.mkdir()
    return entrada, Path(tmp) / 'midia', Path(tmp) / 'log.jsonl'


def args_comuns(entrada, midia, log):
    return ['--entrada', str(entrada), '--app', str(app_real()), '--midia', str(midia),
            '--log', str(log), '--paralelo', '2']


def deve_parar(argv, trecho_da_mensagem):
    try:
        eh.main(argv)
    except SystemExit as e:
        assert trecho_da_mensagem in str(e), str(e)
    else:
        raise AssertionError(f'deveria ter parado por {trecho_da_mensagem!r}')


def registros(log):
    return [json.loads(l) for l in Path(log).read_text(encoding='utf-8').splitlines()]


# ---------------------------------------------------------------------------
# Casamento
# ---------------------------------------------------------------------------

def teste_normalizar_tira_acento_pontuacao_e_caixa_nos_dois_lados():
    assert eh.normalizar('Fonte de toda benção') == 'fonte de toda bencao'
    assert eh.normalizar('Mais perto ,Meu Deus, de Ti') == 'mais perto meu deus de ti'
    assert eh.normalizar('Santo! Santo! Santo! Deus Onipotente') == 'santo santo santo deus onipotente'
    assert eh.normalizar('que-seguranca-blessed-assurance') == 'que seguranca blessed assurance'
    # NFD (como o iPhone grava) e NFC dão o mesmo resultado.
    nfd = unicodedata.normalize('NFD', 'Que segurança')
    assert nfd != 'Que segurança' and eh.normalizar(nfd) == eh.normalizar('Que segurança') == 'que seguranca'
    assert eh.normalizar('') == '' and eh.normalizar('!!!') == ''


def teste_os_15_de_24_09_casam_com_os_15_slugs_certos():
    slugs = eh.catalogo(app_real())
    assert len(slugs) == 113, len(slugs)
    no_ar = sorted(p.stem for p in HINOS_NO_AR.glob('*.m4a'))
    assert sorted(OS_15_DE_24_09.values()) == no_ar, 'a lista do teste não bate com hinos/'
    for nome, esperado in OS_15_DE_24_09.items():
        for forma in ('NFC', 'NFD'):
            candidatos, regra = eh.casar(unicodedata.normalize(forma, Path(nome).stem), slugs)
            assert candidatos == [esperado], (nome, forma, candidatos, regra)
    # 14 por igualdade; "Santo santo Deus onipotente" pulou um "santo" e só
    # casa pela camada das palavras — é a razão de a camada existir.
    regras = {nome: eh.casar(Path(nome).stem, slugs)[1] for nome in OS_15_DE_24_09}
    assert regras.pop('Santo santo Deus onipotente.m4a') == 'palavras'
    assert set(regras.values()) == {'igual'}, regras


def teste_camadas_igual_prefixo_palavras_e_ambiguidade():
    slugs = eh.catalogo(app_real())
    # Igualdade vence: "Feliz" é o hino "feliz", não "sou-feliz"/"terra-feliz".
    assert eh.casar('Feliz', slugs) == (['feliz'], 'igual')
    # Prefixo em qualquer direção (título) e slug começando pelo nome.
    assert eh.casar('Jesus', slugs) == (['jesus-me-transformou'], 'prefixo')
    assert eh.casar('Que segurança blessed', slugs) == (['que-seguranca-blessed-assurance'], 'prefixo')
    assert eh.casar('Feliz natal', slugs) == (['feliz'], 'prefixo')
    # Dois na mesma camada = ambíguo (a lista vem inteira, ordenada).
    assert eh.casar('Luz', slugs) == (['luz-benigna', 'luz-divina'], 'prefixo')
    assert eh.casar('Salvação', slugs) == (['salvacao-pela-fe', 'salvacao-perfeita'], 'prefixo')
    # Palavras em ordem, com outras no meio.
    assert eh.casar('Deus amor bondade', slugs) == (['ao-deus-de-amor-e-de-imensa-bondade'], 'palavras')
    # Fora de ordem não casa; nome inventado não casa.
    assert eh.casar('bondade amor deus', slugs) == ([], 'sem par')
    assert eh.casar('Xyz qwerty', slugs) == ([], 'sem par')
    assert eh.casar('', slugs) == ([], 'sem par')


def teste_planejar_status_novo_ja_no_ar_refazer_ambiguo_sem_par_repetido():
    slugs = eh.catalogo(app_real())
    with tempfile.TemporaryDirectory() as tmp:
        entrada, midia, _ = pastas(tmp)
        for nome in ('Coroai.m4a', 'Coroai (2).m4a', 'Luz.m4a', 'Xyz.m4a', 'Feliz.mp3', 'Certeza.wav',
                     'nota.txt', '.oculto.m4a', 'Feliz.parte.m4a'):
            (entrada / nome).write_bytes(b'x')
        (midia / 'hinos').mkdir(parents=True)
        (midia / 'hinos' / 'feliz.m4a').write_bytes(b'no ar')
        brutos = eh.arquivos_brutos(entrada)
        # Ordem pelo nome normalizado ('coroai' < 'coroai 2'); .txt, oculto e
        # .parte ficam de fora.
        assert [p.name for p in brutos] == ['Certeza.wav', 'Coroai.m4a', 'Coroai (2).m4a', 'Feliz.mp3',
                                            'Luz.m4a', 'Xyz.m4a'], [p.name for p in brutos]
        por_nome = {i.nome: i for i in eh.planejar(brutos, slugs, midia)}
        assert (por_nome['Certeza.wav'].status, por_nome['Certeza.wav'].slug) == ('novo', 'certeza')
        assert por_nome['Feliz.mp3'].status == 'já no ar'
        assert por_nome['Luz.m4a'].status == 'ambíguo' and por_nome['Luz.m4a'].slug is None
        assert por_nome['Xyz.m4a'].status == 'sem par' and not por_nome['Xyz.m4a'].candidatos
        # "Coroai (2)" casa com coroai por prefixo: dois brutos no mesmo slug.
        assert por_nome['Coroai.m4a'].status == por_nome['Coroai (2).m4a'].status == 'repetido'
        assert por_nome['Certeza.wav'].destino == midia / 'hinos' / 'certeza.m4a'
        refazer = {i.nome: i for i in eh.planejar(brutos, slugs, midia, refazer=True)}
        assert refazer['Feliz.mp3'].status == 'refazer'


# ---------------------------------------------------------------------------
# Linha de comando: parar antes de editar, --mapa, --so-listar, --refazer
# ---------------------------------------------------------------------------

def teste_ambiguo_e_sem_par_param_antes_de_editar_qualquer_coisa():
    with tempfile.TemporaryDirectory() as tmp:
        entrada, midia, log = pastas(tmp)
        tom_alto(entrada / 'Coroai.wav')          # editável, mas não pode ser editado
        (entrada / 'Luz.m4a').write_bytes(b'x')   # ambíguo
        (entrada / 'Xyz.m4a').write_bytes(b'x')   # sem par
        deve_parar(args_comuns(entrada, midia, log), '2 problema(s)')
        assert not midia.exists(), 'nada pode ser gravado com problema de casamento'
        assert not log.exists()
        # Só o repetido também para — e os DOIS arquivos do par são problema.
        (entrada / 'Luz.m4a').unlink()
        (entrada / 'Xyz.m4a').unlink()
        (entrada / 'Coroai 2.wav').write_bytes(b'x')
        deve_parar(args_comuns(entrada, midia, log), '2 problema(s)')
        assert not midia.exists() and not log.exists()


def teste_mapa_resolve_ambiguo_e_sem_par_e_recusa_slug_desconhecido():
    with tempfile.TemporaryDirectory() as tmp:
        entrada, midia, log = pastas(tmp)
        tom_alto(entrada / 'Luz.wav')
        tom_alto(entrada / 'Xyz.wav')
        mapa = Path(tmp) / 'mapa.json'
        mapa.write_text(json.dumps({'Luz.wav': 'luz-divina', 'Xyz': 'certeza',
                                    'Não está na pasta.m4a': 'feliz'}), encoding='utf-8')
        assert eh.main(args_comuns(entrada, midia, log) + ['--mapa', str(mapa)]) == 0
        assert sorted(p.name for p in (midia / 'hinos').glob('*.m4a')) == ['certeza.m4a', 'luz-divina.m4a']
        assert sorted((r['bruto'], r['slug'], r['regra']) for r in registros(log)) == \
               [('Luz.wav', 'luz-divina', 'mapa'), ('Xyz.wav', 'certeza', 'mapa')]
        # Slug que o app não tem: para na leitura do mapa, antes de tudo.
        mapa.write_text(json.dumps({'Luz.wav': 'nao-existe'}), encoding='utf-8')
        deve_parar(args_comuns(entrada, midia, log) + ['--mapa', str(mapa), '--refazer'], 'nao-existe')


def teste_so_listar_nao_grava_nada_e_devolve_1_com_problema():
    with tempfile.TemporaryDirectory() as tmp:
        entrada, midia, log = pastas(tmp)
        tom_alto(entrada / 'Coroai.wav')
        assert eh.main(args_comuns(entrada, midia, log) + ['--so-listar']) == 0
        assert not midia.exists() and not log.exists()
        (entrada / 'Luz.m4a').write_bytes(b'x')
        assert eh.main(args_comuns(entrada, midia, log) + ['--so-listar']) == 1
        assert not midia.exists() and not log.exists()


def teste_os_15_no_ar_nao_sao_tocados_sem_refazer():
    """Cópia dos 15 de hinos/ num --midia temporário + os 15 nomes brutos
    (arquivos falsos: se a ferramenta tentasse editar, o ffmpeg falharia e
    o log acusaria). Sem --refazer, nada muda: nem bytes, nem log."""
    with tempfile.TemporaryDirectory() as tmp:
        entrada, midia, log = pastas(tmp)
        shutil.copytree(HINOS_NO_AR, midia / 'hinos', ignore=shutil.ignore_patterns('.gitkeep'))
        antes = {p.name: sha(p) for p in (midia / 'hinos').glob('*.m4a')}
        assert len(antes) == 15
        for nome in OS_15_DE_24_09:
            (entrada / unicodedata.normalize('NFD', nome)).write_bytes(b'falso')
        assert eh.main(args_comuns(entrada, midia, log)) == 0
        assert {p.name: sha(p) for p in (midia / 'hinos').glob('*.m4a')} == antes
        assert not any((midia / 'hinos').glob('*.parte*'))
        assert not log.exists()


def teste_refazer_regrava_so_o_escolhido_e_mantem_o_que_estava_no_ar_se_reprovar():
    with tempfile.TemporaryDirectory() as tmp:
        entrada, midia, log = pastas(tmp)
        tom_alto(entrada / 'Coroai.wav')
        tom_alto(entrada / 'Certeza.wav')
        (midia / 'hinos').mkdir(parents=True)
        for slug in ('coroai', 'certeza'):
            (midia / 'hinos' / f'{slug}.m4a').write_bytes(b'no ar')
        # Sem --refazer: os dois ficam como estão.
        assert eh.main(args_comuns(entrada, midia, log)) == 0
        assert (midia / 'hinos' / 'coroai.m4a').read_bytes() == b'no ar'
        assert not log.exists()
        # --refazer --apenas: só o coroai muda.
        assert eh.main(args_comuns(entrada, midia, log) + ['--refazer', '--apenas', 'Coroai.wav']) == 0
        assert (midia / 'hinos' / 'coroai.m4a').stat().st_size > 1000
        assert (midia / 'hinos' / 'certeza.m4a').read_bytes() == b'no ar'
        assert [(r['slug'], r['refeito'], r['aprovado']) for r in registros(log)] == [('coroai', True, True)]
        # --apenas com nome que não está na pasta para.
        deve_parar(args_comuns(entrada, midia, log) + ['--refazer', '--apenas', 'Nada.wav'], 'Nada.wav')
        # Reprovado ao refazer: o que estava no ar fica, o novo vai para
        # hinos-reprovados/ ao lado do log, e a saída é 1.
        pico = eh.PICO_MAXIMO
        try:
            eh.PICO_MAXIMO = -100.0  # nenhum arquivo passa
            assert eh.main(args_comuns(entrada, midia, log) + ['--refazer', '--apenas', 'Certeza.wav']) == 1
        finally:
            eh.PICO_MAXIMO = pico
        assert (midia / 'hinos' / 'certeza.m4a').read_bytes() == b'no ar'
        assert (log.parent / 'hinos-reprovados' / 'certeza.m4a').stat().st_size > 1000
        assert not any((midia / 'hinos').glob('*.parte*'))
        ultimo = registros(log)[-1]
        assert ultimo['slug'] == 'certeza' and ultimo['ok'] and not ultimo['aprovado']
        assert 'aceito' in ultimo['motivo']


# ---------------------------------------------------------------------------
# Receita
# ---------------------------------------------------------------------------

def teste_receita_tom_a_menos_12_lufs_estourando_sai_a_menos_20_sem_estourar_e_com_fades():
    with tempfile.TemporaryDirectory() as tmp:
        entrada, midia, log = pastas(tmp)
        bruto = tom_alto(entrada / 'Coroai.wav')
        antes = eh.analisar(bruto)
        assert abs(antes['lufs'] - (-12)) < 1.0, antes['lufs']
        assert antes['pico'] > 0 and antes['estoura'], antes['pico']
        assert antes['entrada_seca'] and antes['saida_seca'], antes['rms']
        assert abs(antes['segundos'] - 5.0) < 0.05

        assert eh.main(args_comuns(entrada, midia, log)) == 0
        saida = midia / 'hinos' / 'coroai.m4a'
        depois = eh.medir(saida)
        assert abs(depois['input_i'] - eh.ALVO_LUFS) <= eh.TOLERANCIA_LUFS, depois['input_i']
        assert depois['input_tp'] <= eh.PICO_MAXIMO, depois['input_tp']
        # Fades: os 0,1 s iniciais e finais bem abaixo do RMS do meio.
        medio, inicio, fim = eh.bordas(saida, janela=0.1)
        assert inicio < medio - 8, (medio, inicio)
        assert fim < medio - 8, (medio, fim)
        # Formato de entrega: AAC mono 48 kHz, ~96 kbps.
        info = eh.subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_name,sample_rate,channels',
             '-of', 'default=nw=1', str(saida)], capture_output=True, text=True, check=True).stdout
        assert 'codec_name=aac' in info and 'sample_rate=48000' in info and 'channels=1' in info
        assert abs(eh.duracao_segundos(saida) - 5.0) < 0.1
        # O log: uma linha, com antes e depois, a chave publicada, aprovado.
        (r,) = registros(log)
        assert r['arquivo'] == 'hinos/coroai.m4a' and r['bruto'] == 'Coroai.wav' and r['regra'] == 'igual'
        assert r['ok'] and r['aprovado'] and not r['refeito']
        assert r['antes']['estoura'] and r['antes']['entrada_seca'] and r['antes']['saida_seca']
        assert r['depois']['lufs'] == depois['input_i'] and r['depois']['pico'] == depois['input_tp']
        assert r['depois']['bytes'] == saida.stat().st_size
        assert r['depois']['normalizacao'] in ('linear', 'dynamic')


def teste_tom_baixo_que_precisa_subir_7_db_sai_no_alvo_sem_passar_do_teto():
    """Tom baixo (-27 LUFS) com pulso a -1 dBTP: subir 7 dB levaria o pulso
    a +6 dBTP. Num sintético o próprio loudnorm segura (cai para o modo
    dinâmico); o caso real em que só o limitador segurou foi "Que segurança"
    (+1,17 dBTP sem ele) — daí o limitador ficar na cadeia, depois do
    loudnorm e antes dos fades."""
    with tempfile.TemporaryDirectory() as tmp:
        entrada, midia, log = pastas(tmp)
        bruto = tom_baixo(entrada / 'Certeza.wav')
        antes = eh.medir(bruto)
        assert antes['input_i'] < -24 and -3 < antes['input_tp'] < 0, antes
        assert eh.main(args_comuns(entrada, midia, log)) == 0
        depois = eh.medir(midia / 'hinos' / 'certeza.m4a')
        assert abs(depois['input_i'] - eh.ALVO_LUFS) <= eh.TOLERANCIA_LUFS, depois
        assert depois['input_tp'] <= eh.PICO_MAXIMO, depois
        antes_completo = eh.analisar(bruto)
        filtro = eh.filtro_de_edicao(antes_completo['medida'], antes_completo['duracao'])
        loudnorm, limitador, fade_in, fade_out = (filtro.index(x) for x in (
            'loudnorm=', ',alimiter=limit=0.84:level=disabled,', ',afade=t=in:', ',afade=t=out:'))
        assert loudnorm < limitador < fade_in < fade_out, filtro


def teste_filtro_de_edicao_reproduz_a_receita_de_24_09():
    medida = {'input_i': -26.6, 'input_tp': -1.29, 'input_lra': 6.6, 'input_thresh': -36.85,
              'target_offset': 0.09}
    assert eh.filtro_de_edicao(medida, 33.088) == (
        'loudnorm=I=-20.0:TP=-1.5:LRA=11:measured_I=-26.6:measured_TP=-1.29:measured_LRA=6.6'
        ':measured_thresh=-36.85:offset=0.09:linear=true:print_format=json'
        ',alimiter=limit=0.84:level=disabled,afade=t=in:st=0:d=0.25,afade=t=out:st=31.888:d=1.2')
    assert eh.filtro_de_edicao(medida, 0.5).endswith('afade=t=out:st=0.000:d=1.2')
    assert eh.PARAMETROS_AAC_HINO == ['-c:a', 'aac', '-b:a', '96k', '-ac', '1', '-ar', '48000',
                                      '-movflags', '+faststart']


# ---------------------------------------------------------------------------
# Voz
# ---------------------------------------------------------------------------

def teste_contar_palavras_ignora_marcas_de_musica():
    assert eh.contar_palavras('[MÚSICA]') == 0
    assert eh.contar_palavras('[MÚSICA DE FUNDO] [MÚSICA DE FUNDO]') == 0
    assert eh.contar_palavras('♫ Abertura ♫') == 1
    assert eh.contar_palavras('(música) ♪♪') == 0
    assert eh.contar_palavras('Castelo forte é nosso Deus, espada e bom escudo.') == 9
    assert eh.contar_palavras('1 2 3 ...') == 0
    assert eh.contar_palavras('Eu creio, sim') == 3 < eh.PALAVRAS_PARA_TER_VOZ
    assert eh.contar_palavras('Eu creio, sim, senhor') == 4 >= eh.PALAVRAS_PARA_TER_VOZ


def teste_conferir_voz_roda_o_whisper_num_temporario_ascii():
    if not eh.whisper_disponivel():
        pular(f'sem {eh.WHISPER} ou {eh.MODELO_WHISPER}')
    with tempfile.TemporaryDirectory() as tmp:
        # Nome com acento e em NFD, como o iPhone grava: o wav vai com nome ASCII.
        bruto = tom_alto(Path(tmp) / unicodedata.normalize('NFD', 'Pão da Vida.wav'))
        voz, palavras, transcricao = eh.conferir_voz(bruto, 7)
        assert isinstance(voz, bool) and isinstance(palavras, int) and isinstance(transcricao, str)
        assert voz == (palavras >= eh.PALAVRAS_PARA_TER_VOZ)
        print(f'  whisper no tom: {palavras} palavra(s): {transcricao!r}')
        assert not [p for p in Path(tempfile.gettempdir()).glob('editar_hinos_voz_*')], \
            'o temporário do whisper não foi apagado'


# ---------------------------------------------------------------------------

def main():
    """Roda tudo sem pytest."""
    testes = [(nome, obj) for nome, obj in sorted(globals().items())
              if nome.startswith('teste_') and callable(obj)]
    falhas = pulados = 0
    for nome, teste in testes:
        try:
            teste()
            print(f'ok    {nome}')
        except Pulado as e:
            pulados += 1
            print(f'pulou {nome}: {e}')
        except Exception:  # noqa: BLE001
            falhas += 1
            print(f'FALHA {nome}')
            traceback.print_exc()
    print(f'{chr(10)}{len(testes) - falhas - pulados} ok, {falhas} falha(s), {pulados} pulado(s)')
    return 1 if falhas else 0


if __name__ == '__main__':
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, 'reconfigure'):
            fluxo.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
