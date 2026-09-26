#!/usr/bin/env python3
"""Edita as gravações brutas dos hinos e as deixa prontas para o manifesto.

Gregory grava os hinos no iPhone (instrumental, AAC mono 48 kHz, ~70 kbps,
18–62 s) e deixa na pasta do OneDrive, com o título do hino em português
livre no nome do arquivo ("Mais perto ,Meu Deus, de Ti.m4a", "Fonte de toda
benção.m4a"). Esta ferramenta:

  1. casa cada gravação com UM hino do app (assets/content/hinos/*.json:
     `titulo` e `audioAsset` = assets/audio/hinos/<slug>.m4a);
  2. edita pela receita aprovada em 24/09/2026 (os 15 primeiros hinos, commit
     8dbf52b), para as novas soarem iguais às que já estão no ar;
  3. grava em <midia>/hinos/<slug>.m4a e MEDE o resultado antes de aceitar;
  4. registra tudo em ferramentas/narracao/editar_hinos.log.jsonl.

Casamento nome -> slug. Os dois lados são normalizados (NFKD sem acentos,
minúsculas, só [a-z0-9] separados por espaço) e comparados em camadas, da
mais estrita para a mais frouxa — a primeira camada que casa decide:
  igual     nome == título ou nome == slug;
  prefixo   um é prefixo do outro (título), ou o slug começa pelo nome;
  palavras  as palavras do nome aparecem, na ordem, no título ou no slug
            ("Santo santo Deus onipotente" -> santo-santo-santo-deus-onipotente:
            Gregory pulou um "santo"; sem esta camada ficaria sem par).
Nome que casa com DOIS slugs numa camada, ou com NENHUM em camada alguma,
PARA a ferramenta antes de editar qualquer coisa — a tabela diz o quê (regra
do projeto: parar e relatar, nunca adivinhar). Os casos difíceis se fixam
com --mapa arquivo.json: {"nome do arquivo.m4a": "slug"}. Dois arquivos
brutos no mesmo slug também param. Slug já gravado em hinos/ só é regravado
com --refazer — e, ao refazer, o arquivo no ar só é trocado se o novo passar
na conferência.

Receita (a mesma das 15; não mude os números sem dizer):
  1º passe     loudnorm=I=-20:TP=-1.5:LRA=11 só mede (print_format=json);
  2º passe     loudnorm com os measured_* e o offset do 1º e linear=true,
               DEPOIS alimiter=limit=0.84:level=disabled — o modo linear não
               segura transiente: "Que segurança" saiu em +1,17 dBTP sem o
               limitador; afade de 0,25 s na entrada e de 1,2 s na saída
               (início = duração medida - 1,2, três casas);
               AAC mono 96 kbps a 48 kHz, faststart.
  Conferido em 26/09/2026: com esta cadeia, os 15 brutos de 24/09 saem
  byte a byte iguais aos 15 que estão no ar (o AAC do ffmpeg 9 é
  determinístico) — sem o offset, "Coroai" sairia em -22,9 LUFS.
  conferência  o arquivo gravado é medido de novo; passa se ficou em
               -20 ± 1,5 LUFS e pico verdadeiro <= -0,3 dBTP. Senão vai ao
               log como reprovado, sai de hinos/ (o manifesto pegaria) e fica
               em ferramentas/narracao/hinos-reprovados/ para ouvir.

Por arquivo, imprime o que vai no relatório ao Gregory — antes: duração,
LUFS, pico verdadeiro, se estourava (> 0 dBTP), se entra/corta seco (RMS dos
0,4 s iniciais/finais a menos de 6 dB do RMS médio); depois: LUFS, pico,
tamanho. No fim, a tabela e o resumo (casados, editados, reprovados, já no
ar; dispersão de LUFS antes e depois).

--conferir-voz: Gregory quer INSTRUMENTAL. Com a flag, e se o whisper-cli e
o modelo small existirem, cada gravação é transcrita (wav 16 kHz mono num
temporário de nome ASCII — nome com acento quebra o whisper-cli pelo shell)
e "parece ter voz" se a transcrição tiver 4 ou mais palavras de letras
(fora [MÚSICA], ♫ e afins). Não bloqueia: sai no relatório, Gregory decide.

Depois de editar, a ferramenta imprime os próximos passos (manifesto no repo
do app, commit por pathspec, push) e NÃO os executa: nada de git aqui.

Uso:
  python ferramentas/editar_hinos.py --so-listar        # tabela arquivo -> slug -> status; não toca em nada
  python ferramentas/editar_hinos.py                    # edita o que é novo
  python ferramentas/editar_hinos.py --conferir-voz
  python ferramentas/editar_hinos.py --mapa ferramentas/hinos-mapa.json
  python ferramentas/editar_hinos.py --apenas "Coroai.m4a" --refazer
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from array import array
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from narrar import RAIZ, duracao_segundos, registrar  # noqa: E402

# O repo do app: a pasta-irmã deste, ou onde MANHA_DE_FE_APP apontar (como
# em narrar_trechos.py); --app manda por cima dos dois.
APP_PADRAO = (Path(os.environ['MANHA_DE_FE_APP']) if os.environ.get('MANHA_DE_FE_APP')
              else RAIZ.parent / 'manha-de-fe-app')
# Onde os hinos são gravados (hinos/ na raiz do repo de mídia); --midia manda
# por cima — os testes apontam um temporário para nunca escrever no repo real.
MIDIA_PADRAO = RAIZ
PASTA_DOS_HINOS = 'hinos'
ENTRADA_PADRAO = Path('C:/Users/robot/OneDrive/Área de Trabalho/Aplicativo Manhã de Fé/'
                      'Músicas gravadas Manha de Fé')
LOG = RAIZ / 'ferramentas' / 'narracao' / 'editar_hinos.log.jsonl'
EXTENSOES = ('.m4a', '.mp3', '.wav')

# ---------------------------------------------------------------------------
# A receita de 24/09/2026. Mudar qualquer número aqui faz o lote novo soar
# diferente dos 15 que já estão no ar — só com decisão registrada.
# ---------------------------------------------------------------------------
ALVO_LUFS = -20.0         # o mesmo alvo das outras faixas do app
ALVO_TP = -1.5            # teto do loudnorm (dBTP)
ALVO_LRA = 11
LIMITE_DO_LIMITADOR = 0.84  # ~ -1,5 dBFS, linear; segura o transiente que o loudnorm linear deixa passar
FADE_ENTRADA = 0.25
FADE_SAIDA = 1.2
PARAMETROS_AAC_HINO = ['-c:a', 'aac', '-b:a', '96k', '-ac', '1', '-ar', '48000',
                       '-movflags', '+faststart']
# Conferência do arquivo gravado.
TOLERANCIA_LUFS = 1.5     # aceito: -20 ± 1,5 LUFS
PICO_MAXIMO = -0.3        # aceito: pico verdadeiro <= -0,3 dBTP
# Análise "antes": entra/corta seco = o RMS da borda fica a menos de
# MARGEM_SECA_DB do RMS médio (não há respiro natural na gravação).
JANELA_SECA = 0.4
MARGEM_SECA_DB = 6.0
TAXA_DE_ANALISE = 48000

# Detecção de voz (--conferir-voz).
WHISPER = Path('C:/Users/robot/bin/whisper-cli.exe')
MODELO_WHISPER = Path('C:/Users/robot/.cache/hyperframes/whisper/models/ggml-small.bin')
PALAVRAS_PARA_TER_VOZ = 4

REGRAS = ('igual', 'prefixo', 'palavras')
PROBLEMAS = ('ambíguo', 'sem par', 'repetido')


# ---------------------------------------------------------------------------
# Casamento nome -> slug
# ---------------------------------------------------------------------------

def normalizar(texto):
    """'Fonte de toda benção' -> 'fonte de toda bencao'. Vale para o nome do
    arquivo (o iPhone grava em NFD: 'ç' = 'c' + cedilha combinante), para o
    título do JSON e para o slug (os hifens viram espaço)."""
    t = unicodedata.normalize('NFKD', texto)
    t = ''.join(c for c in t if not unicodedata.combining(c)).lower()
    return ' '.join(re.findall(r'[a-z0-9]+', t))


def nfc(texto):
    """Para comparar e imprimir nomes: o que Gregory digita num JSON vem em
    NFC, o que o iPhone grava vem em NFD — são o mesmo nome."""
    return unicodedata.normalize('NFC', texto)


def catalogo(app):
    """{slug: {títulos}} lido de assets/content/hinos/*.json — 366 JSONs (um
    por dia), 113 slugs: vários dias tocam o mesmo hino. audioAsset fora de
    assets/audio/hinos/<slug>.m4a para a ferramenta."""
    pasta = app / 'assets' / 'content' / PASTA_DOS_HINOS
    arquivos = sorted(pasta.glob('*.json'))
    if not arquivos:
        sys.exit(f'nenhum hino em {pasta}: aponte o repo do app com --app ou MANHA_DE_FE_APP')
    prefixo = f'assets/audio/{PASTA_DOS_HINOS}/'
    slugs = {}
    for caminho in arquivos:
        with open(caminho, encoding='utf-8') as f:
            dados = json.load(f)
        asset = dados.get('audioAsset', '')
        if not (asset.startswith(prefixo) and asset.endswith('.m4a')):
            sys.exit(f'{caminho.name}: audioAsset "{asset}" fora de {prefixo}<slug>.m4a')
        slugs.setdefault(asset[len(prefixo):-4], set()).add(dados['titulo'])
    return slugs


def _subsequencia(curta, longa):
    """As palavras de `curta` aparecem em `longa`, na mesma ordem (pode
    haver outras entre elas)."""
    i = 0
    for p in longa:
        if i < len(curta) and p == curta[i]:
            i += 1
    return i == len(curta)


def casar(nome, slugs):
    """(slugs que casam, regra). A primeira camada com algum casamento
    decide; dois slugs na mesma camada = ambíguo; lista vazia = sem par."""
    n = normalizar(nome)
    if not n:
        return [], 'sem par'
    palavras = n.split()
    achados = {regra: [] for regra in REGRAS}
    for slug, titulos in slugs.items():
        s = normalizar(slug)
        ts = [normalizar(t) for t in titulos]
        if n == s or n in ts:
            achados['igual'].append(slug)
        elif s.startswith(n) or any(t.startswith(n) or n.startswith(t) for t in ts):
            achados['prefixo'].append(slug)
        elif _subsequencia(palavras, s.split()) or any(_subsequencia(palavras, t.split()) for t in ts):
            achados['palavras'].append(slug)
    for regra in REGRAS:
        if achados[regra]:
            return sorted(achados[regra]), regra
    return [], 'sem par'


@dataclass
class Item:
    """Uma gravação bruta e o que a ferramenta decidiu sobre ela."""
    bruto: Path
    slug: str = None
    regra: str = ''
    candidatos: list = field(default_factory=list)
    status: str = ''       # novo / refazer / já no ar / ambíguo / sem par / repetido
    destino: Path = None
    registro: dict = None

    @property
    def nome(self):
        return nfc(self.bruto.name)


def arquivos_brutos(pasta):
    if not pasta.is_dir():
        sys.exit(f'pasta de entrada não existe: {pasta}')
    return sorted((p for p in pasta.iterdir()
                   if p.is_file() and p.suffix.lower() in EXTENSOES
                   and not p.name.startswith('.') and '.parte' not in p.name),
                  key=lambda p: normalizar(p.stem))


def ler_mapa(caminho, slugs, brutos):
    """{nome do arquivo: slug} fixado à mão. A chave é o nome com ou sem
    extensão. Slug que não existe no app para a ferramenta; chave que não
    bate com arquivo nenhum só avisa (o arquivo pode ter saído da pasta)."""
    with open(caminho, encoding='utf-8') as f:
        mapa = json.load(f)
    por_nome = {}
    for p in brutos:
        por_nome[nfc(p.name)] = p
        por_nome[nfc(p.stem)] = p
    fixado = {}
    for chave, slug in mapa.items():
        if slug not in slugs:
            sys.exit(f'--mapa: "{chave}" -> "{slug}", mas esse slug não existe no app')
        p = por_nome.get(nfc(chave))
        if p is None:
            print(f'aviso: --mapa cita "{chave}", que não está na pasta de entrada')
            continue
        fixado[p] = slug
    return fixado


def planejar(brutos, slugs, midia, fixado=None, refazer=False):
    """Um Item por gravação, com slug e status. Dois brutos no mesmo slug
    gravariam um por cima do outro: os dois ficam 'repetido'."""
    fixado = fixado or {}
    itens = []
    for p in brutos:
        item = Item(bruto=p)
        if p in fixado:
            item.slug, item.regra, item.candidatos = fixado[p], 'mapa', [fixado[p]]
        else:
            item.candidatos, item.regra = casar(p.stem, slugs)
            if len(item.candidatos) == 1:
                item.slug = item.candidatos[0]
        if item.slug is None:
            item.status = 'ambíguo' if item.candidatos else 'sem par'
        else:
            item.destino = Path(midia) / PASTA_DOS_HINOS / f'{item.slug}.m4a'
            if item.destino.exists():
                item.status = 'refazer' if refazer else 'já no ar'
            else:
                item.status = 'novo'
        itens.append(item)
    por_slug = {}
    for item in itens:
        if item.slug:
            por_slug.setdefault(item.slug, []).append(item)
    for grupo in por_slug.values():
        if len(grupo) > 1:
            for item in grupo:
                item.status = 'repetido'
    return itens


# ---------------------------------------------------------------------------
# Medição e análise
# ---------------------------------------------------------------------------

def _json_do_loudnorm(stderr):
    """O loudnorm imprime o JSON no stderr, depois do cabeçalho do ffmpeg;
    números viram float, o resto ('dynamic', 'linear') fica texto."""
    blocos = re.findall(r'\{[^{}]*\}', stderr)
    if not blocos:
        raise RuntimeError(f'loudnorm sem JSON: {stderr.strip()[-300:]}')
    saida = {}
    for k, v in json.loads(blocos[-1]).items():
        try:
            saida[k] = float(v)
        except ValueError:
            saida[k] = v
    return saida


def _ffmpeg(args, rotulo):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', *args],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError(f'ffmpeg ({rotulo}) falhou: {r.stderr.strip()[-300:]}')
    return r.stderr


def medir(caminho):
    """1º passe do loudnorm: mede, não grava. É a análise "antes" e a
    conferência "depois" (input_i = LUFS integrado, input_tp = pico
    verdadeiro em dBTP, input_lra, input_thresh, target_offset)."""
    stderr = _ffmpeg(['-i', str(caminho),
                      '-af', f'loudnorm=I={ALVO_LUFS}:TP={ALVO_TP}:LRA={ALVO_LRA}:print_format=json',
                      '-f', 'null', '-'], 'medição')
    return _json_do_loudnorm(stderr)


def rms_db(amostras):
    if not len(amostras):
        return -120.0
    ms = sum(x * x for x in amostras) / len(amostras)
    return 10 * math.log10(ms) if ms > 0 else -120.0


def bordas(caminho, janela=JANELA_SECA):
    """(RMS médio, RMS dos primeiros `janela` s, RMS dos últimos) em dB,
    decodificando em PCM float mono a 48 kHz — sem numpy."""
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(caminho), '-f', 'f32le',
                        '-ac', '1', '-ar', str(TAXA_DE_ANALISE), '-'], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f'ffmpeg (decodificação) falhou: '
                           f'{r.stderr.decode("utf-8", "replace").strip()[-300:]}')
    a = array('f')
    a.frombytes(r.stdout)
    n = int(janela * TAXA_DE_ANALISE)
    return rms_db(a), rms_db(a[:n]), rms_db(a[-n:])


def analisar(caminho):
    """A análise "antes" que vai ao relatório, mais a medição crua do 1º
    passe (em 'medida'), que o 2º passe consome."""
    m = medir(caminho)
    medio, inicio, fim = bordas(caminho)
    duracao = duracao_segundos(caminho)
    # 'duracao' vai inteira ao 2º passe: o início do fade de saída é
    # duração - 1,2 s com três casas. Arredondar antes muda o filtro em 1 ms
    # e o arquivo deixa de sair byte a byte igual aos 15 de 24/09.
    return {'segundos': round(duracao, 2),
            'lufs': m['input_i'], 'pico': m['input_tp'], 'lra': m['input_lra'],
            'estoura': m['input_tp'] > 0,
            'entrada_seca': inicio > medio - MARGEM_SECA_DB,
            'saida_seca': fim > medio - MARGEM_SECA_DB,
            'rms': {'medio': round(medio, 1), 'inicio': round(inicio, 1), 'fim': round(fim, 1)},
            'medida': m, 'duracao': duracao}


# ---------------------------------------------------------------------------
# Edição
# ---------------------------------------------------------------------------

def filtro_de_edicao(medida, segundos):
    """A cadeia do 2º passe, a partir da medição do 1º. A ordem importa:
    loudnorm (linear) -> limitador -> fades. O fade de saída começa em
    duração - 1,2 s (o loudnorm linear não muda a duração)."""
    inicio_do_fade = max(0.0, segundos - FADE_SAIDA)
    return (f'loudnorm=I={ALVO_LUFS}:TP={ALVO_TP}:LRA={ALVO_LRA}'
            f':measured_I={medida["input_i"]}:measured_TP={medida["input_tp"]}'
            f':measured_LRA={medida["input_lra"]}:measured_thresh={medida["input_thresh"]}'
            f':offset={medida["target_offset"]}:linear=true:print_format=json'
            f',alimiter=limit={LIMITE_DO_LIMITADOR}:level=disabled'
            f',afade=t=in:st=0:d={FADE_ENTRADA}'
            f',afade=t=out:st={inicio_do_fade:.3f}:d={FADE_SAIDA}')


def editar(bruto, saida, medida, segundos):
    """2º passe: grava `saida` e devolve o JSON que o loudnorm imprime ao
    aplicar (normalization_type diz se o linear valeu ou se o ffmpeg caiu
    para o dinâmico — vai ao log)."""
    saida.parent.mkdir(parents=True, exist_ok=True)
    try:
        stderr = _ffmpeg(['-y', '-i', str(bruto), '-af', filtro_de_edicao(medida, segundos),
                          *PARAMETROS_AAC_HINO, str(saida)], 'edição')
    except Exception:
        if saida.exists():
            saida.unlink()
        raise
    return _json_do_loudnorm(stderr)


def aprovado(depois):
    return (abs(depois['input_i'] - ALVO_LUFS) <= TOLERANCIA_LUFS
            and depois['input_tp'] <= PICO_MAXIMO)


# ---------------------------------------------------------------------------
# Voz (--conferir-voz)
# ---------------------------------------------------------------------------

def whisper_disponivel():
    return WHISPER.exists() and MODELO_WHISPER.exists()


_MARCAS_DE_MUSICA = re.compile(r'\[[^\]]*\]|\([^)]*\)|[♪♫]')


def contar_palavras(transcricao):
    """Palavras de letras na transcrição, fora do que o whisper marca como
    música: "[MÚSICA]", "(música)", ♪, ♫."""
    limpo = _MARCAS_DE_MUSICA.sub(' ', transcricao)
    return len(re.findall(r'[^\W\d_]+', limpo))


def conferir_voz(bruto, indice):
    """(parece ter voz, palavras, transcrição). O wav 16 kHz mono vai num
    temporário com nome ASCII (NNN.wav): nome com acento quebra o
    whisper-cli pelo shell."""
    pasta = Path(tempfile.mkdtemp(prefix='editar_hinos_voz_'))
    try:
        wav = pasta / f'{indice:03d}.wav'
        base = pasta / f'{indice:03d}'
        _ffmpeg(['-y', '-i', str(bruto), '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)],
                'wav para o whisper')
        r = subprocess.run([str(WHISPER), '-m', str(MODELO_WHISPER), '-l', 'pt', '-nt', '-otxt',
                            '-np', '-of', str(base), '-f', str(wav)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=900)
        txt = base.with_suffix('.txt')
        if r.returncode != 0 or not txt.exists():
            raise RuntimeError(f'whisper-cli falhou: {(r.stderr or r.stdout).strip()[-300:]}')
        transcricao = ' '.join(txt.read_text(encoding='utf-8', errors='replace').split())
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    palavras = contar_palavras(transcricao)
    return palavras >= PALAVRAS_PARA_TER_VOZ, palavras, transcricao[:200]


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

def processar(item, indice, conferir, log, reprovados):
    """Analisa, edita num .parte, confere e só então põe em hinos/. Reprovado
    vai para `reprovados`/<slug>.m4a e o que estava no ar (se --refazer)
    fica como estava. Uma linha no log de qualquer jeito."""
    registro = {'arquivo': f'{PASTA_DOS_HINOS}/{item.slug}.m4a', 'slug': item.slug,
                'bruto': item.nome, 'regra': item.regra, 'refeito': item.status == 'refazer',
                'quando': time.strftime('%Y-%m-%dT%H:%M:%S')}
    parcial = item.destino.with_suffix('.parte.m4a')
    try:
        antes = analisar(item.bruto)
        medida, duracao = antes.pop('medida'), antes.pop('duracao')
        registro['antes'] = antes
        if conferir:
            try:
                voz, palavras, transcricao = conferir_voz(item.bruto, indice)
                registro['voz'] = {'parece_ter_voz': voz, 'palavras': palavras,
                                   'transcricao': transcricao}
            except Exception as e:  # noqa: BLE001
                registro['voz'] = {'erro': str(e)[:300]}
        aplicado = editar(item.bruto, parcial, medida, duracao)
        depois = medir(parcial)
        registro['depois'] = {'lufs': depois['input_i'], 'pico': depois['input_tp'],
                              'bytes': parcial.stat().st_size,
                              'segundos': round(duracao_segundos(parcial), 2),
                              'normalizacao': aplicado.get('normalization_type')}
        registro['aprovado'] = aprovado(depois)
        if registro['aprovado']:
            parcial.replace(item.destino)
        else:
            reprovados.mkdir(parents=True, exist_ok=True)
            parcial.replace(reprovados / item.destino.name)
            registro['motivo'] = (f'ficou em {depois["input_i"]} LUFS / {depois["input_tp"]} dBTP; '
                                  f'aceito: {ALVO_LUFS} ± {TOLERANCIA_LUFS} LUFS e <= {PICO_MAXIMO} dBTP')
        registro['ok'] = True
    except Exception as e:  # noqa: BLE001
        if parcial.exists():
            parcial.unlink()
        registro.update(ok=False, aprovado=False, erro=str(e)[:300])
    registrar(registro, log)
    item.registro = registro
    return registro


def tabela(itens):
    """arquivo -> slug -> status (-> regra). Ambíguo mostra os candidatos."""
    largura = min(46, max((len(i.nome) for i in itens), default=12))
    largura_slug = max((len(i.slug) for i in itens if i.slug), default=20)
    print(f'{"arquivo bruto":<{largura}}  {"slug":<{largura_slug}}  {"status":<9}  regra')
    for i in itens:
        if i.slug:
            slug = i.slug
        elif i.candidatos:
            slug = 'candidatos: ' + ', '.join(i.candidatos)
        else:
            slug = '-'
        print(f'{i.nome[:largura]:<{largura}}  {slug:<{largura_slug}}  {i.status:<9}  {i.regra}')


def linha_do_resultado(item):
    r = item.registro
    if not r.get('ok'):
        return f'ERRO      {item.slug:<44} {r.get("erro", "")}'
    a, d = r['antes'], r['depois']
    seco = ' entra seco' if a['entrada_seca'] else ''
    seco += ' corta seco' if a['saida_seca'] else ''
    estoura = ' ESTOURAVA' if a['estoura'] else ''
    marca = 'ok       ' if r['aprovado'] else 'REPROVADO'
    voz = ''
    if 'voz' in r:
        voz = ('  ATENÇÃO: parece ter voz' if r['voz'].get('parece_ter_voz')
               else ('  voz?' if 'erro' in r['voz'] else '  instrumental'))
    return (f'{marca} {item.slug:<44} antes {a["segundos"]:5.1f}s {a["lufs"]:6.2f} LUFS '
            f'pico {a["pico"]:5.2f}{estoura}{seco}  |  depois {d["lufs"]:6.2f} LUFS '
            f'pico {d["pico"]:5.2f}  {d["bytes"] // 1024} KB{voz}')


def resumo(itens, processados, midia, app):
    editados = [i for i in processados if i.registro.get('aprovado')]
    reprovados = [i for i in processados if i.registro.get('ok') and not i.registro.get('aprovado')]
    erros = [i for i in processados if not i.registro.get('ok')]
    no_ar = [i for i in itens if i.status == 'já no ar']
    casados = [i for i in itens if i.slug and i.status not in PROBLEMAS]
    problemas = [i for i in itens if i.status in PROBLEMAS]
    print(f'{chr(10)}casados {len(casados)} de {len(itens)} - editados {len(editados)} - '
          f'reprovados {len(reprovados)} - erros {len(erros)} - já no ar {len(no_ar)} - '
          f'problemas {len(problemas)}')
    antes = [i.registro['antes']['lufs'] for i in processados if 'antes' in i.registro]
    depois = [i.registro['depois']['lufs'] for i in editados]
    if antes:
        print(f'LUFS antes:  {min(antes):.2f} a {max(antes):.2f}  (dispersão {max(antes) - min(antes):.1f} dB)')
    if depois:
        picos = [i.registro['depois']['pico'] for i in editados]
        print(f'LUFS depois: {min(depois):.2f} a {max(depois):.2f}  (dispersão {max(depois) - min(depois):.1f} dB); '
              f'pior pico {max(picos):.2f} dBTP')
    estouravam = [i for i in processados if i.registro.get('antes', {}).get('estoura')]
    secos = [i for i in processados if i.registro.get('antes', {}).get('entrada_seca')
             or i.registro.get('antes', {}).get('saida_seca')]
    if estouravam:
        print(f'estouravam (> 0 dBTP): {", ".join(i.nome for i in estouravam)}')
    if secos:
        print(f'entravam/cortavam seco: {", ".join(i.nome for i in secos)}')
    com_voz = [i for i in processados if i.registro.get('voz', {}).get('parece_ter_voz')]
    for i in com_voz:
        v = i.registro['voz']
        print(f'ATENÇÃO: {i.nome} parece ter voz ({v["palavras"]} palavras): "{v["transcricao"]}"')
    for i in reprovados:
        print(f'REPROVADO: {i.nome} -> {i.slug}: {i.registro["motivo"]}')
    for i in erros:
        print(f'ERRO: {i.nome} -> {i.slug}: {i.registro["erro"]}')
    if editados:
        print(f'{chr(10)}Próximos passos (manuais — esta ferramenta não faz git):')
        print(f'  1. no repo do app:      cd {app}')
        print(f'                          dart run tool/midia/gerar_manifesto.dart {midia}')
        print(f'  2. no repo de mídia:    cd {midia}')
        print(f'                          git add -- {PASTA_DOS_HINOS}/ manifesto.json')
        print(f'                          git commit -- {PASTA_DOS_HINOS}/ manifesto.json')
        print('                          git push')
    return editados, reprovados, erros


def main(argv=None):
    # Nomes com acento derrubavam o print no console do Windows (cp1252).
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, 'reconfigure'):
            fluxo.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    ap.add_argument('--entrada', default=str(ENTRADA_PADRAO),
                    help='pasta com as gravações brutas (.m4a/.mp3/.wav)')
    ap.add_argument('--app', default=str(APP_PADRAO),
                    help='raiz do repo manha-de-fe-app (padrão: pasta-irmã, ou MANHA_DE_FE_APP)')
    ap.add_argument('--midia', default=str(MIDIA_PADRAO),
                    help='raiz do repo manhadefe-midia, onde hinos/ é gravado (padrão: este repo)')
    ap.add_argument('--mapa', help='JSON {"nome do arquivo.m4a": "slug"} para os casos difíceis')
    ap.add_argument('--apenas', help='só estes arquivos brutos (nomes, separados por vírgula)')
    ap.add_argument('--so-listar', action='store_true',
                    help='mostra arquivo -> slug -> status e sai sem tocar em nada')
    ap.add_argument('--refazer', action='store_true', help='regrava slug que já está em hinos/')
    ap.add_argument('--conferir-voz', action='store_true',
                    help='transcreve com o whisper-cli e avisa se parece ter voz (não bloqueia)')
    ap.add_argument('--log', default=str(LOG))
    ap.add_argument('--paralelo', type=int, default=3)
    args = ap.parse_args(argv)

    app = Path(args.app)
    if not (app / 'pubspec.yaml').exists():
        sys.exit(f'{app} não parece o repo do app (sem pubspec.yaml): aponte com --app '
                 'ou com a variável de ambiente MANHA_DE_FE_APP')
    midia = Path(args.midia)
    log = Path(args.log)
    reprovados = log.parent / 'hinos-reprovados'

    slugs = catalogo(app)
    brutos = arquivos_brutos(Path(args.entrada))
    fixado = ler_mapa(Path(args.mapa), slugs, brutos) if args.mapa else {}
    itens = planejar(brutos, slugs, midia, fixado, args.refazer)
    pasta_dos_hinos = midia / PASTA_DOS_HINOS
    no_ar = sum(1 for _ in pasta_dos_hinos.glob('*.m4a')) if pasta_dos_hinos.is_dir() else 0
    print(f'{len(brutos)} gravações em {args.entrada}; {len(slugs)} hinos no app; '
          f'{no_ar} já em {pasta_dos_hinos}{chr(10)}')
    tabela(itens)

    problemas = [i for i in itens if i.status in PROBLEMAS]
    a_editar = [i for i in itens if i.status in ('novo', 'refazer')]
    if args.apenas:
        quero = {nfc(n.strip()) for n in args.apenas.split(',') if n.strip()}
        desconhecidos = quero - {i.nome for i in itens} - {nfc(i.bruto.stem) for i in itens}
        if desconhecidos:
            sys.exit(f'--apenas: não estão na pasta de entrada: {sorted(desconhecidos)}')
        a_editar = [i for i in a_editar if i.nome in quero or nfc(i.bruto.stem) in quero]
    print(f'{chr(10)}a editar: {len(a_editar)}  |  já no ar: {sum(1 for i in itens if i.status == "já no ar")}'
          f'  |  problemas: {len(problemas)}')
    if args.so_listar:
        return 1 if problemas else 0
    if problemas:
        print()
        for i in problemas:
            if i.status == 'ambíguo':
                print(f'AMBÍGUO   {i.nome}: casa com {", ".join(i.candidatos)} (regra {i.regra})')
            elif i.status == 'sem par':
                print(f'SEM PAR   {i.nome}: nenhum hino do app casa com este nome')
            else:
                print(f'REPETIDO  {i.nome}: outro arquivo bruto também casa com {i.slug}')
        sys.exit(f'{len(problemas)} problema(s) de casamento — nada editado. Fixe cada um com '
                 '--mapa arquivo.json ({"nome do arquivo.m4a": "slug"}) ou tire o arquivo da pasta, '
                 'e rode de novo.')
    if not a_editar:
        print('nada a editar')
        return 0

    conferir = args.conferir_voz
    if conferir and not whisper_disponivel():
        print(f'aviso: --conferir-voz ignorado, falta {WHISPER} ou {MODELO_WHISPER}')
        conferir = False

    inicio = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.paralelo)) as pool:
        futuros = {pool.submit(processar, item, n, conferir, log, reprovados): item
                   for n, item in enumerate(a_editar, 1)}
        for n, fut in enumerate(as_completed(futuros), 1):
            item = futuros[fut]
            fut.result()
            print(f'[{n}/{len(a_editar)}] {linha_do_resultado(item)}')
    editados, reprovados_, erros = resumo(itens, a_editar, midia, app)
    print(f'{(time.time() - inicio) / 60:.1f} min')
    return 1 if (reprovados_ or erros) else 0


if __name__ == '__main__':
    sys.exit(main())
