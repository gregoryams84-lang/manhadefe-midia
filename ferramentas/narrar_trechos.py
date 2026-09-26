#!/usr/bin/env python3
"""Áudios guiados do Manhã de Fé: o Terço (28 arquivos) e as orações
guiadas (9 + 4). Dois destinos, desde a decisão do Gregory de 25/09/2026:

  <este repo>/terco/<misterio>-<trecho>.m4a                      (4 × 7)  BAIXÁVEL
  manha-de-fe-app/assets/audio/oracoes/<slug>.m4a                (9)      embutido
  manha-de-fe-app/assets/audio/oracoes/<slug>-evangelico.m4a     (4, ver abaixo)

O Terço saiu do bundle: os 28 trechos (~92 min, ~22 MB a 32 kbps) levariam o
app de 24 para 46 MB, e o perfil evangélico carregaria um áudio que nunca
abre. É camada católica, como o santo do dia — gravado na pasta terco/ deste
repo e publicado pelo servidor de mídia; depois de gerar, no repo do app:
`dart run tool/midia/gerar_manifesto.dart ../manhadefe-midia` (os 28 entram
no manifesto) e commit + push aqui. --midia aponta outra raiz (os testes usam
um temporário). As nove orações continuam embutidas no app.

E — a parte que mais importa — grava de volta as `marcas` reais nos JSONs de
assets/content/terco/*.json e assets/content/oracoes/*.json. A tela do Terço
(GuiaDeAudio + ContasDoTerco) acende uma conta quando a posição do áudio
passa por cada marca; a oração guiada acende um passo. Hoje as marcas são
chute; com o áudio real, as contas acenderiam fora de hora.

Como a marca é exata por construção: cada PEÇA (um passo de oração, uma
Ave-Maria inteira vale duas peças, o Glória vale uma) vira um arquivo
próprio, medido com ffprobe; entre as peças entra um silêncio de duração
controlada (ffmpeg anullsrc); tudo é concatenado pelo demuxer concat numa
única passada de codificação. A marca de uma conta é a soma das durações e
dos silêncios anteriores a ela — medida, nunca estimada. As peças ficam num
diretório de trabalho (--trabalho) para refazer só uma depois.

Reaproveitamento (--sem-reaproveitar desliga): uma peça é identificada por
(voz, texto). A Ave-Maria aparece 53 vezes em cada Terço; gerar 212 vezes o
mesmo texto custaria ~46 mil caracteres na ElevenLabs — reaproveitando, o
Terço inteiro custa menos de 7 mil. Quem preferir cada Ave-Maria com a sua
própria entonação usa --sem-reaproveitar e paga a diferença; --so-contar
mostra os dois números.

PENDÊNCIA (decisão do Gregory): salmo-23, oracao-da-manha, oracao-da-noite e
oracao-de-entrega são comuns às duas tradições (indice.json), mas o JSON só
tem UM `audioAsset`. Esta ferramenta gera as quatro nas DUAS vozes — a
católica em <slug>.m4a (a que o JSON cita) e a evangélica em
<slug>-evangelico.m4a. O segundo arquivo ainda não é usado por código nenhum;
existe para a decisão de "ouvir a voz da própria tradição" não custar uma
rodada nova de geração. As marcas dele ficam só no log (narrar_trechos.log.jsonl)
e nos metadados do diretório de trabalho — quando o app ganhar um segundo
`audioAsset`, é só reconstruir (sem chamar a API) e gravar.

O texto do Terço não existe pronto em lugar nenhum: é composto aqui. As
orações fixas (Pai-Nosso, Ave-Maria, Creio, Salve-Rainha) saem dos JSONs de
assets/content/oracoes/ — uma versão só de cada texto no projeto. O que não
existe lá (Sinal da Cruz, Glória, a jaculatória de Fátima, o anúncio do
mistério e a oração final do fecho) está nas constantes logo abaixo, PARA
REVISÃO HUMANA (as quatro primeiras aprovadas pelo Gregory em 25/09/2026).
C13, 25/09/2026: jaculatória de Fátima após cada Glória e Sinal da Cruz no
fecho, peças sem conta.

Modo --simular: sem chave e sem rede, cada peça vira um silêncio com duração
proporcional ao texto (CARACTERES_POR_SEGUNDO). Todo o resto — ffprobe,
ffmpeg, concat, marcas, gravação nos JSONs — roda de verdade. Só a fonte do
áudio muda. Serve para provar o caminho antes de gastar caractere.

Voz, chave, chamada da API, codec e log vêm de narrar.py (mesma pasta).

Uso:
  python ferramentas/narrar_trechos.py --so-contar
  python ferramentas/narrar_trechos.py --mostrar gozosos-dezena-1      # o texto, peça a peça
  python ferramentas/narrar_trechos.py --simular                       # prova ponta a ponta
  python ferramentas/narrar_trechos.py                                 # tudo o que falta
  python ferramentas/narrar_trechos.py --ids gozosos-dezena-1 --refazer
  python ferramentas/narrar_trechos.py --ids gozosos-dezena-1 --refazer --passos 3
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from narrar import (  # noqa: E402
    PARAMETROS_AAC, RAIZ, VOZES, chave_api, duracao_segundos, registrar,
    saldo, sintetizar)

# O repo do app: a pasta-irmã deste, ou onde MANHA_DE_FE_APP apontar (clone
# isolado, outra máquina); --app manda por cima dos dois.
APP_PADRAO = (Path(os.environ['MANHA_DE_FE_APP']) if os.environ.get('MANHA_DE_FE_APP')
              else RAIZ.parent / 'manha-de-fe-app')
# Onde o Terço é gravado (terco/ na raiz do repo de mídia); --midia manda por
# cima — os testes apontam um temporário para nunca escrever no repo real.
MIDIA_PADRAO = RAIZ
PASTA_DO_TERCO = 'terco'
TRABALHO_PADRAO = RAIZ / 'ferramentas' / 'narracao' / 'trechos'
# Peças simuladas nunca se misturam com as reais: outro diretório.
TRABALHO_SIMULADO = RAIZ / 'ferramentas' / 'narracao' / 'trechos-simulado'
LOG = RAIZ / 'ferramentas' / 'narracao' / 'narrar_trechos.log.jsonl'
TAXA = 44100  # a mesma dos .m4a de narrar.py; peças e silêncios em PCM nesta taxa

# ---------------------------------------------------------------------------
# Pausas: silêncio REAL inserido pelo ffmpeg entre as peças (segundos). Não
# são tags <break> — a marca precisa da duração exata, e a tag é a voz quem
# interpreta. Ajustar aqui muda o ritmo de tudo; as marcas acompanham.
# ---------------------------------------------------------------------------
PAUSA_ENTRE_PASSOS = 0.8     # entre passos de uma mesma oração (e entre as duas metades da Ave-Maria)
PAUSA_ENTRE_CONTAS = 1.4     # entre uma oração e a seguinte (Ave-Maria → Ave-Maria, Pai-Nosso → Ave-Maria, → Glória)
PAUSA_APOS_MEDITACAO = 2.0   # depois da meditação do mistério, antes do Pai-Nosso: um instante para guardar

# --simular: ritmo de fala plausível. As vozes aprovadas rodam a ~120 palavras
# por minuto (docs/fase4/narracao-parametros.md); em português dá por volta
# de 13 caracteres por segundo, contando os espaços.
CARACTERES_POR_SEGUNDO = 13.0
DURACAO_MINIMA_SIMULADA = 0.6

# ---------------------------------------------------------------------------
# TEXTO LITÚRGICO QUE NÃO EXISTE EM assets/content/oracoes/ — PARA REVISÃO
# HUMANA (molde brasileiro corrente). Tudo o mais (Pai-Nosso, Ave-Maria,
# Creio, Salve-Rainha) é lido dos JSONs do app, passo a passo.
# ---------------------------------------------------------------------------
SINAL_DA_CRUZ = 'Em nome do Pai, e do Filho, e do Espírito Santo. Amém.'
GLORIA = ('Glória ao Pai, e ao Filho, e ao Espírito Santo. '
          'Como era no princípio, agora e sempre. Amém.')
# A jaculatória de Fátima ("Ó meu Jesus"), rezada depois de CADA Glória —
# na abertura e nas cinco dezenas (C13, decisão do Gregory em 25/09/2026).
# Sem conta, como o Glória: o texto é o do costume brasileiro corrente.
JACULATORIA_DE_FATIMA = ('Ó meu Jesus, perdoai-nos, livrai-nos do fogo do inferno, '
                         'levai as almas todas para o céu e socorrei principalmente '
                         'as que mais precisarem.')
# A oração final do Rosário, depois da Salve-Rainha (o "Rogai por nós" já é
# o terceiro passo de salve-rainha.json).
ORACAO_FINAL = ('Ó Deus, cujo Filho Unigênito, por sua vida, morte e '
                'ressurreição, nos alcançou os prêmios da salvação eterna: '
                'concedei-nos, nós vos rogamos, que, venerando estes '
                'mistérios do Santíssimo Rosário da bem-aventurada Virgem '
                'Maria, imitemos o que eles contêm e alcancemos o que eles '
                'prometem. Pelo mesmo Cristo, Senhor nosso. Amém.')
# O anúncio de cada dezena: "Primeiro mistério gozoso: A anunciação do anjo
# a Maria." — o `titulo` vem do JSON, sem retoque; a meditação vem em seguida
# como peça própria.
ANUNCIO = '{ordinal} mistério {adjetivo}: {titulo}.'
ORDINAIS = ['Primeiro', 'Segundo', 'Terceiro', 'Quarto', 'Quinto']
ADJETIVO = {'gozosos': 'gozoso', 'dolorosos': 'doloroso',
            'gloriosos': 'glorioso', 'luminosos': 'luminoso'}

MISTERIOS = ['gozosos', 'dolorosos', 'gloriosos', 'luminosos']
TRECHOS_DO_TERCO = ['abertura', 'dezena-1', 'dezena-2', 'dezena-3',
                    'dezena-4', 'dezena-5', 'fecho']
# Espelho de Terco.marcasPorTrecho (lib/content/terco.dart): a tela desenha
# 60 contas = crucifixo + Pai-Nosso + 3 Ave-Marias (5) e 5 × (Pai-Nosso + 10
# Ave-Marias) (55). Glória e Salve-Rainha não têm conta. Se a composição
# daqui não bater com isto, a ferramenta para — nunca grava.
CONTAS_POR_TRECHO = {'abertura': 5, 'dezena-1': 11, 'dezena-2': 11,
                     'dezena-3': 11, 'dezena-4': 11, 'dezena-5': 11, 'fecho': 0}

# Qual voz reza cada camada de assets/content/oracoes/indice.json. A lista de
# orações NÃO é fixa aqui: vem do índice, para uma oração nova entrar sozinha
# no catálogo — e um índice que não bate com a pasta parar a ferramenta, nunca
# ser ignorado em silêncio. As comuns saem nas duas vozes: a católica no
# arquivo que o JSON cita, a evangélica com o sufixo (pendência no topo).
VOZ_DA_CAMADA = {'catolico': 'catolico', 'evangelico': 'evangelico'}
CAMADA_COMUM = 'comum'
CAMADAS = ('catolico', 'evangelico', CAMADA_COMUM)  # as do lint do app (camadasDeOracoes)
SUFIXO_EVANGELICO = '-evangelico'


@dataclass(frozen=True)
class Peca:
    """Um pedaço falado. `conta` = esta peça começa uma conta/passo (ganha
    marca). `pausa_antes` = silêncio inserido antes dela (0 na primeira)."""
    texto: str
    conta: bool
    pausa_antes: float
    rotulo: str


@dataclass(frozen=True)
class Trecho:
    """Um arquivo final e como ele se monta. `json` + `posicao` dizem onde
    as marcas são gravadas: no terço, `posicao` é o índice do trecho em
    `trechos`; na oração é None (as marcas ficam na raiz); `json` None = as
    marcas não vão a lugar nenhum (só ao log) — a cópia evangélica das comuns.
    `arquivo` é o caminho como o app o conhece — a chave publicada do Terço
    (`terco/<misterio>-<trecho>.m4a`) ou o asset embutido da oração — e vai
    ao log; `destino` é onde ele fica no disco."""
    id: str
    destino: Path
    tradicao: str
    pecas: tuple
    contas_esperadas: int
    json: Path
    posicao: int
    arquivo: str = ''

    @property
    def contas(self):
        return sum(1 for p in self.pecas if p.conta)

    @property
    def caracteres(self):
        return sum(len(p.texto) for p in self.pecas)


# ---------------------------------------------------------------------------
# Composição
# ---------------------------------------------------------------------------

def ler_json(caminho):
    with open(caminho, encoding='utf-8') as f:
        return json.load(f)


def passos_da_oracao(app, slug):
    dados = ler_json(app / 'assets' / 'content' / 'oracoes' / f'{slug}.json')
    passos = [p['texto'] for p in dados['passos']]
    if not passos:
        sys.exit(f'{slug}.json sem passos')
    return passos


def pecas_de_oracao(passos, rotulo, pausa_antes, conta_na_primeira,
                    conta_em_todos=False):
    """Os passos de uma oração como peças. No Terço só o primeiro passo ganha
    conta (uma conta = uma oração inteira); na tela da oração guiada cada
    passo é um passo aceso (`conta_em_todos`)."""
    pecas = []
    for n, texto in enumerate(passos, 1):
        pecas.append(Peca(
            texto=texto,
            conta=conta_em_todos or (n == 1 and conta_na_primeira),
            pausa_antes=pausa_antes if n == 1 else PAUSA_ENTRE_PASSOS,
            rotulo=f'{rotulo} ({n}/{len(passos)})' if len(passos) > 1 else rotulo))
    return pecas


def compor_terco(app, misterio, midia=MIDIA_PADRAO):
    """Os 7 trechos de um conjunto de mistérios, na ordem em que se reza —
    gravados em <midia>/terco/ (baixáveis), com as marcas no JSON do app."""
    conteudo = app / 'assets' / 'content' / 'terco' / f'{misterio}.json'
    dados = ler_json(conteudo)
    if len(dados['misterios']) != 5:
        sys.exit(f'{conteudo.name}: esperados 5 mistérios, vieram {len(dados["misterios"])}')
    ids = [t['id'] for t in dados['trechos']]
    if ids != TRECHOS_DO_TERCO:
        sys.exit(f'{conteudo.name}: trechos {ids} — esperados {TRECHOS_DO_TERCO}')

    pai_nosso = passos_da_oracao(app, 'pai-nosso-catolico')
    ave_maria = passos_da_oracao(app, 'ave-maria')
    creio = passos_da_oracao(app, 'creio')
    salve_rainha = passos_da_oracao(app, 'salve-rainha')

    def ave_marias(quantas):
        pecas = []
        for i in range(1, quantas + 1):
            pecas += pecas_de_oracao(ave_maria, f'ave-maria {i}/{quantas}',
                                     PAUSA_ENTRE_CONTAS, conta_na_primeira=True)
        return pecas

    # Glória + jaculatória de Fátima (C13): as duas sem conta, e a
    # jaculatória com o MESMO silêncio antes dela que o Glória tem (o de
    # entre contas) — é a pausa que já havia entre a última Ave-Maria e o
    # Glória, agora também entre o Glória e o "Ó meu Jesus".
    gloria = [Peca(GLORIA, False, PAUSA_ENTRE_CONTAS, 'gloria'),
              Peca(JACULATORIA_DE_FATIMA, False, PAUSA_ENTRE_CONTAS, 'jaculatoria')]

    # abertura: crucifixo (Sinal da Cruz + Creio = UMA conta), Pai-Nosso,
    # três Ave-Marias, Glória e jaculatória (sem conta).
    abertura = (
        [Peca(SINAL_DA_CRUZ, True, 0.0, 'sinal-da-cruz')]
        + pecas_de_oracao(creio, 'creio', PAUSA_ENTRE_CONTAS, conta_na_primeira=False)
        + pecas_de_oracao(pai_nosso, 'pai-nosso', PAUSA_ENTRE_CONTAS, conta_na_primeira=True)
        + ave_marias(3)
        + gloria)

    trechos = [_trecho_do_terco(app, misterio, dados, 0, abertura, midia)]

    # dezena-N: anúncio (título + meditação, sem conta), Pai-Nosso, dez
    # Ave-Marias, Glória e jaculatória (sem conta). A primeira marca fica
    # DEPOIS do anúncio: a conta do Pai-Nosso acende quando o Pai-Nosso
    # começa, não no zero.
    for n in range(5):
        m = dados['misterios'][n]
        anuncio = ANUNCIO.format(ordinal=ORDINAIS[n], adjetivo=ADJETIVO[misterio],
                                 titulo=m['titulo'])
        dezena = (
            [Peca(anuncio, False, 0.0, f'anuncio {n + 1}'),
             Peca(m['meditacao'], False, PAUSA_ENTRE_PASSOS, f'meditacao {n + 1}')]
            + pecas_de_oracao(pai_nosso, 'pai-nosso', PAUSA_APOS_MEDITACAO, conta_na_primeira=True)
            + ave_marias(10)
            + gloria)
        trechos.append(_trecho_do_terco(app, misterio, dados, n + 1, dezena, midia))

    # fecho: Salve-Rainha, a oração final e o Sinal da Cruz (C13) — nenhuma
    # conta. O Sinal da Cruz é a MESMA peça da abertura (mesma voz, mesmo
    # texto: reaproveitada), só que aqui sem conta — a tela não assume nada
    # sobre a última peça do fecho, só espera o arquivo acabar.
    fecho = (pecas_de_oracao(salve_rainha, 'salve-rainha', 0.0, conta_na_primeira=False)
             + [Peca(ORACAO_FINAL, False, PAUSA_ENTRE_CONTAS, 'oracao-final'),
                Peca(SINAL_DA_CRUZ, False, PAUSA_ENTRE_CONTAS, 'sinal-da-cruz')])
    trechos.append(_trecho_do_terco(app, misterio, dados, 6, fecho, midia))
    return trechos


def _trecho_do_terco(app, misterio, dados, posicao, pecas, midia):
    id_trecho = TRECHOS_DO_TERCO[posicao]
    nome = f'{misterio}-{id_trecho}.m4a'
    # O audioAsset do JSON é a chave lógica (D2 do plano de 18/09 do app): o
    # prefixo assets/audio/terco/ é histórico, o NOME é o que vira
    # terco/<nome> no servidor — a regra 15 do lint do app prende a mesma
    # amarra; aqui a ferramenta para antes de gravar um áudio com nome errado.
    asset = dados['trechos'][posicao]['audioAsset']
    esperado = f'assets/audio/terco/{nome}'
    if asset != esperado:
        sys.exit(f'{misterio}.json/{id_trecho}: audioAsset "{asset}", esperado "{esperado}"')
    return Trecho(id=f'{misterio}-{id_trecho}', destino=Path(midia) / PASTA_DO_TERCO / nome,
                  tradicao='catolico',
                  pecas=tuple(pecas), contas_esperadas=CONTAS_POR_TRECHO[id_trecho],
                  json=app / 'assets' / 'content' / 'terco' / f'{misterio}.json',
                  posicao=posicao, arquivo=f'{PASTA_DO_TERCO}/{nome}')


def camadas_do_indice(pasta):
    """{slug: camada}, na ordem das CAMADAS, lido de indice.json e conferido
    contra a pasta: cada oração numa camada só, todo slug citado com arquivo,
    todo .json da pasta citado. Qualquer diferença para a ferramenta com a
    mensagem do que falta (regra 6 do briefing: parar, não inventar)."""
    indice = ler_json(pasta / 'indice.json')
    desconhecidas = sorted(set(indice) - {'topo', *CAMADAS})
    if desconhecidas:
        sys.exit(f'indice.json: camada(s) desconhecida(s) {desconhecidas}; só {list(CAMADAS)} (e "topo")')
    camada_de = {}
    for camada in CAMADAS:
        for slug in indice.get(camada, []):
            if slug in camada_de:
                sys.exit(f'indice.json: "{slug}" está em "{camada_de[slug]}" e em "{camada}" — em qual voz?')
            if not (pasta / f'{slug}.json').exists():
                sys.exit(f'indice.json cita "{slug}" em "{camada}", mas {slug}.json não existe em {pasta}')
            camada_de[slug] = camada
    sem_camada = sorted(p.stem for p in pasta.glob('*.json')
                        if p.name != 'indice.json' and p.stem not in camada_de)
    if sem_camada:
        sys.exit(f'{pasta} tem oração fora do indice.json: {sem_camada} — em qual camada entra?')
    return camada_de


def compor_oracoes(app):
    """As orações guiadas do índice (hoje 9) e as cópias evangélicas das
    comuns (hoje 4; pendência no topo do arquivo)."""
    pasta = app / 'assets' / 'content' / 'oracoes'
    trechos = []

    def oracao(slug, tradicao, sufixo='', grava=True):
        dados = ler_json(pasta / f'{slug}.json')
        passos = [p['texto'] for p in dados['passos']]
        asset = dados['audioAsset']
        esperado = f'assets/audio/oracoes/{slug}.m4a'
        if asset != esperado:
            sys.exit(f'{slug}.json: audioAsset "{asset}", esperado "{esperado}"')
        arquivo = asset
        if sufixo:
            arquivo = f'assets/audio/oracoes/{slug}{sufixo}.m4a'
        return Trecho(id=f'{slug}{sufixo}', destino=app / arquivo, tradicao=tradicao,
                      pecas=tuple(pecas_de_oracao(passos, slug, 0.0, True, conta_em_todos=True)),
                      contas_esperadas=len(passos),
                      json=(pasta / f'{slug}.json') if grava else None, posicao=None,
                      arquivo=arquivo)

    for slug, camada in camadas_do_indice(pasta).items():
        if camada == CAMADA_COMUM:
            trechos.append(oracao(slug, 'catolico'))
            trechos.append(oracao(slug, 'evangelico', SUFIXO_EVANGELICO, grava=False))
        else:
            trechos.append(oracao(slug, VOZ_DA_CAMADA[camada]))
    return trechos


def catalogo(app, midia=MIDIA_PADRAO):
    """Tudo o que a ferramenta gera: 28 do Terço (em <midia>/terco/) + 9
    orações + 4 evangélicas (no app)."""
    trechos = []
    for misterio in MISTERIOS:
        trechos += compor_terco(app, misterio, midia)
    trechos += compor_oracoes(app)
    for t in trechos:
        if t.contas != t.contas_esperadas:
            sys.exit(f'{t.id}: a composição dá {t.contas} contas, a tela espera '
                     f'{t.contas_esperadas} — PARE e revise a composição')
    ids = [t.id for t in trechos]
    if len(ids) != len(set(ids)):
        sys.exit('ids repetidos no catálogo')
    return trechos


# ---------------------------------------------------------------------------
# Peças: identidade, geração, medição
# ---------------------------------------------------------------------------

def chave_da_peca(peca, tradicao, trecho_id, posicao, reaproveitar):
    """Nome estável da peça no diretório de trabalho. Reaproveitando, (voz,
    texto) basta — a mesma Ave-Maria é um arquivo só; sem reaproveitar, cada
    posição de cada trecho é uma peça própria."""
    base = f'{tradicao}|{peca.texto}'
    if not reaproveitar:
        base += f'|{trecho_id}|{posicao}'
    return hashlib.sha1(base.encode('utf-8')).hexdigest()[:20]


def pasta_da_peca(trabalho, tradicao):
    return trabalho / 'pecas' / tradicao


def arquivos_da_peca(trabalho, tradicao, chave):
    pasta = pasta_da_peca(trabalho, tradicao)
    return pasta / f'{chave}.wav', pasta / f'{chave}.mp3', pasta / f'{chave}.json'


def _ffmpeg(*args):
    r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'ffmpeg falhou: {r.stderr.strip()[:400]}')


def silencio_wav(destino, segundos):
    """Um silêncio de duração exata, em PCM mono na TAXA do projeto."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg('-f', 'lavfi', '-i', f'anullsrc=r={TAXA}:cl=mono', '-t', f'{segundos:.3f}',
            '-c:a', 'pcm_s16le', str(destino))
    return destino


def duracao_simulada(texto):
    return max(DURACAO_MINIMA_SIMULADA, len(texto) / CARACTERES_POR_SEGUNDO)


def gerar_peca(peca, tradicao, chave, trabalho, simular, chave_api_=None,
               normalizacao='auto'):
    """Produz o .wav medido da peça (e o .mp3 bruto da API, no modo real) e
    grava o .json de metadados ao lado. Devolve a duração em segundos."""
    wav, mp3, meta = arquivos_da_peca(trabalho, tradicao, chave)
    wav.parent.mkdir(parents=True, exist_ok=True)
    registro = {'chave': chave, 'tradicao': tradicao, 'texto': peca.texto,
                'caracteres': len(peca.texto), 'simulado': simular,
                'quando': time.strftime('%Y-%m-%dT%H:%M:%S')}
    if simular:
        silencio_wav(wav, duracao_simulada(peca.texto))
    else:
        audio, pedido = sintetizar(chave_api_, {'tradicao': tradicao, 'texto': peca.texto},
                                   normalizacao)
        mp3.write_bytes(audio)
        _ffmpeg('-i', str(mp3), '-ac', '1', '-ar', str(TAXA), '-c:a', 'pcm_s16le', str(wav))
        registro['pedido'] = pedido
    registro['segundos'] = round(duracao_segundos(wav), 3)
    meta.write_text(json.dumps(registro, ensure_ascii=False, indent=1), encoding='utf-8')
    return registro['segundos']


# ---------------------------------------------------------------------------
# Montagem e marcas
# ---------------------------------------------------------------------------

def calcular_marcas(pecas, duracoes):
    """A marca de cada peça com conta: soma das durações e dos silêncios
    anteriores. Função pura — é ela que os testes conferem."""
    if len(pecas) != len(duracoes):
        raise ValueError('peças e durações não batem')
    marcas, posicao = [], 0.0
    for peca, dur in zip(pecas, duracoes):
        posicao += peca.pausa_antes
        if peca.conta:
            marcas.append(round(posicao, 2))
        posicao += dur
    return marcas, round(posicao, 3)


def conferir_crescentes(marcas, rotulo):
    """O lint do app (regras 11/12) exige marcas ESTRITAMENTE crescentes;
    TrechoDeAudio.fromJson lança se decrescerem. Melhor parar aqui."""
    for i in range(1, len(marcas)):
        if marcas[i] <= marcas[i - 1]:
            raise ValueError(f'{rotulo}: marcas {i} e {i + 1} não crescem '
                             f'({marcas[i - 1]} → {marcas[i]})')


def montar(trecho, wavs, trabalho):
    """Concatena peças e silêncios num .m4a só (uma codificação) e devolve
    (marcas, duração total medida). `wavs` são os .wav das peças, na ordem."""
    duracoes = [duracao_segundos(w) for w in wavs]
    marcas, previsto = calcular_marcas(trecho.pecas, duracoes)
    conferir_crescentes(marcas, trecho.id)

    montagem = trabalho / 'montagem' / trecho.id
    montagem.mkdir(parents=True, exist_ok=True)
    linhas = []
    for peca, wav in zip(trecho.pecas, wavs):
        if peca.pausa_antes > 0:
            sil = trabalho / 'silencios' / f'{peca.pausa_antes:.3f}.wav'
            if not sil.exists():
                silencio_wav(sil, peca.pausa_antes)
            linhas.append(sil)
        linhas.append(wav)
    lista = montagem / 'lista.txt'
    # Caminhos com barra normal e aspas simples: é o que o demuxer concat lê,
    # inclusive no Windows.
    lista.write_text(''.join(f"file '{p.resolve().as_posix()}'{chr(10)}" for p in linhas),
                     encoding='utf-8')
    trecho.destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = trecho.destino.with_suffix('.parte.m4a')
    _ffmpeg('-f', 'concat', '-safe', '0', '-i', str(lista), *PARAMETROS_AAC, str(parcial))
    parcial.replace(trecho.destino)

    total = duracao_segundos(trecho.destino)
    # O AAC acrescenta uns milissegundos de priming; mais que isso é sinal de
    # peça errada na lista.
    if abs(total - previsto) > 0.15:
        raise RuntimeError(f'{trecho.id}: o arquivo final tem {total:.3f}s, '
                           f'as peças somam {previsto:.3f}s')
    return marcas, total


_MARCAS = re.compile(r'"marcas"\s*:\s*\[[^\]]*\]')


def formatar_marcas(marcas):
    partes = [str(int(m)) if float(m).is_integer() else f'{m:g}' for m in marcas]
    return '[' + ', '.join(partes) + ']'


def substituir_marcas(texto, ocorrencia, marcas):
    """Troca só a N-ésima `"marcas": [...]` do texto do JSON, byte a byte no
    resto: o arquivo mantém a formatação, a ordem das chaves e todos os
    outros campos — o diff é uma linha."""
    achados = list(_MARCAS.finditer(texto))
    if ocorrencia >= len(achados):
        raise ValueError(f'só {len(achados)} "marcas" no arquivo, pedida a {ocorrencia + 1}ª')
    a = achados[ocorrencia]
    return texto[:a.start()] + f'"marcas": {formatar_marcas(marcas)}' + texto[a.end():]


def gravar_marcas(trecho, marcas):
    """Grava as marcas no JSON do trecho e confere, reparseando, que nada
    além delas mudou."""
    with open(trecho.json, encoding='utf-8', newline='') as f:
        antes = f.read()
    dados_antes = json.loads(antes)
    if trecho.posicao is None:
        ocorrencia, esperado = 0, 1
    else:
        ocorrencia, esperado = trecho.posicao, len(dados_antes['trechos'])
    if len(_MARCAS.findall(antes)) != esperado:
        raise ValueError(f'{trecho.json.name}: esperadas {esperado} chaves "marcas"')
    depois = substituir_marcas(antes, ocorrencia, marcas)
    dados_depois = json.loads(depois)
    if trecho.posicao is None:
        if dados_depois['marcas'] != marcas:
            raise ValueError(f'{trecho.json.name}: as marcas gravadas não bateram')
        dados_depois['marcas'] = dados_antes['marcas']
    else:
        if dados_depois['trechos'][ocorrencia]['marcas'] != marcas:
            raise ValueError(f'{trecho.json.name}: as marcas gravadas não bateram')
        dados_depois['trechos'][ocorrencia]['marcas'] = dados_antes['trechos'][ocorrencia]['marcas']
    if json.dumps(dados_depois) != json.dumps(dados_antes):
        raise ValueError(f'{trecho.json.name}: a gravação mudaria algo além das marcas')
    with open(trecho.json, 'w', encoding='utf-8', newline='') as f:
        f.write(depois)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

def pecas_do_trecho(trecho, reaproveitar):
    """[(posição 1-based, peça, chave)] de um trecho."""
    return [(n, p, chave_da_peca(p, trecho.tradicao, trecho.id, n, reaproveitar))
            for n, p in enumerate(trecho.pecas, 1)]


def construir(trecho, trabalho, reaproveitar, log):
    """Monta o arquivo final a partir das peças já prontas, grava as marcas
    (se o trecho tiver JSON) e registra no log."""
    wavs = []
    for _, _, chave in pecas_do_trecho(trecho, reaproveitar):
        wav = arquivos_da_peca(trabalho, trecho.tradicao, chave)[0]
        if not wav.exists():
            raise RuntimeError(f'{trecho.id}: falta a peça {chave}')
        wavs.append(wav)
    marcas, total = montar(trecho, wavs, trabalho)
    if len(marcas) != trecho.contas_esperadas:
        raise RuntimeError(f'{trecho.id}: {len(marcas)} marcas, a tela espera {trecho.contas_esperadas}')
    if trecho.json is not None:
        gravar_marcas(trecho, marcas)
    simulado = any(json.loads(arquivos_da_peca(trabalho, trecho.tradicao, c)[2]
                              .read_text(encoding='utf-8')).get('simulado')
                   for _, _, c in pecas_do_trecho(trecho, reaproveitar))
    # A chave publicada ('terco/x.m4a') ou o asset embutido
    # ('assets/audio/oracoes/x.m4a') — nunca o caminho absoluto do disco.
    registro = {'arquivo': trecho.arquivo or trecho.destino.name,
                'id': trecho.id, 'tradicao': trecho.tradicao, 'pecas': len(trecho.pecas),
                'caracteres': trecho.caracteres, 'marcas': marcas,
                'segundos': round(total, 2), 'bytes': trecho.destino.stat().st_size,
                'simulado': simulado, 'gravou_json': trecho.json is not None,
                'quando': time.strftime('%Y-%m-%dT%H:%M:%S')}
    registrar(registro, log)
    return registro


def eh_do_terco(trecho):
    return trecho.arquivo.startswith(PASTA_DO_TERCO + '/')


def selecionar(trechos, args):
    if args.apenas == 'terco':
        trechos = [t for t in trechos if eh_do_terco(t)]
    elif args.apenas == 'oracoes':
        trechos = [t for t in trechos if not eh_do_terco(t)]
    if args.ids:
        quero = set(args.ids.split(','))
        desconhecidos = quero - {t.id for t in trechos}
        if desconhecidos:
            sys.exit(f'ids desconhecidos: {sorted(desconhecidos)}')
        trechos = [t for t in trechos if t.id in quero]
    return trechos


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    ap.add_argument('--app', default=str(APP_PADRAO),
                    help='raiz do repo manha-de-fe-app (padrão: pasta-irmã, ou MANHA_DE_FE_APP)')
    ap.add_argument('--midia', default=str(MIDIA_PADRAO),
                    help='raiz do repo manhadefe-midia, onde terco/ é gravado (padrão: este repo)')
    ap.add_argument('--trabalho', help='diretório das peças (padrão: narracao/trechos; simulado: narracao/trechos-simulado)')
    ap.add_argument('--log', default=str(LOG))
    ap.add_argument('--apenas', choices=['terco', 'oracoes'])
    ap.add_argument('--ids', help='ids exatos, separados por vírgula: gozosos-dezena-1,ave-maria,salmo-23-evangelico')
    ap.add_argument('--refazer', action='store_true', help='gera de novo as peças dos trechos escolhidos (e reconstrói quem as usa)')
    ap.add_argument('--passos', help='com --refazer e um só --ids: só estas peças (posições 1-based, vírgula)')
    ap.add_argument('--simular', action='store_true', help='silêncio no lugar da voz; todo o resto de verdade')
    ap.add_argument('--so-contar', action='store_true')
    ap.add_argument('--sem-reaproveitar', action='store_true', help='cada ocorrência do mesmo texto vira uma geração própria')
    ap.add_argument('--mostrar', help='imprime a composição (peça a peça) do id e sai')
    ap.add_argument('--normalizacao', default='auto', choices=['auto', 'on', 'off'])
    ap.add_argument('--paralelo', type=int, default=3)
    ap.add_argument('--forcar', action='store_true', help='segue mesmo se o saldo não cobrir tudo')
    args = ap.parse_args(argv)

    app = Path(args.app)
    if not (app / 'pubspec.yaml').exists():
        sys.exit(f'{app} não parece o repo do app (sem pubspec.yaml): aponte com --app '
                 'ou com a variável de ambiente MANHA_DE_FE_APP')
    midia = Path(args.midia)
    trabalho = Path(args.trabalho) if args.trabalho else (TRABALHO_SIMULADO if args.simular else TRABALHO_PADRAO)
    log = Path(args.log)
    reaproveitar = not args.sem_reaproveitar

    todos = catalogo(app, midia)
    if args.mostrar:
        return mostrar(todos, args.mostrar)
    escolhidos = selecionar(todos, args)
    if not args.refazer:
        escolhidos = [t for t in escolhidos if not t.destino.exists()]

    # Quais peças gerar: as que faltam no trabalho — ou, com --refazer, as
    # dos trechos escolhidos (restritas por --passos).
    a_refazer = set()
    if args.refazer:
        if args.passos:
            if len(escolhidos) != 1:
                sys.exit('--passos pede exatamente um --ids')
            posicoes = {int(p) for p in args.passos.split(',')}
            fora = posicoes - set(range(1, len(escolhidos[0].pecas) + 1))
            if fora:
                sys.exit(f'--passos fora do trecho (ele tem {len(escolhidos[0].pecas)} peças): {sorted(fora)}')
            a_refazer = {c for n, _, c in pecas_do_trecho(escolhidos[0], reaproveitar) if n in posicoes}
        else:
            a_refazer = {c for t in escolhidos for _, _, c in pecas_do_trecho(t, reaproveitar)}

    pendentes = {}  # chave -> (peça, tradição)
    for t in escolhidos:
        for _, peca, chave in pecas_do_trecho(t, reaproveitar):
            wav = arquivos_da_peca(trabalho, t.tradicao, chave)[0]
            if chave in a_refazer or not wav.exists():
                pendentes[chave] = (peca, t.tradicao)

    # Reaproveitando, uma peça refeita muda todo trecho JÁ MONTADO que a usa:
    # eles são reconstruídos também, senão o .m4a deles e as marcas no JSON
    # ficariam de versões diferentes da mesma peça. Trecho nunca montado não
    # tem nada envelhecido — e puxá-lo geraria peças que ninguém pediu.
    a_construir = list(escolhidos)
    if a_refazer:
        vistos = {t.id for t in a_construir}
        for t in todos:
            if (t.id not in vistos and t.destino.exists()
                    and any(c in a_refazer for _, _, c in pecas_do_trecho(t, reaproveitar))):
                a_construir.append(t)

    caracteres = sum(len(p.texto) for p, _ in pendentes.values())
    sem_reuso = sum(t.caracteres for t in escolhidos)
    print(f'arquivos a montar: {len(a_construir)} (de {len(todos)} no catálogo)')
    print(f'peças a gerar: {len(pendentes)}, {_milhar(caracteres)} caracteres'
          + (f' (sem reaproveitar seriam {_milhar(sem_reuso)})' if reaproveitar else ''))
    if args.simular:
        print(f'modo SIMULADO: silêncio no lugar da voz, peças em {trabalho}')

    chave = None
    if not args.simular:
        try:
            chave = chave_api()
        except SystemExit as e:
            if not args.so_contar:
                raise
            print(f'aviso: {e}')
        s = saldo(chave) if chave else None
        if s:
            print(f'plano {s["plano"]}: {s["usados"]} usados de {s["limite"]}, restam {s["restam"]}')
        if not args.so_contar and pendentes:
            if s is None:
                sys.exit('sem chave válida: troque a chave (ver narrar.py) e rode de novo, '
                         'ou use --simular para provar o caminho')
            if caracteres > s['restam'] and not args.forcar:
                sys.exit('o saldo não cobre este lote; reduza com --ids/--apenas ou use --forcar')
    if args.so_contar or not a_construir:
        return 0

    erros = 0
    inicio = time.time()
    if pendentes:
        with ThreadPoolExecutor(max_workers=max(1, args.paralelo)) as pool:
            futuros = {pool.submit(gerar_peca, peca, trad, ch, trabalho, args.simular,
                                   chave, args.normalizacao): (ch, peca)
                       for ch, (peca, trad) in pendentes.items()}
            for n, fut in enumerate(as_completed(futuros), 1):
                ch, peca = futuros[fut]
                try:
                    seg = fut.result()
                    print(f'[peça {n}/{len(pendentes)}] ok   {peca.rotulo:<24} {seg:6.2f}s  {len(peca.texto)} car.')
                except Exception as e:  # noqa: BLE001
                    erros += 1
                    print(f'[peça {n}/{len(pendentes)}] ERRO {peca.rotulo}: {str(e)[:200]}')
    if erros:
        print(f'{erros} peça(s) com erro — nada montado; rode de novo para completar')
        return 1

    for n, t in enumerate(a_construir, 1):
        try:
            r = construir(t, trabalho, reaproveitar, log)
            gravou = 'marcas no JSON' if r['gravou_json'] else 'marcas só no log'
            print(f'[{n}/{len(a_construir)}] ok   {t.id:<28} {r["segundos"]:7.2f}s  '
                  f'{len(r["marcas"])} marcas  {r["bytes"] // 1024} KB  ({gravou})')
        except Exception as e:  # noqa: BLE001
            erros += 1
            print(f'[{n}/{len(a_construir)}] ERRO {t.id}: {str(e)[:300]}')
    print(f'{chr(10)}montados {len(a_construir) - erros} - erros {erros} - {(time.time() - inicio) / 60:.1f} min')
    return 1 if erros else 0


def mostrar(trechos, id_):
    t = next((t for t in trechos if t.id == id_), None)
    if t is None:
        sys.exit(f'id desconhecido: {id_}')
    print(f'{t.id}  voz {t.tradicao}  {len(t.pecas)} peças  {t.contas} contas  '
          f'{_milhar(t.caracteres)} caracteres  {t.arquivo}  -> {t.destino}')
    for n, p in enumerate(t.pecas, 1):
        marca = 'CONTA' if p.conta else '     '
        print(f'{n:3} {marca} +{p.pausa_antes:.1f}s  {p.rotulo:<24} {p.texto}')
    return 0


def _milhar(n):
    return f'{n:,}'.replace(',', '.')


if __name__ == '__main__':
    sys.exit(main())
