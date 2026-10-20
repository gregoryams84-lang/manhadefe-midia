#!/usr/bin/env python3
"""Publica uma temporada da novela "A Palavra em Capítulos" (versão 5 do app,
D1-D12 da spec de 19/10/2026) a partir da ENTREGA do chat da novela.

A entrega é uma pasta (formato fechado com o chat da novela):
  temporada.json   {id, titulo, inicio, capitulos: [{n, data, titulo, gancho,
                    referenciaBiblica, versiculo, reflexao, oracao, duracaoS}]}
  NN-catolico.mp4, NN-evangelico.mp4   os dois vídeos de cada capítulo
  NN.webp          a capa (1080x1350)
  NN.srt           a legenda (opcional)
com NN de 2 dígitos (01, 02...). Outros arquivos da pasta (um LEIA, notas)
são ignorados.

1. CONFERE tudo antes de escrever qualquer coisa; ao falhar, lista TODOS os
   problemas e sai com 1:
   - id `t<número>`; capítulos numerados de 1 a N em ordem; datas que
     existem e consecutivas a partir de `inicio`; duracaoS inteiro;
   - vídeos: os dois de cada capítulo, h264, 720x1280, até 25 MB (D4), a
     duração a 2 s de duracaoS e as duas versões a 0,5 s uma da outra;
   - capa WebP 1080x1350;
   - legenda: SRT que o parser do app lê inteiro, UMA linha por fala, até
     42 caracteres (cabe inteira com a letra no máximo, Ruling 9), cada fala
     com pelo menos 1,5 s, dentro da duração do vídeo e sem sobrepor a
     anterior;
   - textos: versículo até 180 caracteres, reflexão de 40 a 100 palavras
     e no máximo 2 travessões (as réguas do lint do app, contadas do mesmo
     jeito), oração terminando em "Amém.", referência "Livro C,V" ou
     "Livro C,V-V" (a palavra final é do lint, que roda no fim);
   - índice: a temporada não sobrepõe outra de novela/temporadas.json (o
     mesmo id é a versão nova dela, e a substitui);
   - no caminho real, também as ferramentas: as chaves do R2, o boto3, o
     dart, as ferramentas do app e as da voz na raiz de mídia.

2. ESCREVE (tudo conferido):
   - R2: cada mp4 vai ao balde manhadefe-video em
     <r2-prefixo>video/<t>/<NN>-<tradicao>.mp4, com o sha256 nos metadados;
     o que já está lá com o mesmo tamanho e o mesmo sha256 não sobe de
     novo. Vem PRIMEIRO: se o envio falhar, nenhum JSON local aponta para
     um vídeo que não está no ar;
   - <midia>/novela/<t>.json: a temporada no formato do app (Temporada.fromJson
     em lib/content/novela.dart) — por capítulo, `id` <t>c<n>, `capa`,
     `legenda` (só com SRT) e `video` com arquivo, bytes e sha256;
   - capas em <midia>/imagens/<t>c<n>.webp, legendas em
     <midia>/novela/<t>c<n>.srt (sem o BOM, se vier com um); as sobras de
     uma versão anterior da MESMA temporada (capítulo que sumiu, legenda
     que saiu) são apagadas;
   - <midia>/novela/temporadas.json: {versao, videos, temporadas}, em ordem
     de início, as outras mantidas. A base `videos` vem de --videos-base,
     senão do índice existente, senão da "Public Development URL" do
     arquivo de chaves (+ --r2-prefixo), sempre terminando em /;
   - a voz dos cartões dos dias de capítulo (sem --sem-voz):
     texto_narrado.dart --temporadas, narrar.py --ids <t>c1,... --refazer e
     conferir_stt.py --stt whisper — reprovado, para e lista (o manifesto
     não é refeito). Os dois .py rodam a cópia de DENTRO de --midia: eles
     gravam na raiz do repositório em que estão;
   - o manifesto (gerar_manifesto.dart) e o lint (lint_conteudo.dart, 0
     erros, senão sai com 1).
   No fim, o resumo. NUNCA faz commit nem push: commit por caminho, e o
   push só com o OK do Gregory.

--simular: exige --midia numa pasta temporária (nunca o repositório real
nem uma pasta dentro dele); escreve os JSONs, as capas e as legendas nela;
não sobe ao R2, não gera voz e não roda o Dart — imprime o que faria.

As chaves do R2 são lidas do arquivo (--r2) pelos rótulos ("Access Key ID",
"Secret Access Key", a URL https://<conta>.r2.cloudflarestorage.com e a
"Public Development URL") e só usadas dentro do processo: nunca impressas
nem gravadas.

Uso:
  python ferramentas/publicar_temporada.py "<entrega>" --simular --midia <pasta temporária>
  python ferramentas/publicar_temporada.py "<entrega>" --motor microsoft
  python ferramentas/publicar_temporada.py "<entrega>" --midia <cópia do repo> --r2-prefixo teste/midia/ --motor microsoft
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parents[1]
# A raiz de mídia padrão é este repositório; --simular nunca a aceita.
MIDIA_PADRAO = RAIZ
# O repo do app: a pasta-irmã deste, ou onde MANHA_DE_FE_APP apontar.
APP_PADRAO = (Path(os.environ['MANHA_DE_FE_APP']) if os.environ.get('MANHA_DE_FE_APP')
              else RAIZ.parent / 'manha-de-fe-app')
CHAVES_R2_PADRAO = Path('C:/Users/robot/OneDrive/Área de Trabalho/NUVEM GREGORY/'
                        'Cloudflare R2/R2.txt')
DART_PADRAO = Path('C:/Users/robot/flutter-sdk/bin') / ('dart.bat' if os.name == 'nt' else 'dart')
BALDE = 'manhadefe-video'
MOTORES = ('elevenlabs', 'microsoft')
TRADICOES = ('catolico', 'evangelico')

# As réguas da entrega.
LIMITE_DE_BYTES = 25 * 1024 * 1024          # D4: vídeo até 25 MB
TAMANHO_DO_VIDEO = (720, 1280)
TAMANHO_DA_CAPA = (1080, 1350)
FOLGA_DA_DURACAO = 2.0                       # vídeo x duracaoS
FOLGA_ENTRE_VERSOES = 0.5                    # católico x evangélico
MAXIMO_DE_CARACTERES_DA_FALA = 42            # Ruling 9
MINIMO_DE_MS_DA_FALA = 1500
# As do lint do app (tool/lint_conteudo.dart, regras 7, 10 e 13).
MAXIMO_DE_CARACTERES_DO_VERSICULO = 180
PALAVRAS_DA_REFLEXAO = (40, 100)
MAXIMO_DE_TRAVESSOES = 2

CAMPOS_DE_TEXTO = ('titulo', 'gancho', 'referenciaBiblica', 'versiculo', 'reflexao', 'oracao')
# re.ASCII: o \d do Dart (regex de JavaScript) \u00e9 s\u00f3 0-9; o do Python aceitaria
# d\u00edgitos de outras escritas que o app recusa.
ID_DE_TEMPORADA = re.compile(r't\d+', re.ASCII)
_DATA = re.compile(r'\d{4}-\d{2}-\d{2}', re.ASCII)
_ESPACOS = re.compile(r'\s+')
_TRAVESSAO = re.compile('[\u2014\u2013]')
_CAPITULO_E_VERSICULO = re.compile(r'\d+,\d+(-\d+)?', re.ASCII)
_ARQUIVO_DA_ENTREGA = re.compile(r'(\d{2})(-catolico\.mp4|-evangelico\.mp4|\.webp|\.srt)', re.ASCII)
_TEMPO_SRT = re.compile(r'(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)', re.ASCII)


# ---------------------------------------------------------------------------
# A entrega
# ---------------------------------------------------------------------------

@dataclass
class CapituloDaEntrega:
    n: int
    dados: dict                 # o capítulo como veio no temporada.json
    videos: dict                # tradição -> Path
    capa: Path
    legenda: Path | None

    @property
    def nn(self):
        return f'{self.n:02d}'


@dataclass
class Entrega:
    pasta: Path
    id: str
    titulo: str
    inicio: date
    capitulos: list

    @property
    def fim(self):
        return self.inicio + timedelta(days=len(self.capitulos) - 1)

    def id_do_capitulo(self, capitulo):
        return f'{self.id}c{capitulo.n}'


def data_valida(texto):
    """A data AAAA-MM-DD que existe (2026-11-31 não), ou None."""
    if not isinstance(texto, str) or not _DATA.fullmatch(texto):
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def contar_palavras(reflexao):
    """Como o lint do app (regra 13): pedaços separados por espaço; um
    travessão colado entre letras separa dois."""
    total = 0
    for pedaco in _ESPACOS.split(reflexao):
        lados = [s for s in _TRAVESSAO.split(pedaco) if s]
        total += len(lados) or 1
    return total


def referencia_valida(referencia):
    """Como separarReferencia (lib/content/referencia_biblica.dart): o livro
    é tudo antes do último espaço; o resto, "C,V" ou "C,V-V"."""
    aparada = referencia.strip()
    espaco = aparada.rfind(' ')
    if espaco <= 0:
        return False
    return bool(aparada[:espaco].strip()) and bool(
        _CAPITULO_E_VERSICULO.fullmatch(aparada[espaco + 1:]))


def sondar(arquivo):
    """{codec, largura, altura, duracao} do primeiro fluxo de vídeo (a
    imagem WebP conta como um), pelo ffprobe; None se ele não ler."""
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'stream=codec_type,codec_name,width,height:format=duration',
                        '-of', 'json', str(arquivo)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        return None
    dados = json.loads(r.stdout or '{}')
    fluxo = next((s for s in dados.get('streams', []) if s.get('codec_type') == 'video'), {})
    try:
        duracao = float(dados.get('format', {}).get('duration'))
    except (TypeError, ValueError):
        duracao = None
    return {'codec': fluxo.get('codec_name'), 'largura': fluxo.get('width'),
            'altura': fluxo.get('height'), 'duracao': duracao}


def _milhar(n):
    return f'{n:,}'.replace(',', '.')


def _segundos(ms):
    """1400 -> "1,4"; 1499 -> "1,499"; 2000 -> "2"."""
    return f'{ms / 1000:.3f}'.rstrip('0').rstrip('.').replace('.', ',')


def _casas(segundos):
    """87.733 -> "87,73"; 2.0 -> "2"."""
    return f'{segundos:.2f}'.rstrip('0').rstrip('.').replace('.', ',')


def _tempo_srt(ms):
    h, resto = divmod(ms, 3_600_000)
    m, resto = divmod(resto, 60_000)
    s, ms = divmod(resto, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def _linhas_como_o_app(texto):
    """As linhas como o LineSplitter do Dart: \\n, \\r\\n e \\r separam; o
    terminador do fim não cria uma linha vazia."""
    linhas = re.split(r'\r\n|\r|\n', texto)
    if linhas and linhas[-1] == '':
        linhas.pop()
    return linhas


def _blocos_como_o_app(texto):
    """Os blocos como o _readSubRipFile do video_player: as linhas não
    brancas até uma branca (ou até a última linha). Duas brancas seguidas
    fazem um bloco vazio."""
    linhas = _linhas_como_o_app(texto)
    blocos, atual = [], []
    for i, linha in enumerate(linhas):
        branca = linha.strip() == ''
        if not branca:
            atual.append(linha)
        if branca or i == len(linhas) - 1:
            blocos.append(atual)
            atual = []
    return blocos


def conferir_legenda(texto, duracao_do_video):
    """Os problemas da legenda (lista vazia = passa). O app lê o SRT pelo
    SubRipCaptionFile do video_player 2.14: ele PARA no primeiro bloco com
    menos de 3 linhas (uma linha em branco a mais no meio basta), lança no
    bloco que não começa por número (o app então toca sem legenda) e pula em
    silêncio a fala de tempo fora do formato. A tela mostra uma fala por vez,
    numa linha só: até 42 caracteres, pelo menos 1,5 s, dentro do vídeo e
    sem sobrepor a anterior."""
    if texto.startswith('\ufeff'):
        texto = texto[1:]
    blocos = _blocos_como_o_app(texto)
    problemas = []
    falas = fim_anterior = 0
    for i, bloco in enumerate(blocos):
        if not bloco:
            if any(blocos[i + 1:]):
                problemas.append(f'linha em branco a mais depois da fala {falas} — o app para '
                                 'de ler a legenda ali')
            continue
        falas += 1
        if len(bloco) < 3:
            problemas.append(f'fala {falas} com {len(bloco)} linha(s) — cada fala tem número, '
                             'tempo e uma linha de texto; o app para de ler a legenda ali')
            continue
        numero, tempo, texto_da_fala = bloco[0].strip(), bloco[1].strip(), bloco[2:]
        if not re.fullmatch(r'[0-9]+', numero):
            problemas.append(f'fala {falas}: o bloco não começa por número ("{numero}") — o app '
                             'não abre a legenda')
        if len(texto_da_fala) != 1:
            problemas.append(f'fala {falas} com {len(texto_da_fala)} linhas — uma linha só por fala')
        linha = ' '.join(t.strip() for t in texto_da_fala)
        if len(linha) > MAXIMO_DE_CARACTERES_DA_FALA:
            problemas.append(f'fala {falas} com {len(linha)} caracteres ("{linha}") — o máximo é '
                             f'{MAXIMO_DE_CARACTERES_DA_FALA}')
        m = _TEMPO_SRT.fullmatch(tempo)
        if not m:
            problemas.append(f'fala {falas}: tempo "{tempo}" fora do formato '
                             'HH:MM:SS,mmm --> HH:MM:SS,mmm — o app pula a fala')
            continue
        g = [int(x) for x in m.groups()]
        inicio = ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + g[3]
        fim = ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + g[7]
        if fim - inicio < MINIMO_DE_MS_DA_FALA:
            problemas.append(f'fala {falas} dura {_segundos(fim - inicio)} s — o mínimo é '
                             f'{_segundos(MINIMO_DE_MS_DA_FALA)} s')
        if duracao_do_video is not None and fim > round(duracao_do_video * 1000):
            problemas.append(f'fala {falas} termina em {_tempo_srt(fim)}, depois do fim do vídeo '
                             f'({_tempo_srt(round(duracao_do_video * 1000))})')
        if inicio < fim_anterior:
            problemas.append(f'fala {falas} começa em {_tempo_srt(inicio)}, antes do fim da fala '
                             f'anterior ({_tempo_srt(fim_anterior)})')
        fim_anterior = max(fim_anterior, fim)
    if not falas:
        problemas.append('nenhuma fala')
    return problemas


def _conferir_textos(rotulo, cap):
    problemas = []
    for campo in CAMPOS_DE_TEXTO:
        valor = cap.get(campo)
        if not isinstance(valor, str) or not valor.strip():
            problemas.append(f'{rotulo}: sem "{campo}"')
    versiculo = cap.get('versiculo')
    if isinstance(versiculo, str) and len(versiculo) > MAXIMO_DE_CARACTERES_DO_VERSICULO:
        problemas.append(f'{rotulo}: versículo com {len(versiculo)} caracteres — o máximo é '
                         f'{MAXIMO_DE_CARACTERES_DO_VERSICULO} (cabe na imagem de partilha)')
    reflexao = cap.get('reflexao')
    if isinstance(reflexao, str) and reflexao.strip():
        palavras = contar_palavras(reflexao)
        minimo, maximo = PALAVRAS_DA_REFLEXAO
        if not minimo <= palavras <= maximo:
            problemas.append(f'{rotulo}: reflexão com {palavras} palavras — a medida é '
                             f'{minimo} a {maximo}')
        travessoes = len(_TRAVESSAO.findall(reflexao))
        if travessoes > MAXIMO_DE_TRAVESSOES:
            problemas.append(f'{rotulo}: reflexão com {travessoes} travessões — o máximo é '
                             f'{MAXIMO_DE_TRAVESSOES}')
    oracao = cap.get('oracao')
    if isinstance(oracao, str) and oracao.strip() and \
            not unicodedata.normalize('NFC', oracao.strip()).endswith('Amém.'):
        problemas.append(f'{rotulo}: a oração tem de terminar em "Amém."')
    referencia = cap.get('referenciaBiblica')
    if isinstance(referencia, str) and referencia.strip() and not referencia_valida(referencia):
        problemas.append(f'{rotulo}: referência "{referencia}" fora do formato "Livro C,V" ou '
                         '"Livro C,V-V"')
    return problemas


def conferir_entrega(pasta, limite_de_bytes=LIMITE_DE_BYTES):
    """(Entrega ou None, [problemas]). A Entrega vem sempre que o id, o
    início e os capítulos dão para ler — mesmo com problemas, para as outras
    conferências (o índice) também listarem os delas. `limite_de_bytes` é
    parâmetro para o teste não precisar de um vídeo de 25 MB."""
    pasta = Path(pasta)
    arquivo = pasta / 'temporada.json'
    if not pasta.is_dir():
        return None, [f'a entrega {pasta} não é uma pasta']
    if not arquivo.exists():
        return None, [f'falta temporada.json em {pasta}']
    try:
        dados = json.loads(arquivo.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeDecodeError) as e:
        return None, [f'temporada.json não é um JSON válido: {e}']
    if not isinstance(dados, dict):
        return None, ['temporada.json não é um objeto']
    problemas = []
    id_ = dados.get('id')
    id_ok = isinstance(id_, str) and bool(ID_DE_TEMPORADA.fullmatch(id_))
    if not id_ok:
        problemas.append(f'id "{id_}" fora do formato t<número> (t1, t2...): os ids são neutros')
    titulo = dados.get('titulo')
    if not isinstance(titulo, str) or not titulo.strip():
        problemas.append('a temporada não tem "titulo"')
    inicio = data_valida(dados.get('inicio'))
    if inicio is None:
        problemas.append(f'inicio "{dados.get("inicio")}" não é uma data AAAA-MM-DD que exista')
    capitulos = dados.get('capitulos')
    if not isinstance(capitulos, list) or not capitulos:
        problemas.append('a temporada não tem "capitulos"')
        return None, problemas

    lista = []
    for i, cap in enumerate(capitulos, 1):
        rotulo = f'cap. {i}'
        if not isinstance(cap, dict):
            problemas.append(f'{rotulo}: não é um objeto')
            continue
        n = cap.get('n')
        if isinstance(n, bool) or n != i:
            problemas.append(f'{rotulo}: veio com n={n} — os capítulos vão de 1 a '
                             f'{len(capitulos)}, em ordem')
        data = data_valida(cap.get('data'))
        if data is None:
            problemas.append(f'{rotulo}: data "{cap.get("data")}" não é uma data AAAA-MM-DD '
                             'que exista')
        elif inicio is not None and data != inicio + timedelta(days=i - 1):
            problemas.append(f'{rotulo}: data {data} — esperada {inicio + timedelta(days=i - 1)} '
                             f'(datas consecutivas a partir do inicio, {inicio})')
        problemas += _conferir_textos(rotulo, cap)
        duracao = cap.get('duracaoS')
        duracao_ok = isinstance(duracao, int) and not isinstance(duracao, bool) and duracao > 0
        if not duracao_ok:
            problemas.append(f'{rotulo}: duracaoS "{duracao}" tem de ser um número inteiro de '
                             'segundos')

        nn = f'{i:02d}'
        videos, duracoes = {}, {}
        for tradicao in TRADICOES:
            video = pasta / f'{nn}-{tradicao}.mp4'
            if not video.exists():
                problemas.append(f'{rotulo}: falta {video.name}')
                continue
            videos[tradicao] = video
            tamanho = video.stat().st_size
            if tamanho > limite_de_bytes:
                problemas.append(f'{rotulo} ({video.name}): {_milhar(tamanho)} bytes — o máximo é '
                                 f'{_milhar(limite_de_bytes)} bytes (D4)')
            medida = sondar(video)
            if medida is None:
                problemas.append(f'{rotulo} ({video.name}): o ffprobe não leu o arquivo')
                continue
            if medida['codec'] != 'h264':
                problemas.append(f'{rotulo} ({video.name}): vídeo '
                                 f'{medida["codec"] or "(sem fluxo de vídeo)"} — tem de ser h264')
            if (medida['largura'], medida['altura']) != TAMANHO_DO_VIDEO:
                problemas.append(f'{rotulo} ({video.name}): {medida["largura"]}x{medida["altura"]}'
                                 f' — tem de ser {TAMANHO_DO_VIDEO[0]}x{TAMANHO_DO_VIDEO[1]}')
            if medida['duracao'] is None:
                problemas.append(f'{rotulo} ({video.name}): o ffprobe não deu a duração')
                continue
            duracoes[tradicao] = medida['duracao']
            if duracao_ok and abs(medida['duracao'] - duracao) > FOLGA_DA_DURACAO:
                problemas.append(f'{rotulo} ({video.name}): {_casas(medida["duracao"])} s, mas '
                                 f'duracaoS = {duracao} (folga de {_casas(FOLGA_DA_DURACAO)} s)')
        if len(duracoes) == len(TRADICOES):
            a, b = duracoes['catolico'], duracoes['evangelico']
            if abs(a - b) > FOLGA_ENTRE_VERSOES:
                problemas.append(f'{rotulo}: as versões têm {_casas(a)} s (católica) e {_casas(b)} s '
                                 f'(evangélica) — diferem {_casas(abs(a - b))} s; o máximo é '
                                 f'{_casas(FOLGA_ENTRE_VERSOES)} s')

        capa = pasta / f'{nn}.webp'
        if not capa.exists():
            problemas.append(f'{rotulo}: falta {capa.name}')
        else:
            medida = sondar(capa)
            if medida is None or medida['codec'] != 'webp':
                problemas.append(f'{rotulo} ({capa.name}): não é uma imagem WebP')
            elif (medida['largura'], medida['altura']) != TAMANHO_DA_CAPA:
                problemas.append(f'{rotulo} ({capa.name}): {medida["largura"]}x{medida["altura"]} — '
                                 f'tem de ser {TAMANHO_DA_CAPA[0]}x{TAMANHO_DA_CAPA[1]}')

        legenda = pasta / f'{nn}.srt'
        if legenda.exists():
            try:
                texto = legenda.read_bytes().decode('utf-8')
            except UnicodeDecodeError:
                problemas.append(f'{rotulo} ({legenda.name}): não está em UTF-8')
            else:
                problemas += [f'{rotulo} ({legenda.name}): {p}' for p in
                              conferir_legenda(texto, min(duracoes.values()) if duracoes else None)]
        else:
            legenda = None
        lista.append(CapituloDaEntrega(n=i, dados=cap, videos=videos, capa=capa, legenda=legenda))

    for arquivo_da_pasta in sorted(pasta.iterdir()):
        m = _ARQUIVO_DA_ENTREGA.fullmatch(arquivo_da_pasta.name)
        if m and not 1 <= int(m.group(1)) <= len(capitulos):
            problemas.append(f'sobra {arquivo_da_pasta.name}: a temporada tem {len(capitulos)} '
                             'capítulo(s)')
    if not (id_ok and inicio is not None and len(lista) == len(capitulos)):
        return None, problemas
    return Entrega(pasta=pasta, id=id_, titulo=titulo.strip() if isinstance(titulo, str) else '',
                   inicio=inicio, capitulos=lista), problemas


# ---------------------------------------------------------------------------
# O índice (novela/temporadas.json) e a base dos vídeos
# ---------------------------------------------------------------------------

def ler_indice(midia):
    """(o índice existente ou None, [problemas]) — conferido como o app o lê
    (IndiceDeTemporadas.fromJson): um índice quebrado não é regravado por
    cima em silêncio."""
    caminho = Path(midia) / 'novela' / 'temporadas.json'
    if not caminho.exists():
        return None, []
    try:
        dados = json.loads(caminho.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeDecodeError) as e:
        return None, [f'{caminho}: não é um JSON válido ({e}) — conserte antes de publicar']
    if not isinstance(dados, dict) or not isinstance(dados.get('temporadas'), list):
        return None, [f'{caminho}: sem a lista "temporadas" — conserte antes de publicar']
    problemas = []
    for r in dados['temporadas']:
        if not isinstance(r, dict):
            problemas.append(f'{caminho}: uma temporada não é um objeto')
            continue
        id_, capitulos = r.get('id'), r.get('capitulos')
        inicio, fim = data_valida(r.get('inicio')), data_valida(r.get('fim'))
        if (not isinstance(id_, str) or not ID_DE_TEMPORADA.fullmatch(id_)
                or r.get('arquivo') != f'novela/{id_}.json'
                or not isinstance(capitulos, int) or isinstance(capitulos, bool) or capitulos < 1
                or inicio is None or fim is None
                or fim != inicio + timedelta(days=capitulos - 1)):
            problemas.append(f'{caminho}: a temporada "{id_}" está fora do formato do app — '
                             'conserte antes de publicar')
    return (None if problemas else dados), problemas


def conferir_sobreposicao(indice, entrega):
    """A temporada nova não pode cair nos dias de outra (o app recusaria o
    índice inteiro); a de mesmo id é a versão anterior dela."""
    problemas = []
    for r in indice['temporadas']:
        if r['id'] == entrega.id:
            continue
        inicio, fim = data_valida(r['inicio']), data_valida(r['fim'])
        if not (entrega.inicio > fim or entrega.fim < inicio):
            problemas.append(f'as datas de {entrega.id} ({entrega.inicio} a {entrega.fim}) '
                             f'sobrepõem a temporada {r["id"]} ({inicio} a {fim}) do índice '
                             'existente')
    return problemas


def normalizar_prefixo(prefixo):
    """'teste/midia' -> 'teste/midia/'; '' fica ''."""
    prefixo = (prefixo or '').strip().strip('/')
    return prefixo + '/' if prefixo else ''


@dataclass(frozen=True, repr=False)
class ChavesR2:
    """As chaves do R2 — só dentro do processo. repr/str nunca as mostram."""
    endpoint: str
    access_key_id: str
    secret_access_key: str
    url_publica: str | None

    def __repr__(self):
        return 'ChavesR2(<valores ocultos>)'

    __str__ = __repr__


def _valor_depois_do_rotulo(linhas, rotulo):
    for i, linha in enumerate(linhas):
        if linha.strip().lower() == rotulo.lower():
            for seguinte in linhas[i + 1:]:
                valor = seguinte.strip()
                if not valor or valor.lower() == 'click to copy':
                    continue
                return valor if re.fullmatch(r'[A-Za-z0-9]+', valor) else None
            return None
    return None


def url_publica_de(texto):
    """A "Public Development URL" (na mesma linha do rótulo ou logo abaixo),
    sem a barra final; ou None."""
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        if 'public development url' in linha.lower():
            for candidata in [linha] + linhas[i + 1:i + 3]:
                m = re.search(r'https://\S+', candidata)
                if m:
                    return m.group(0).rstrip('/')
            return None
    return None


def ler_chaves_r2(caminho):
    """As chaves do arquivo do Gregory, pelos rótulos (o valor na linha
    seguinte). OSError se o arquivo não existe; ValueError, dizendo só o
    RÓTULO que faltou, se ele não tem o que precisa."""
    caminho = Path(caminho)
    texto = caminho.read_text(encoding='utf-8-sig')
    linhas = texto.splitlines()
    acesso = _valor_depois_do_rotulo(linhas, 'Access Key ID')
    segredo = _valor_depois_do_rotulo(linhas, 'Secret Access Key')
    endpoint = re.search(r'https://[A-Za-z0-9]+\.r2\.cloudflarestorage\.com', texto)
    faltam = [rotulo for rotulo, valor in (('Access Key ID', acesso), ('Secret Access Key', segredo),
                                           ('a URL https://<conta>.r2.cloudflarestorage.com',
                                            endpoint)) if not valor]
    if faltam:
        raise ValueError(f'{caminho.name}: não achei {", ".join(faltam)} (o rótulo numa linha, o '
                         'valor na seguinte)')
    return ChavesR2(endpoint=endpoint.group(0), access_key_id=acesso, secret_access_key=segredo,
                    url_publica=url_publica_de(texto))


def resolver_base(videos_base, indice, arquivo_de_chaves, prefixo):
    """(a base `videos` terminada em /, [problemas]): --videos-base, senão a
    do índice existente, senão a Public Development URL do arquivo de chaves
    mais o prefixo. Uma base que não termina no prefixo do R2 mandaria o app
    pedir os vídeos fora de onde eles sobem."""
    if videos_base:
        base, origem = videos_base, '--videos-base'
    elif indice and indice.get('videos'):
        base, origem = indice['videos'], 'o índice existente'
    else:
        try:
            publica = url_publica_de(Path(arquivo_de_chaves).read_text(encoding='utf-8-sig'))
        except OSError:
            return None, [f'sem a base "videos": não veio --videos-base, o índice ainda não '
                          f'existe e o arquivo de chaves do R2 não foi encontrado ({arquivo_de_chaves})']
        if not publica:
            return None, [f'sem a base "videos": não veio --videos-base, o índice ainda não '
                          f'existe e {Path(arquivo_de_chaves).name} não tem a "Public Development URL"']
        base, origem = f'{publica}/{prefixo}', 'a Public Development URL do R2'
    if not base.endswith('/'):
        base += '/'
    partes = urlparse(base)
    if partes.scheme not in ('http', 'https') or not partes.netloc:
        return None, [f'a base "videos" ({base}, de {origem}) não é uma URL http(s)']
    if prefixo and not partes.path.endswith('/' + prefixo):
        return None, [f'a base "videos" ({base}, de {origem}) não termina no prefixo do R2 '
                      f'({prefixo}): o app pediria os vídeos fora de onde eles sobem']
    return base, []


def conferir_raiz_da_simulacao(midia):
    """--simular escreve de verdade (JSONs, capas, legendas): exige --midia
    numa pasta temporária, nunca o repositório real nem uma pasta dentro
    dele — um gerar_manifesto depois levaria a temporada simulada ao app.
    Roda antes de qualquer outra conferência e de qualquer escrita."""
    if not midia:
        sys.exit('--simular exige --midia apontando uma pasta temporária: a simulação escreve '
                 'os JSONs, as capas e as legendas de verdade, e nunca no repositório real')
    if _dentro_de(midia, MIDIA_PADRAO):
        sys.exit(f'--simular com --midia no repositório real ({MIDIA_PADRAO}): aponte uma pasta '
                 'temporária fora dele — a simulação escreve os JSONs, as capas e as legendas')


def _dentro_de(pasta, raiz):
    a = os.path.normcase(str(Path(pasta).resolve()))
    b = os.path.normcase(str(Path(raiz).resolve()))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


# ---------------------------------------------------------------------------
# O caminho real: R2, Dart e a voz (os pontos que os testes trocam por dublês)
# ---------------------------------------------------------------------------

def rodar(cmd, cwd=None):
    """Roda um comando com a saída direto no terminal; devolve o código."""
    sys.stdout.flush()
    return subprocess.run([str(c) for c in cmd],
                          cwd=None if cwd is None else str(cwd)).returncode


def criar_cliente_r2(chaves):
    import boto3  # noqa: PLC0415 — só no caminho real
    return boto3.client(service_name='s3', endpoint_url=chaves.endpoint,
                        aws_access_key_id=chaves.access_key_id,
                        aws_secret_access_key=chaves.secret_access_key,
                        region_name='auto')


def localizar_dart():
    for candidato in (os.environ.get('DART'), shutil.which('dart'), str(DART_PADRAO)):
        if candidato and Path(candidato).exists():
            return candidato
    return None


def _nao_existe(erro):
    resposta = getattr(erro, 'response', None) or {}
    return str((resposta.get('Error') or {}).get('Code', '')) in ('404', 'NoSuchKey', 'NotFound')


def _cabeca(cliente, balde, chave):
    try:
        return cliente.head_object(Bucket=balde, Key=chave)
    except Exception as e:  # noqa: BLE001 — o 404 é resposta, o resto sobe
        if _nao_existe(e):
            return None
        raise


def subir_videos(cliente, envios, balde=BALDE):
    """`envios`: [(chave, arquivo, bytes, sha256)]. Pula o que já está no
    balde com o mesmo tamanho e o mesmo sha256 nos metadados; o que sobe é
    conferido do mesmo jeito depois. Devolve [(chave, bytes, 'subiu' ou
    'já estava')]."""
    resultado = []
    for chave, arquivo, tamanho, sha in envios:
        cabeca = _cabeca(cliente, balde, chave)
        if (cabeca and cabeca.get('ContentLength') == tamanho
                and (cabeca.get('Metadata') or {}).get('sha256') == sha):
            resultado.append((chave, tamanho, 'já estava'))
            continue
        cliente.upload_file(str(arquivo), balde, chave,
                            ExtraArgs={'ContentType': 'video/mp4', 'Metadata': {'sha256': sha}})
        conferida = _cabeca(cliente, balde, chave)
        if (not conferida or conferida.get('ContentLength') != tamanho
                or (conferida.get('Metadata') or {}).get('sha256') != sha):
            raise RuntimeError(f'{chave}: depois do envio, o R2 não mostra o mesmo tamanho e sha256')
        resultado.append((chave, tamanho, 'subiu'))
    return resultado


def conferir_o_caminho_real(args, midia, app):
    """(chaves, dart, [problemas]) do que o caminho real precisa — antes de
    qualquer envio ou escrita."""
    problemas = []
    chaves = None
    try:
        chaves = ler_chaves_r2(args.r2)
    except OSError:
        problemas.append(f'arquivo de chaves do R2 não encontrado: {args.r2} (--r2)')
    except ValueError as e:
        problemas.append(str(e))
    try:
        import boto3  # noqa: F401, PLC0415
    except ImportError:
        problemas.append('o boto3 não está instalado (pip install boto3)')
    dart = localizar_dart()
    if dart is None:
        problemas.append(f'dart não encontrado (no PATH, em DART ou em {DART_PADRAO})')
    ferramentas_do_app = ['pubspec.yaml', 'tool/midia/gerar_manifesto.dart', 'tool/lint_conteudo.dart']
    if not args.sem_voz:
        ferramentas_do_app.append('tool/midia/texto_narrado.dart')
    for relativo in ferramentas_do_app:
        if not (app / relativo).exists():
            problemas.append(f'o app em {app} não tem {relativo} (aponte com --app)')
    if not args.sem_voz:
        for script in ('narrar.py', 'conferir_stt.py'):
            if not (midia / 'ferramentas' / script).exists():
                problemas.append(f'a voz roda {midia / "ferramentas" / script}, que grava na raiz '
                                 'de mídia em que está: copie o repositório de mídia inteiro para '
                                 '--midia, ou use --sem-voz')
    return chaves, dart, problemas


# ---------------------------------------------------------------------------
# A escrita
# ---------------------------------------------------------------------------

def sha256_de(arquivo):
    h = hashlib.sha256()
    with open(arquivo, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()


def escrever_json(caminho, dados):
    """UTF-8 sem BOM, indentação de 2 espaços, LF, por um .parte."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    parcial = caminho.with_name(caminho.name + '.parte')
    with open(parcial, 'w', encoding='utf-8', newline='') as f:
        f.write(json.dumps(dados, ensure_ascii=False, indent=2) + '\n')
    parcial.replace(caminho)


def chave_do_video(entrega, capitulo, tradicao):
    """A chave de mídia do vídeo (o `arquivo` do JSON; no R2, com o prefixo)."""
    return f'video/{entrega.id}/{capitulo.nn}-{tradicao}.mp4'


def temporada_no_formato_do_app(entrega, medidos):
    """O <t>.json que Temporada.fromJson lê. `medidos`: {(n, tradição):
    (bytes, sha256)}."""
    capitulos = []
    for c in entrega.capitulos:
        id_ = entrega.id_do_capitulo(c)
        saida = {'id': id_, 'n': c.n, 'data': c.dados['data']}
        for campo in (*CAMPOS_DE_TEXTO, 'duracaoS'):
            saida[campo] = c.dados[campo]
        saida['capa'] = f'assets/images/cartoes/{id_}.webp'
        if c.legenda is not None:
            saida['legenda'] = f'novela/{id_}.srt'
        saida['video'] = {t: {'arquivo': chave_do_video(entrega, c, t),
                              'bytes': medidos[c.n, t][0], 'sha256': medidos[c.n, t][1]}
                          for t in TRADICOES}
        capitulos.append(saida)
    return {'id': entrega.id, 'titulo': entrega.titulo, 'inicio': entrega.inicio.isoformat(),
            'capitulos': capitulos}


def indice_atualizado(indice, entrega, base):
    """O temporadas.json com esta temporada (no lugar da versão anterior
    dela, se houver), as outras como estavam, tudo em ordem de início."""
    outras = [r for r in (indice or {}).get('temporadas', []) if r['id'] != entrega.id]
    nova = {'id': entrega.id, 'titulo': entrega.titulo, 'inicio': entrega.inicio.isoformat(),
            'fim': entrega.fim.isoformat(), 'capitulos': len(entrega.capitulos),
            'arquivo': f'novela/{entrega.id}.json'}
    return {'versao': 1, 'videos': base,
            'temporadas': sorted(outras + [nova], key=lambda r: r['inicio'])}


_DO_CAPITULO = re.compile(r'(t\d+)c(\d+)\.(webp|srt|m4a)')


def limpar_sobras(midia, entrega):
    """Apaga o que uma versão anterior DESTA temporada deixou e a nova não
    tem: capa e voz de capítulo que sumiu, legenda que saiu. Nada de outra
    temporada nem de outro conteúdo é tocado."""
    com_legenda = {c.n for c in entrega.capitulos if c.legenda is not None}
    total = len(entrega.capitulos)
    candidatos = [*(midia / 'imagens').glob(f'{entrega.id}c*.webp'),
                  *(midia / 'novela').glob(f'{entrega.id}c*.srt'),
                  *(p for t in TRADICOES for p in (midia / 'narracao' / t).glob(f'{entrega.id}c*.m4a'))]
    removidos = []
    for caminho in sorted(candidatos):
        m = _DO_CAPITULO.fullmatch(caminho.name)
        if not m or m.group(1) != entrega.id:
            continue
        n = int(m.group(2))
        fica = n in com_legenda if m.group(3) == 'srt' else 1 <= n <= total
        if not fica:
            caminho.unlink()
            removidos.append(caminho.relative_to(midia).as_posix())
    return removidos


def escrever(midia, entrega, medidos, base, indice):
    """Os JSONs, as capas e as legendas; o índice por último. Devolve os
    caminhos escritos e os removidos (relativos a `midia`)."""
    escritos = []
    escrever_json(midia / 'novela' / f'{entrega.id}.json',
                  temporada_no_formato_do_app(entrega, medidos))
    escritos.append(f'novela/{entrega.id}.json')
    for c in entrega.capitulos:
        id_ = entrega.id_do_capitulo(c)
        destino = midia / 'imagens' / f'{id_}.webp'
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(c.capa, destino)
        escritos.append(f'imagens/{id_}.webp')
        if c.legenda is not None:
            bruto = c.legenda.read_bytes()
            if bruto.startswith(b'\xef\xbb\xbf'):
                bruto = bruto[3:]
            (midia / 'novela' / f'{id_}.srt').write_bytes(bruto)
            escritos.append(f'novela/{id_}.srt')
    removidos = limpar_sobras(midia, entrega)
    escrever_json(midia / 'novela' / 'temporadas.json', indice_atualizado(indice, entrega, base))
    escritos.append('novela/temporadas.json')
    return escritos, removidos


# ---------------------------------------------------------------------------
# Voz, manifesto e lint
# ---------------------------------------------------------------------------

def comandos_da_voz(dart, midia, app, ids, motor):
    return [
        ([dart, 'run', 'tool/midia/texto_narrado.dart',
          f'--saida={midia / "ferramentas" / "narracao" / "narracoes.jsonl"}',
          f'--temporadas={midia / "novela"}', str(app)], app),
        ([sys.executable, str(midia / 'ferramentas' / 'narrar.py'), '--motor', motor,
          '--ids', ','.join(ids), '--refazer'], midia),
        ([sys.executable, str(midia / 'ferramentas' / 'conferir_stt.py'), '--stt', 'whisper',
          '--ids', ','.join(ids)], midia),
    ]


def comandos_do_manifesto(dart, midia, app):
    return [([dart, 'run', 'tool/midia/gerar_manifesto.dart', str(midia)], app),
            ([dart, 'run', 'tool/lint_conteudo.dart', f'--manifesto={midia / "manifesto.json"}'], app)]


def _caminhos_da_voz(ids):
    return {f'narracao/{t}/{id_}.m4a' for id_ in ids for t in TRADICOES}


def gerar_voz(dart, midia, app, ids, motor):
    """texto_narrado -> narrar -> conferir_stt; None se tudo passou, senão a
    mensagem do que parou."""
    (texto, cwd_texto), (narrar, cwd_narrar), (stt, cwd_stt) = comandos_da_voz(
        dart, midia, app, ids, motor)
    if rodar(texto, cwd=cwd_texto) != 0:
        return ('o texto_narrado.dart falhou (a opção --temporadas é da Task 7 do app: o app '
                'apontado já a tem?)')
    jsonl = midia / 'ferramentas' / 'narracao' / 'narracoes.jsonl'
    emitidos = set()
    for linha in jsonl.read_text(encoding='utf-8').splitlines():
        if linha.strip():
            item = json.loads(linha)
            if item.get('id') in ids:
                emitidos.add(item.get('caminho'))
    faltam = sorted(_caminhos_da_voz(ids) - emitidos)
    if faltam:
        return (f'o texto_narrado.dart não emitiu a voz dos capítulos ({", ".join(faltam)}): a '
                'opção --temporadas é da Task 7 do app — o app apontado já a tem?')
    if rodar(narrar, cwd=cwd_narrar) != 0:
        return 'o narrar.py falhou (a saída está acima); nada do manifesto foi refeito'
    faltam = sorted(c for c in _caminhos_da_voz(ids)
                    if not (midia / c).exists() or (midia / c).stat().st_size == 0)
    if faltam:
        return f'o narrar.py não gravou {", ".join(faltam)}; nada do manifesto foi refeito'
    if rodar(stt, cwd=cwd_stt) != 0:
        reprovados = _reprovados_no_log(midia, ids)
        lista = f': {", ".join(reprovados)}' if reprovados else ' (a lista está acima)'
        return (f'a conferência por STT reprovou a voz{lista} — refaça com narrar.py --ids '
                f'{",".join(ids)} --refazer e publique de novo; nada do manifesto foi refeito')
    return None


def _reprovados_no_log(midia, ids):
    log = midia / 'ferramentas' / 'narracao' / 'stt.log.jsonl'
    if not log.exists():
        return []
    ultimo = {}
    for linha in log.read_text(encoding='utf-8').splitlines():
        if linha.strip():
            r = json.loads(linha)
            if r.get('caminho') in _caminhos_da_voz(ids):
                ultimo[r['caminho']] = r
    return sorted(c for c, r in ultimo.items() if not r.get('aprovado'))


# ---------------------------------------------------------------------------

def _console_tolerante():
    """Título e texto da entrega vão ao terminal: um caractere fora da
    página de código do Windows não pode derrubar a publicação."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass


def _argumentos(argv):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('entrega', help='a pasta da entrega (temporada.json, NN-*.mp4, NN.webp, NN.srt)')
    ap.add_argument('--midia', help='raiz de mídia (padrão: este repositório; com --simular é '
                                    'obrigatória e tem de ser uma pasta temporária)')
    ap.add_argument('--app', help='raiz do repo manha-de-fe-app (padrão: pasta-irmã, ou '
                                  'MANHA_DE_FE_APP)')
    ap.add_argument('--r2', default=str(CHAVES_R2_PADRAO), help='o arquivo das chaves do R2')
    ap.add_argument('--r2-prefixo', default='',
                    help='prefixo das chaves no balde (teste/midia/ num ensaio)')
    ap.add_argument('--videos-base', help='a base "videos" do índice (padrão: a do índice '
                                          'existente, senão a Public Development URL + prefixo)')
    ap.add_argument('--motor', choices=MOTORES, default='microsoft',
                    help='a voz dos cartões dos capítulos (padrão: microsoft, a fase atual)')
    ap.add_argument('--sem-voz', action='store_true', help='não gera a voz dos capítulos')
    ap.add_argument('--simular', action='store_true',
                    help='escreve só os JSONs, as capas e as legendas em --midia (temporária); '
                         'não sobe, não gera voz, não roda o Dart')
    return ap.parse_args(argv)


def _mostrar(cmd, cwd):
    texto = ' '.join(f'"{c}"' if ' ' in str(c) else str(c) for c in cmd)
    return f'    {texto}    (em {cwd})'


def main(argv=None):
    _console_tolerante()
    args = _argumentos(argv)
    # Antes de tudo: a simulação nunca escreve no repositório real.
    if args.simular:
        conferir_raiz_da_simulacao(args.midia)
    midia = Path(args.midia).absolute() if args.midia else MIDIA_PADRAO
    app = Path(args.app).absolute() if args.app else APP_PADRAO
    prefixo = normalizar_prefixo(args.r2_prefixo)

    # 1. Conferência: tudo, antes de qualquer envio ou escrita.
    entrega, problemas = conferir_entrega(Path(args.entrega))
    indice, p = ler_indice(midia)
    problemas += p
    if entrega is not None and indice is not None:
        problemas += conferir_sobreposicao(indice, entrega)
    base, p = resolver_base(args.videos_base, indice, args.r2, prefixo)
    problemas += p
    chaves = dart = None
    if not args.simular:
        chaves, dart, p = conferir_o_caminho_real(args, midia, app)
        problemas += p
    if problemas:
        print(f'conferência: {len(problemas)} problema(s) — nada foi enviado nem escrito:')
        for problema in problemas:
            print(f'  - {problema}')
        return 1
    ids = [entrega.id_do_capitulo(c) for c in entrega.capitulos]
    print(f'conferência ok: {entrega.id}, {len(ids)} capítulo(s), de {entrega.inicio} a {entrega.fim}')

    # 2. Os vídeos medidos e o R2 (primeiro: nenhum JSON local aponta para um
    #    vídeo que não subiu).
    medidos, envios = {}, []
    for c in entrega.capitulos:
        for t in TRADICOES:
            tamanho, sha = c.videos[t].stat().st_size, sha256_de(c.videos[t])
            medidos[c.n, t] = (tamanho, sha)
            envios.append((prefixo + chave_do_video(entrega, c, t), c.videos[t], tamanho, sha))
    if args.simular:
        print(f'R2 (simulado): subiria ao balde {BALDE}:')
        for chave, _, tamanho, sha in envios:
            print(f'    {chave}  {_milhar(tamanho)} bytes  sha256 {sha}')
        enviados = [(chave, tamanho, 'simulado: não subiu') for chave, _, tamanho, _ in envios]
    else:
        try:
            enviados = subir_videos(criar_cliente_r2(chaves), envios)
        except Exception as e:  # noqa: BLE001
            print(f'R2: o envio falhou ({type(e).__name__}: {str(e)[:300]}); nada foi escrito — '
                  'rode de novo (o que já subiu com o mesmo sha256 não sobe outra vez)')
            return 1

    # 3. Os JSONs, as capas e as legendas.
    escritos, removidos = escrever(midia, entrega, medidos, base, indice)

    # 4. Voz, manifesto e lint.
    if args.simular:
        if args.sem_voz:
            print('voz (simulado): pulada (--sem-voz)')
        else:
            print('voz (simulado): rodaria')
            for cmd, cwd in comandos_da_voz('dart', midia, app, ids, args.motor):
                print(_mostrar(cmd, cwd))
        print('manifesto e lint (simulado): rodaria')
        for cmd, cwd in comandos_do_manifesto('dart', midia, app):
            print(_mostrar(cmd, cwd))
    else:
        if not args.sem_voz:
            falha = gerar_voz(dart, midia, app, ids, args.motor)
            if falha:
                print(f'voz: {falha}')
                return 1
        (manifesto, cwd_manifesto), (lint, cwd_lint) = comandos_do_manifesto(dart, midia, app)
        if rodar(manifesto, cwd=cwd_manifesto) != 0:
            print('manifesto: o gerar_manifesto.dart falhou (a saída está acima)')
            return 1
        if rodar(lint, cwd=cwd_lint) != 0:
            print('lint: o lint_conteudo.dart achou erro (a saída está acima) — corrija e publique '
                  'de novo; nada foi commitado')
            return 1

    # 5. O resumo.
    print()
    print(f'== resumo{" (SIMULADO)" if args.simular else ""} ==')
    print(f'temporada {entrega.id} ("{entrega.titulo}"): {len(ids)} capítulo(s), de '
          f'{entrega.inicio} a {entrega.fim}')
    for c in entrega.capitulos:
        videos = '  '.join(f'{c.nn}-{t}.mp4 {_milhar(medidos[c.n, t][0])} bytes' for t in TRADICOES)
        print(f'  {entrega.id_do_capitulo(c)}  {c.dados["data"]}  {videos}  '
              f'legenda: {"sim" if c.legenda else "não"}')
    print(f'R2 (balde {BALDE}):')
    for chave, tamanho, estado in enviados:
        print(f'  {chave}  {_milhar(tamanho)} bytes  {estado}')
    print(f'base "videos": {base}')
    if indice and indice.get('videos') and indice['videos'] != base:
        print(f'  (era {indice["videos"]}: o vídeo que já está no aparelho não baixa de novo — o '
              'app o reconhece pelo sha256)')
    print(f'escrito em {midia}: {", ".join(escritos)}')
    if removidos:
        print(f'removido (sobra da versão anterior): {", ".join(removidos)}')
    if args.simular:
        print('voz, manifesto e lint: não rodaram (simulado)')
    else:
        voz = 'pulada (--sem-voz)' if args.sem_voz else f'{args.motor}, {len(ids) * 2} arquivos, STT ok'
        print(f'voz: {voz}; manifesto refeito; lint sem erro')
    print('lembrete: commit por caminho (git add -- <novos>; git commit -- <caminhos>) + push SÓ '
          'com OK do Gregory.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
