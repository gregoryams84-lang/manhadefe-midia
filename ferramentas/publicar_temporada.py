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
   - vídeos: os dois de cada capítulo, h264 yuv420p (o 4:2:0 de 8 bits que
     todo Android toca; o yuvj420p, o mesmo com a faixa cheia de cor, passa
     com um AVISO que sugere exportar em yuv420p; 10 bits, 4:2:2 e 4:4:4
     são erro), 720x1280, até 25 MB (D4), a duração a 2 s de
     duracaoS e as duas versões a 0,5 s uma da outra (no limite passa); e
     as duas diferentes — o mesmo sha256 nas duas é entrega trocada (o
     bispo na católica, o pastor na evangélica);
   - capa WebP 1080x1350;
   - legenda: SRT que o parser do app lê inteiro, UMA linha por fala, até
     42 caracteres (cabe inteira com a letra no máximo, Ruling 9), cada fala
     com pelo menos 1,5 s, dentro da duração do vídeo e sem sobrepor a
     anterior. A fala com mais de 42 caracteres é DIVIDIDA em pedaços de
     até 42 (entre palavras, de preferência depois de pontuação), com a
     duração repartida na proporção dos caracteres e cada pedaço com pelo
     menos 1,5 s — sai como AVISO (fala, pedaços e tempos), e o SRT que vai
     para novela/ é o dividido (o da entrega não muda). A fala que dura
     menos do que precisa (1,5 s; ou k × 1,5 s, quando vai ser dividida
     em k pedaços) é ESTENDIDA até isso quando há espaço — para a frente
     até a fala seguinte ou o fim do vídeo, para trás no vazio depois da
     anterior, ou encurtando a anterior no que ela tem acima do mínimo
     dela —, também como AVISO; sem espaço, é erro como antes;
   - textos: versículo até 180 caracteres, reflexão de 40 a 100 palavras
     e no máximo 2 travessões (as réguas do lint do app, contadas do mesmo
     jeito: no texto aparado, como o app o lê), oração terminando em
     "Amém.", referência "Livro C,V" ou "Livro C,V-V" (a palavra final é do
     lint, que roda no fim);
   - índice: o novela/temporadas.json FINAL — as temporadas que já estavam,
     com esta no lugar da versão anterior dela (o mesmo id) — passa pelas
     regras do app, que o recusa inteiro por qualquer uma: base terminada
     em /, ids únicos, fim = início + capítulos − 1 e nenhuma sobreposição
     de datas (nem entre as que já estavam);
   - no caminho real, também as ferramentas: as chaves do R2, o boto3, o
     dart, as ferramentas do app e as da voz na raiz de mídia.

2. ESCREVE (tudo conferido):
   - R2 (balde manhadefe-video, as chaves com o --r2-prefixo): NUNCA
     sobrescreve um objeto com outro conteúdo, com ou sem opção, e nunca
     apaga nada. A chave de cada vídeo sai só de consultas (HEAD): a que o
     novela/<t>.json já publicado dá, se o objeto lá é este (já estava);
     senão a fixa video/<t>/<NN>-<tradicao>.mp4 — ausente, sobe (novo);
     com este conteúdo, já estava; com OUTRO sha256 (trocado), a
     publicação recusa antes de subir ou escrever qualquer coisa, listando
     chave, capítulo e data — e, quando nenhum novela/<t>.json (nem o da
     pasta, nem o do último commit dela) aponta o vídeo, explica que o
     objeto é provavelmente sobra de uma rodada interrompida, que nenhum
     aparelho o usa e que --substituir-videos é seguro (nem a sobra é
     sobrescrita). Com --substituir-videos, o trocado sobe na
     chave versionada video/<t>/<NN>-<tradicao>-<sha8>.mp4 (sha8 = os 8
     primeiros hex do sha256) e o objeto velho fica: o aparelho com o JSON
     velho baixa o velho, o com o novo baixa o novo, sem janela. O sha256
     vai nos metadados e o que sobe é conferido depois. Vem PRIMEIRO: se o
     envio falhar, nenhum JSON local aponta para um vídeo que não está lá.
     Uma publicação real por vez: a trava <midia>/.publicando.trava (criada
     com O_EXCL, com a data/hora e o PID) vem antes de qualquer conferência,
     HEAD ou envio e sai no fim, também na falha; presente, a publicação
     recusa na hora — se nenhuma estiver rodando, apague o arquivo. O HEAD
     de logo antes de cada envio só estreita a janela; quem impede a
     corrida é a trava (que vale para a mesma --midia: duas raízes de mídia
     diferentes publicando o mesmo prefixo ao mesmo tempo não se veem);
   - a URL pública: cada vídeo (o que subiu e o que já estava) por um HEAD
     em <base><chave>, a URL que o app vai pedir — o Content-Length tem de
     ser o tamanho do arquivo, senão para antes de escrever. Em produção
     (sem --r2-prefixo), a base com "teste/" é recusada e a *.r2.dev só
     avisa (é a base real até o domínio próprio entrar);
   - <midia>/novela/<t>.json: a temporada no formato do app (Temporada.fromJson
     em lib/content/novela.dart) — por capítulo, `id` <t>c<n>, `capa`,
     `legenda` (só com SRT) e `video` com arquivo (a chave escolhida
     acima), bytes e sha256;
   - capas em <midia>/imagens/<t>c<n>.webp, legendas em
     <midia>/novela/<t>c<n>.srt (sem o BOM, se vier com um); as sobras de
     uma versão anterior da MESMA temporada (capítulo que sumiu, legenda
     que saiu) são apagadas;
   - <midia>/novela/temporadas.json: {versao, videos, temporadas}, em ordem
     de início, as outras mantidas. A base `videos` vem de --videos-base,
     senão do índice existente, senão da "Public Development URL" do
     arquivo de chaves (+ --r2-prefixo), sempre terminando em /;
   - o manifesto (gerar_manifesto.dart), conferido: tem de listar os
     arquivos da temporada (um app anterior à Task 7 não conhece novela/ e
     a temporada não chegaria a ninguém); e o lint (lint_conteudo.dart, 0
     erros, senão sai com 1). Os dois rodam ANTES da voz — o lint é a
     palavra final sobre os textos, e um texto que ele recusa não gasta um
     crédito de voz (a narração ausente é só pendência da regra 2) — e DE
     NOVO depois dela, com a voz dentro;
   - a voz dos cartões dos dias de capítulo (sem --sem-voz), SÓ o que
     mudou: texto_narrado.dart --temporadas dá o texto de cada narração;
     ao lado de cada .m4a fica o registro <arquivo>.origem (sha256 do
     texto narrado, motor e voz), e só a narração sem registro ou com
     registro diferente passa pelo narrar.py (--refazer gera tudo); o
     conferir_stt.py --stt whisper roda só no que foi gerado agora ou que
     o stt.log.jsonl ainda não aprovou com estes bytes. Reprovado, para e
     lista SÓ os ids reprovados, apaga o registro deles e manda rodar a
     publicação de novo (que gera só esses). Rodar duas vezes a mesma
     publicação não gera nenhum .m4a novo e deixa o manifesto igual. Os
     dois .py rodam a cópia de DENTRO de --midia: eles gravam na raiz do
     repositório em que estão. Os .origem vão no commit junto dos .m4a.
   Parar DEPOIS de escrever (a voz reprovada, o manifesto, o lint — e
   também um Ctrl+C ou uma exceção imprevista, que seguem subindo depois
   do bloco) lista o que esta rodada escreveu e removeu, diz em destaque
   "NÃO rode o gerar_manifesto nem faça commit" e dá os comandos exatos
   para desfazer: git checkout -- <os versionados> e git clean -f -- <os
   novos>. Nada vai para quarentena.
   No fim, o resumo. NUNCA faz commit nem push: commit por caminho, e o
   push só com o OK do Gregory.

--simular: exige --midia numa pasta temporária — nunca o repositório real,
o repositório do app ou qualquer pasta com .git (ela ou uma acima dela);
escreve os JSONs, as capas e as legendas nela; não sobe ao R2, não gera
voz, não roda o Dart e nunca lê o arquivo de chaves (sem --videos-base e
sem índice, a base é o marcador "<Public Development URL>/" + prefixo) —
imprime o que faria. O estado do R2 (novo, já estava, trocado) sai do
novela/<t>.json publicado na pasta, sem consultar o balde.

As chaves do R2 são lidas do arquivo (--r2) pelos rótulos ("Access Key ID",
"Secret Access Key", a URL https://<conta>.r2.cloudflarestorage.com e a
"Public Development URL") e só usadas dentro do processo: nunca impressas
nem gravadas. Erro do R2, do botocore ou da rede nunca vai cru à tela:
passa por descrever_erro — o tipo (o Error.Code, num ClientError) e a
mensagem limpa por limpar_mensagem (o endpoint, o host dele, o id da conta
e as chaves viram "<endpoint do R2>", "<conta>" e "<chave>").

Uso:
  python ferramentas/publicar_temporada.py "<entrega>" --simular --midia <pasta temporária>
  python ferramentas/publicar_temporada.py "<entrega>" --motor microsoft
  python ferramentas/publicar_temporada.py "<entrega>" --midia <cópia do repo> --r2-prefixo teste/midia/ --motor microsoft
  python ferramentas/publicar_temporada.py "<entrega>" --motor microsoft --substituir-videos   # vídeo já publicado trocado
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
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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
# O repositório do app do Gregory, onde quer que este script esteja: rodando
# de uma CÓPIA do repo de mídia, a pasta-irmã (APP_PADRAO) não é ele, e a
# trava do --simular tem de reconhecê-lo mesmo assim.
REPOSITORIO_DO_APP = Path('C:/Users/robot/dev/manha-de-fe-app')
# A base dos vídeos na simulação, que nunca lê o arquivo de chaves: a rodada
# real põe aqui a "Public Development URL" do R2.
MARCADOR_DA_URL_PUBLICA = '<Public Development URL>'
DART_PADRAO = Path('C:/Users/robot/flutter-sdk/bin') / ('dart.bat' if os.name == 'nt' else 'dart')
BALDE = 'manhadefe-video'
MOTORES = ('elevenlabs', 'microsoft')
TRADICOES = ('catolico', 'evangelico')

# As réguas da entrega.
LIMITE_DE_BYTES = 25 * 1024 * 1024          # D4: vídeo até 25 MB
TAMANHO_DO_VIDEO = (720, 1280)
PIX_FMT_DO_VIDEO = 'yuv420p'
# R8-M: o mesmo 4:2:0 de 8 bits, só com a faixa cheia de cor (comum em
# exportação de imagem/IA) — toca nos Android: passa, com um AVISO.
PIX_FMT_FAIXA_CHEIA = 'yuvj420p'
EXPORTAR_EM_YUV420P = 'exporte em yuv420p: -vf scale=out_range=tv -pix_fmt yuv420p'
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
    shas: dict                  # tradição -> sha256 do vídeo (medido na conferência)
    legenda_ajustada: str | None = None   # o SRT que vai para novela/, quando a conferência o ajustou

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
    travessão colado entre letras separa dois. O texto é o APARADO — o app
    apara (Capitulo.fromJson) e o lint mede o aparado: espaço nas pontas
    não é palavra."""
    total = 0
    for pedaco in _ESPACOS.split(reflexao.strip()):
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
    """{codec, pix_fmt, largura, altura, duracao} do primeiro fluxo de vídeo
    (a imagem WebP conta como um), pelo ffprobe; None se ele não ler."""
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                        'stream=codec_type,codec_name,pix_fmt,width,height:format=duration',
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
    return {'codec': fluxo.get('codec_name'), 'pix_fmt': fluxo.get('pix_fmt'),
            'largura': fluxo.get('width'), 'altura': fluxo.get('height'), 'duracao': duracao}


def passa_da_folga(a, b, folga):
    """|a - b| > folga, com a diferença arredondada ao microssegundo (a
    precisão do ffprobe): 4,4 - 3,9 dá 0,5000000000000004 em ponto
    flutuante, e no limite tem de passar."""
    return round(abs(a - b), 6) > folga


def _milhar(n):
    return f'{n:,}'.replace(',', '.')


def _segundos(ms):
    """1400 -> "1,4"; 1499 -> "1,499"; 2000 -> "2"."""
    return f'{ms / 1000:.3f}'.rstrip('0').rstrip('.').replace('.', ',')


def _casas(segundos):
    """87.733 -> "87,73"; 2.0 -> "2"."""
    return f'{segundos:.2f}'.rstrip('0').rstrip('.').replace('.', ',')


def _ms(segundos):
    """Até o milissegundo: 6.001 -> "6,001"; 4.4 -> "4,4"; 6.0 -> "6" — a
    recusa no limite mostra a diferença que recusou."""
    return f'{segundos:.3f}'.rstrip('0').rstrip('.').replace('.', ',')


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


PONTUACAO_DE_CORTE = ',;:.!?…'
# Um corte fora da pontuação custa o mesmo que uns 20 caracteres de
# desequilíbrio entre os pedaços (20², na soma dos quadrados).
CUSTO_DO_CORTE_SEM_PONTUACAO = 400


def dividir_fala(texto, maximo=MAXIMO_DE_CARACTERES_DA_FALA):
    """Os pedaços de até `maximo` caracteres de uma fala longa (FM3), ou
    None quando não dá (uma palavra maior que o máximo). Só corta entre
    palavras. Entre as partições possíveis, a de MENOS pedaços (menos
    trocas na tela, cada uma mais tempo); entre essas, a de menor custo —
    a soma dos quadrados dos comprimentos (a mais equilibrada) mais
    CUSTO_DO_CORTE_SEM_PONTUACAO por corte que não vem depois de
    pontuação: "O meu feixe se levantou, | e os vossos…" vence o corte
    pelo meio, e "Ontem: | José interpretou…" perde para ele. A fala que
    cabe volta inteira, intocada."""
    if len(texto) <= maximo:
        return [texto]
    palavras = texto.split()
    if not palavras or any(len(p) > maximo for p in palavras):
        return None
    n = len(palavras)
    melhor = [None] * (n + 1)      # (pedaços, custo, partição) das palavras [0, j)
    melhor[0] = (0, 0, [])
    for j in range(1, n + 1):
        for i in range(j - 1, -1, -1):
            pedaco = ' '.join(palavras[i:j])
            if len(pedaco) > maximo:
                break
            if melhor[i] is None:
                continue
            pedacos, custo, particao = melhor[i]
            corte = 0 if j == n or pedaco[-1] in PONTUACAO_DE_CORTE else CUSTO_DO_CORTE_SEM_PONTUACAO
            candidato = (pedacos + 1, custo + len(pedaco) ** 2 + corte, particao + [pedaco])
            if melhor[j] is None or candidato[:2] < melhor[j][:2]:
                melhor[j] = candidato
    return melhor[n][2]


def repartir_duracao(total_ms, comprimentos, minimo=MINIMO_DE_MS_DA_FALA):
    """A duração (ms, inteira) de cada pedaço de uma fala dividida (FM3):
    na proporção dos caracteres, com cada pedaço ficando com pelo menos
    `minimo` — o que falta a um pedaço curto sai dos outros, na proporção
    deles. A soma é exatamente `total_ms`. None se o total não dá para
    todos (len × minimo): a fala é curta demais para a divisão."""
    k = len(comprimentos)
    if total_ms < k * minimo:
        return None
    fixos, duracoes = {}, {}
    while True:
        livres = [i for i in range(k) if i not in fixos]
        sobra = total_ms - sum(fixos.values())
        peso = sum(comprimentos[i] for i in livres)
        duracoes = {i: sobra * comprimentos[i] / peso for i in livres} if peso else {}
        curtos = [i for i in livres if duracoes[i] < minimo]
        if not curtos:
            break
        for i in curtos:
            fixos[i] = minimo
    exatas = [fixos.get(i, duracoes.get(i, 0)) for i in range(k)]
    inteiras = [int(d) for d in exatas]
    # O que o truncamento tirou volta um ms por vez, para as maiores frações.
    resto = total_ms - sum(inteiras)
    for i in sorted(range(k), key=lambda i: exatas[i] - inteiras[i], reverse=True)[:resto]:
        inteiras[i] += 1
    return inteiras


@dataclass
class _Fala:
    """Uma fala da legenda com tempo válido, na ordem do arquivo."""
    numero: int                  # a posição (1, 2...), como as mensagens contam
    inicio: int                  # ms
    fim: int
    texto: str
    pedacos: list | None = None  # (inicio, fim, texto) de cada pedaço, quando dividida
    sem_espaco: bool = False     # precisava de mais tempo e não havia para onde estender


def _minimo_da_fala(texto):
    """Quanto a fala precisa durar: 1,5 s, ou k × 1,5 s quando vai ser
    dividida em k pedaços (dividir_fala); a que não dá para dividir conta
    como inteira (o problema dela é outro)."""
    return len(dividir_fala(texto) or [texto]) * MINIMO_DE_MS_DA_FALA


def _estender_falas(falas, fim_do_video, problemas, avisos):
    """FM4: a fala que dura menos do que precisa (_minimo_da_fala) é
    estendida até isso quando há espaço — primeiro para a frente, até a
    fala seguinte (ou o fim do vídeo); depois para trás, no vazio depois da
    anterior (ou desde o 0); por fim encurtando a anterior, no que ela tem
    acima do mínimo DELA (o caso real do 05.srt da t1-v2: a fala curta
    colada nas duas vizinhas). Quando o espaço não chega, nada muda: a
    fala curta vira problema aqui; a longa fica marcada (`sem_espaco`) e o
    problema é o da divisão que não cabe. Cada extensão sai como aviso.
    `problemas` e `avisos` recebem (número da fala, texto)."""
    for k, fala in enumerate(falas):
        precisa = _minimo_da_fala(fala.texto)
        duracao = fala.fim - fala.inicio
        falta = precisa - duracao
        if falta <= 0:
            continue
        limite = falas[k + 1].inicio if k + 1 < len(falas) else fim_do_video
        frente = falta if limite is None else max(0, min(falta, limite - fala.fim))
        piso = falas[k - 1].fim if k else 0
        tras = max(0, min(falta - frente, fala.inicio - piso))
        anterior = falas[k - 1] if k else None
        cede = 0
        if anterior is not None:
            sobra = (anterior.fim - anterior.inicio) - _minimo_da_fala(anterior.texto)
            cede = max(0, min(falta - frente - tras, sobra))
        if frente + tras + cede < falta:
            if len(fala.texto) <= MAXIMO_DE_CARACTERES_DA_FALA:
                problemas.append((fala.numero, f'fala {fala.numero} dura {_segundos(duracao)} s — o '
                                               f'mínimo é {_segundos(MINIMO_DE_MS_DA_FALA)} s, e não '
                                               'há espaço para estendê-la'))
            else:
                fala.sem_espaco = True
            continue
        fala.fim += frente
        fala.inicio -= tras + cede
        detalhe = ''
        if cede:
            anterior.fim -= cede
            detalhe = f'; a fala {anterior.numero} passa a terminar em {_tempo_srt(anterior.fim)}'
        motivo = ('' if precisa == MINIMO_DE_MS_DA_FALA
                  else f', o que a divisão em {precisa // MINIMO_DE_MS_DA_FALA} pede')
        avisos.append((fala.numero, f'fala {fala.numero} durava {_segundos(duracao)} s: estendida '
                                    f'para {_segundos(precisa)} s{motivo} ({_tempo_srt(fala.inicio)} '
                                    f'--> {_tempo_srt(fala.fim)}{detalhe})'))


def _dividir_falas_longas(falas, problemas, avisos):
    """FM3: a fala com mais de 42 caracteres vira pedaços de até 42, com a
    duração dela repartida entre eles (repartir_duracao) — cada um com
    pelo menos 1,5 s; se a divisão não cabe (ou uma palavra passa de 42),
    é problema. `problemas` e `avisos` recebem (número da fala, texto)."""
    for fala in falas:
        if len(fala.texto) <= MAXIMO_DE_CARACTERES_DA_FALA:
            continue
        pedacos = dividir_fala(fala.texto)
        duracao = fala.fim - fala.inicio
        duracoes = repartir_duracao(duracao, [len(p) for p in pedacos]) if pedacos else None
        cabecalho = f'fala {fala.numero} com {len(fala.texto)} caracteres'
        if duracoes is None:
            if pedacos is None:
                motivo = 'não dá para dividir (uma palavra maior que o máximo)'
            else:
                motivo = (f'dividida em {len(pedacos)} pedaços, cada um precisaria de '
                          f'{_segundos(MINIMO_DE_MS_DA_FALA)} s, e a fala tem {_segundos(duracao)} s')
                if fala.sem_espaco:
                    motivo += ' — e não há espaço em volta para estendê-la'
            problemas.append((fala.numero, f'{cabecalho} ("{fala.texto}") — o máximo é '
                                           f'{MAXIMO_DE_CARACTERES_DA_FALA}, e {motivo}'))
            continue
        inicio, fala.pedacos = fala.inicio, []
        for pedaco, ms in zip(pedacos, duracoes):
            fala.pedacos.append((inicio, inicio + ms, pedaco))
            inicio += ms
        avisos.append((fala.numero, f'{cabecalho} dividida em {len(pedacos)}: ' + ' | '.join(
            f'{_tempo_srt(a)} --> {_tempo_srt(b)} "{t}"' for a, b, t in fala.pedacos)))


def _srt_de(falas):
    """O SRT das falas (as divididas como falas seguidas), renumerado, uma
    linha de texto por fala, LF, sem BOM."""
    linhas, n = [], 0
    for fala in falas:
        for inicio, fim, texto in fala.pedacos or [(fala.inicio, fala.fim, fala.texto)]:
            n += 1
            linhas += [str(n), f'{_tempo_srt(inicio)} --> {_tempo_srt(fim)}', texto, '']
    return '\n'.join(linhas)


def ajustar_legenda(texto, duracao_do_video):
    """(problemas, avisos, o SRT ajustado — ou None quando nada mudou) de
    uma legenda. O app lê o SRT pelo SubRipCaptionFile do video_player
    2.14: ele PARA no primeiro bloco com menos de 3 linhas (uma linha em
    branco a mais no meio basta), lança no bloco que não começa por número
    (o app então toca sem legenda) e pula em silêncio a fala de tempo fora
    do formato. A tela mostra uma fala por vez, numa linha só: até 42
    caracteres, pelo menos 1,5 s, dentro do vídeo e sem sobrepor a
    anterior. O que dá para ajustar sem mexer no sentido é ajustado e sai
    como aviso: a fala que dura menos do que precisa é estendida (FM4,
    _estender_falas) e a fala longa é dividida (FM3,
    _dividir_falas_longas). O resto é problema (lista vazia = passa)."""
    if texto.startswith('﻿'):
        texto = texto[1:]
    blocos = _blocos_como_o_app(texto)
    problemas, falas = [], []
    contagem = fim_anterior = 0
    for i, bloco in enumerate(blocos):
        if not bloco:
            if any(blocos[i + 1:]):
                onde = f'a mais depois da fala {contagem}' if contagem else 'antes da primeira fala'
                problemas.append(f'linha em branco {onde} — o app para de ler a legenda ali')
            continue
        contagem += 1
        if len(bloco) < 3:
            problemas.append(f'fala {contagem} com {len(bloco)} linha(s) — cada fala tem número, '
                             'tempo e uma linha de texto; o app para de ler a legenda ali')
            continue
        numero, tempo, texto_da_fala = bloco[0].strip(), bloco[1].strip(), bloco[2:]
        if not re.fullmatch(r'[0-9]+', numero):
            problemas.append(f'fala {contagem}: o bloco não começa por número ("{numero}") — o app '
                             'não abre a legenda')
        if len(texto_da_fala) != 1:
            problemas.append(f'fala {contagem} com {len(texto_da_fala)} linhas — uma linha só por '
                             'fala')
        linha = ' '.join(t.strip() for t in texto_da_fala)
        m = _TEMPO_SRT.fullmatch(tempo)
        if not m:
            problemas.append(f'fala {contagem}: tempo "{tempo}" fora do formato '
                             'HH:MM:SS,mmm --> HH:MM:SS,mmm — o app pula a fala')
            continue
        g = [int(x) for x in m.groups()]
        inicio = ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + g[3]
        fim = ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + g[7]
        if duracao_do_video is not None and fim > round(duracao_do_video * 1000):
            problemas.append(f'fala {contagem} termina em {_tempo_srt(fim)}, depois do fim do vídeo '
                             f'({_tempo_srt(round(duracao_do_video * 1000))})')
        if inicio < fim_anterior:
            problemas.append(f'fala {contagem} começa em {_tempo_srt(inicio)}, antes do fim da fala '
                             f'anterior ({_tempo_srt(fim_anterior)})')
        fim_anterior = max(fim_anterior, fim)
        falas.append(_Fala(contagem, inicio, fim, linha))
    if not contagem:
        problemas.append('nenhuma fala')
    # Os ajustes, fala a fala: primeiro o tempo (FM4), depois a divisão
    # (FM3), que reparte o tempo já estendido. As mensagens saem na ordem
    # das falas. O SRT ajustado só sai quando não há problema (com
    # problema, nada vai ser escrito).
    das_falas, avisos = [], []
    fim_do_video = round(duracao_do_video * 1000) if duracao_do_video is not None else None
    _estender_falas(falas, fim_do_video, das_falas, avisos)
    _dividir_falas_longas(falas, das_falas, avisos)
    problemas += [p for _, p in sorted(das_falas, key=lambda par: par[0])]
    avisos = [a for _, a in sorted(avisos, key=lambda par: par[0])]
    return problemas, avisos, _srt_de(falas) if avisos and not problemas else None


def conferir_legenda(texto, duracao_do_video, avisos=None):
    """Só os problemas da legenda (ajustar_legenda); os avisos vão para a
    lista `avisos`, se vier uma."""
    problemas, novos, _ = ajustar_legenda(texto, duracao_do_video)
    if avisos is not None:
        avisos.extend(novos)
    return problemas


def _conferir_textos(rotulo, cap):
    problemas = []
    for campo in CAMPOS_DE_TEXTO:
        valor = cap.get(campo)
        if not isinstance(valor, str) or not valor.strip():
            problemas.append(f'{rotulo}: sem "{campo}"')
    # Medidos aparados, como o app (que apara) e o lint (que mede o aparado).
    versiculo = cap.get('versiculo')
    if isinstance(versiculo, str) and len(versiculo.strip()) > MAXIMO_DE_CARACTERES_DO_VERSICULO:
        problemas.append(f'{rotulo}: versículo com {len(versiculo.strip())} caracteres — o máximo '
                         f'é {MAXIMO_DE_CARACTERES_DO_VERSICULO} (cabe na imagem de partilha)')
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


def conferir_entrega(pasta, limite_de_bytes=LIMITE_DE_BYTES, avisos=None):
    """(Entrega ou None, [problemas]). A Entrega vem sempre que o id, o
    início e os capítulos dão para ler — mesmo com problemas, para as outras
    conferências (o índice) também listarem os delas. `limite_de_bytes` é
    parâmetro para o teste não precisar de um vídeo de 25 MB. O que passa
    mas merece aviso (o yuvj420p, R8-M; a fala dividida, FM3; a fala
    estendida, FM4) vai para a lista `avisos`, se vier uma — nunca para os
    problemas."""
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
        videos, duracoes, shas = {}, {}, {}
        for tradicao in TRADICOES:
            video = pasta / f'{nn}-{tradicao}.mp4'
            if not video.exists():
                problemas.append(f'{rotulo}: falta {video.name}')
                continue
            videos[tradicao] = video
            shas[tradicao] = sha256_de(video)
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
            if medida['pix_fmt'] == PIX_FMT_FAIXA_CHEIA:
                if avisos is not None:
                    avisos.append(f'{rotulo} ({video.name}): pix_fmt {PIX_FMT_FAIXA_CHEIA} — o 4:2:0 '
                                  'de 8 bits com a faixa cheia de cor: passa (a cor pode variar um '
                                  f'pouco num aparelho que ignore a faixa); {EXPORTAR_EM_YUV420P}')
            elif medida['pix_fmt'] != PIX_FMT_DO_VIDEO:
                problemas.append(f'{rotulo} ({video.name}): pix_fmt {medida["pix_fmt"] or "(nenhum)"}'
                                 f' — tem de ser {PIX_FMT_DO_VIDEO} (ou {PIX_FMT_FAIXA_CHEIA}): o h264 '
                                 'de 8 bits 4:2:0 que todo Android toca; 10 bits, 4:2:2 e 4:4:4 não')
            if (medida['largura'], medida['altura']) != TAMANHO_DO_VIDEO:
                problemas.append(f'{rotulo} ({video.name}): {medida["largura"]}x{medida["altura"]}'
                                 f' — tem de ser {TAMANHO_DO_VIDEO[0]}x{TAMANHO_DO_VIDEO[1]}')
            if medida['duracao'] is None:
                problemas.append(f'{rotulo} ({video.name}): o ffprobe não deu a duração')
                continue
            duracoes[tradicao] = medida['duracao']
            if duracao_ok and passa_da_folga(medida['duracao'], duracao, FOLGA_DA_DURACAO):
                problemas.append(f'{rotulo} ({video.name}): {_ms(medida["duracao"])} s, mas '
                                 f'duracaoS = {duracao} (folga de {_casas(FOLGA_DA_DURACAO)} s)')
        if len(shas) == len(TRADICOES) and shas['catolico'] == shas['evangelico']:
            problemas.append(f'{rotulo}: {nn}-catolico.mp4 e {nn}-evangelico.mp4 são o mesmo arquivo '
                             '(mesmo sha256) — a versão católica é do bispo e a evangélica do '
                             'pastor: entrega trocada')
        if len(duracoes) == len(TRADICOES):
            a, b = duracoes['catolico'], duracoes['evangelico']
            if passa_da_folga(a, b, FOLGA_ENTRE_VERSOES):
                problemas.append(f'{rotulo}: as versões têm {_ms(a)} s (católica) e {_ms(b)} s '
                                 f'(evangélica) — diferem {_ms(abs(a - b))} s; o máximo é '
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
        legenda_ajustada = None
        if legenda.exists():
            try:
                texto = legenda.read_bytes().decode('utf-8')
            except UnicodeDecodeError:
                problemas.append(f'{rotulo} ({legenda.name}): não está em UTF-8')
            else:
                p, a, legenda_ajustada = ajustar_legenda(
                    texto, min(duracoes.values()) if duracoes else None)
                problemas += [f'{rotulo} ({legenda.name}): {x}' for x in p]
                if avisos is not None:
                    avisos += [f'{rotulo} ({legenda.name}): {x}' for x in a]
        else:
            legenda = None
        lista.append(CapituloDaEntrega(n=i, dados=cap, videos=videos, capa=capa, legenda=legenda,
                                       shas=shas, legenda_ajustada=legenda_ajustada))

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


def conferir_indice(indice):
    """Os problemas do índice FINAL (o que vai ser gravado: as temporadas que
    já estavam, com a nova no lugar da versão anterior dela) pelas regras do
    app (IndiceDeTemporadas.fromJson), que recusa o índice INTEIRO por
    qualquer uma: a base "videos" terminada em /; cada temporada com id
    t<número>, arquivo novela/<id>.json, capítulos ≥ 1 e fim = início +
    capítulos − 1; os ids únicos; nenhuma sobreposição de datas."""
    problemas = []
    base = indice.get('videos')
    if not isinstance(base, str) or not base.endswith('/') or not urlparse(base).path.endswith('/'):
        problemas.append(f'índice final: a base "videos" ({base}) não termina em /')
    temporadas = indice.get('temporadas')
    if not isinstance(temporadas, list):
        return problemas + ['índice final: sem a lista "temporadas"']
    ids = [r.get('id') if isinstance(r, dict) else None for r in temporadas]
    for id_ in sorted({i for i in ids if ids.count(i) > 1}, key=str):
        problemas.append(f'índice final: o id {id_} aparece {ids.count(id_)} vezes — cada temporada '
                         'tem um id só (todas apontariam o mesmo novela/<id>.json)')
    vistas = []
    for r in temporadas:
        if not isinstance(r, dict):
            problemas.append('índice final: uma temporada não é um objeto')
            continue
        id_, capitulos = r.get('id'), r.get('capitulos')
        inicio, fim = data_valida(r.get('inicio')), data_valida(r.get('fim'))
        if not isinstance(id_, str) or not ID_DE_TEMPORADA.fullmatch(id_):
            problemas.append(f'índice final: id "{id_}" fora do formato t<número>')
            continue
        if r.get('arquivo') != f'novela/{id_}.json':
            problemas.append(f'índice final: {id_} com arquivo "{r.get("arquivo")}" — tem de ser '
                             f'novela/{id_}.json')
        if not isinstance(capitulos, int) or isinstance(capitulos, bool) or capitulos < 1:
            problemas.append(f'índice final: {id_} com capitulos "{capitulos}" — um inteiro ≥ 1')
            continue
        if inicio is None or fim is None:
            problemas.append(f'índice final: {id_} com início "{r.get("inicio")}" e fim '
                             f'"{r.get("fim")}" — datas AAAA-MM-DD que existam')
            continue
        esperado = inicio + timedelta(days=capitulos - 1)
        if fim != esperado:
            problemas.append(f'índice final: {id_} termina em {fim}, mas {capitulos} capítulo(s) a '
                             f'partir de {inicio} terminam em {esperado}')
        for outro, o_inicio, o_fim in vistas:
            if not (inicio > o_fim or fim < o_inicio):
                problemas.append(f'índice final: as datas de {outro} ({o_inicio} a {o_fim}) '
                                 f'sobrepõem as de {id_} ({inicio} a {fim}) — o app recusaria o '
                                 'índice inteiro')
        vistas.append((id_, inicio, fim))
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


def resolver_base(videos_base, indice, url_publica, prefixo):
    """(a base `videos` terminada em /, [problemas]): --videos-base, senão a
    do índice existente, senão a Public Development URL (a das chaves do R2,
    já lidas; na simulação, que nunca lê o arquivo de chaves, o marcador
    MARCADOR_DA_URL_PUBLICA) mais o prefixo. Uma base que não termina no
    prefixo do R2 mandaria o app pedir os vídeos fora de onde eles sobem."""
    if videos_base:
        base, origem = videos_base, '--videos-base'
    elif indice and indice.get('videos'):
        base, origem = indice['videos'], 'o índice existente'
    elif url_publica == MARCADOR_DA_URL_PUBLICA:
        return f'{MARCADOR_DA_URL_PUBLICA}/{prefixo}', []
    elif url_publica:
        base, origem = f'{url_publica.rstrip("/")}/{prefixo}', 'a Public Development URL do R2'
    else:
        return None, ['sem a base "videos": não veio --videos-base, o índice ainda não existe e o '
                      'arquivo de chaves do R2 (--r2) não deu a "Public Development URL"']
    if not base.endswith('/'):
        base += '/'
    partes = urlparse(base)
    if partes.scheme not in ('http', 'https') or not partes.netloc:
        return None, [f'a base "videos" ({base}, de {origem}) não é uma URL http(s)']
    if prefixo and not partes.path.endswith('/' + prefixo):
        return None, [f'a base "videos" ({base}, de {origem}) não termina no prefixo do R2 '
                      f'({prefixo}): o app pediria os vídeos fora de onde eles sobem']
    if not prefixo and 'teste/' in base.lower():
        return None, [f'a base "videos" ({base}, de {origem}) é de teste (tem "teste/"), mas a '
                      'publicação é de produção (sem --r2-prefixo): o app pediria os vídeos na '
                      'pasta de teste do balde']
    return base, []


def avisos_da_base(base, prefixo):
    """O que não recusa, mas o Gregory precisa ver: em produção (sem
    prefixo), a base *.r2.dev — a Public Development URL, que a Cloudflare
    limita. Hoje ela ainda é a base real, até o DNS do domínio próprio
    (video.manhadefe.com.br) ir para a Cloudflare."""
    host = (urlparse(base).hostname or '').lower()
    if not prefixo and (host == 'r2.dev' or host.endswith('.r2.dev')):
        return [f'a base "videos" ({base}) é a Public Development URL do R2 (*.r2.dev), que a '
                'Cloudflare limita — serve até o domínio próprio (video.manhadefe.com.br) estar no '
                'ar; aí, publique com --videos-base apontando para ele']
    return []


def conferir_raiz_da_simulacao(midia, app=None):
    """--simular escreve de verdade (JSONs, capas, legendas): exige --midia
    numa pasta temporária — nunca o repositório real, o repositório do app
    (REPOSITORIO_DO_APP, a pasta-irmã ou o --app) nem qualquer pasta com
    .git (ela ou uma acima dela): rodando o script de uma cópia, o
    "repositório real" dele é a cópia, e um gerar_manifesto ou um commit
    depois levaria a temporada simulada ao app. Roda antes de qualquer outra
    conferência e de qualquer escrita."""
    if not midia:
        sys.exit('--simular exige --midia apontando uma pasta temporária: a simulação escreve '
                 'os JSONs, as capas e as legendas de verdade, e nunca no repositório real')
    if _dentro_de(midia, MIDIA_PADRAO):
        sys.exit(f'--simular com --midia no repositório real ({MIDIA_PADRAO}): aponte uma pasta '
                 'temporária fora dele — a simulação escreve os JSONs, as capas e as legendas')
    for repositorio in (REPOSITORIO_DO_APP, APP_PADRAO, app):
        if repositorio and _dentro_de(midia, repositorio):
            sys.exit(f'--simular com --midia no repositório do app ({repositorio}): aponte uma '
                     'pasta temporária — a simulação escreve os JSONs, as capas e as legendas')
    repositorio = _repositorio_git_de(midia)
    if repositorio is not None:
        sys.exit(f'--simular com --midia dentro de um repositório git ({repositorio} tem .git): '
                 'aponte uma pasta temporária fora de qualquer repositório — a simulação escreve '
                 'os JSONs, as capas e as legendas')


def _dentro_de(pasta, raiz):
    a = os.path.normcase(str(Path(pasta).resolve()))
    b = os.path.normcase(str(Path(raiz).resolve()))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


TRAVA = '.publicando.trava'


def tomar_trava(midia):
    """A trava da publicação REAL: <midia>/.publicando.trava, criada com
    O_EXCL, com a data/hora e o PID dentro (R8-N). Uma publicação por vez
    nesta raiz de mídia: o HEAD logo antes de cada envio só estreita a
    janela (o objeto só aparece no R2 quando o PUT termina), não impede
    duas publicações ao mesmo tempo — quem impede é a trava. Devolve (o
    caminho, None) ou (None, por que recusou); recusar não toca em nada."""
    caminho = Path(midia) / TRAVA
    if not Path(midia).is_dir():
        return None, f'a raiz de mídia {midia} não existe (--midia)'
    try:
        descritor = os.open(caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            de_quando = caminho.read_text(encoding='utf-8').strip()
        except OSError:
            de_quando = ''
        if not de_quando:
            try:
                de_quando = f'{datetime.fromtimestamp(caminho.stat().st_mtime):%Y-%m-%d %H:%M:%S}'
            except OSError:
                de_quando = 'quando não se sabe'
        return None, (f'outra publicação está rodando nesta raiz de mídia — a trava {caminho} é de '
                      f'{de_quando}. Se nenhuma publicação estiver rodando (uma que caiu sem limpar), '
                      'basta apagar esse arquivo e rodar de novo; nada foi tocado')
    except OSError as e:
        return None, f'não deu para criar a trava {caminho} ({type(e).__name__}: {e})'
    # Daqui em diante a trava existe e é desta publicação: toda saída que
    # não a devolve a apaga (F15) — uma trava vazia, de ninguém, faria a
    # rodada seguinte recusar e mandar apagar à mão.
    try:
        escrever_trava(descritor, f'{datetime.now():%Y-%m-%d %H:%M:%S} PID {os.getpid()}' + chr(10))
    except OSError as e:
        soltar_trava(caminho)
        return None, (f'não deu para escrever a trava {caminho} ({type(e).__name__}: {e}); ela foi '
                      'apagada e nada foi tocado')
    except BaseException:
        # Um Ctrl+C entre a criação e a devolução: a trava não pode ficar.
        soltar_trava(caminho)
        raise
    return caminho, None


def escrever_trava(descritor, texto):
    """O conteúdo da trava, pelo descritor que o O_EXCL deu (fechado aqui,
    também na falha). É o ponto que o teste troca por uma escrita que falha
    ou é interrompida."""
    with os.fdopen(descritor, 'w', encoding='utf-8', newline='') as f:
        f.write(texto)


def soltar_trava(caminho):
    """Apaga a trava desta publicação (no finally: também na falha)."""
    try:
        caminho.unlink()
    except FileNotFoundError:
        pass


def _repositorio_git_de(pasta):
    """A pasta que tem .git (o diretório, ou o arquivo de um worktree) e
    contém `pasta` — ela mesma ou uma acima dela —, ou None."""
    atual = Path(pasta).resolve()
    for candidata in (atual, *atual.parents):
        if (candidata / '.git').exists():
            return candidata
    return None


# ---------------------------------------------------------------------------
# O caminho real: R2, Dart e a voz (os pontos que os testes trocam por dublês)
# ---------------------------------------------------------------------------

def rodar(cmd, cwd=None):
    """Roda um comando com a saída direto no terminal; devolve o código."""
    sys.stdout.flush()
    return subprocess.run([str(c) for c in cmd],
                          cwd=None if cwd is None else str(cwd)).returncode


def criar_cliente_r2(chaves):
    """O cliente S3 do R2 como na documentação da Cloudflare (region_name
    'auto'). Os checksums opcionais que o boto3 manda por padrão desde a
    1.36 ficam só para quando a operação os exige: serviços compatíveis com
    S3 já recusaram esses cabeçalhos, e este envio não tem como ser provado
    contra o R2 antes do primeiro uso real."""
    import boto3  # noqa: PLC0415 — só no caminho real
    from botocore.config import Config  # noqa: PLC0415
    return boto3.client(service_name='s3', endpoint_url=chaves.endpoint,
                        aws_access_key_id=chaves.access_key_id,
                        aws_secret_access_key=chaves.secret_access_key,
                        region_name='auto',
                        config=Config(request_checksum_calculation='when_required',
                                      response_checksum_validation='when_required'))


def localizar_dart():
    for candidato in (os.environ.get('DART'), shutil.which('dart'), str(DART_PADRAO)):
        if candidato and Path(candidato).exists():
            return candidato
    return None


MARCA_DO_ENDPOINT = '<endpoint do R2>'
# Qualquer host da API S3 do R2 (o id da conta é o subdomínio), mesmo de
# outra conta ou com o balde na frente.
_HOST_DO_R2 = re.compile(r'[A-Za-z0-9.-]*\.r2\.cloudflarestorage\.com', re.IGNORECASE)
LIMITE_DA_MENSAGEM = 300


def limpar_mensagem(texto, chaves):
    """O texto sem nada que identifique a conta do R2: o endpoint inteiro, o
    host dele, o id da conta e as chaves de acesso viram marcadores
    ("<endpoint do R2>", "<conta>", "<chave>"), em qualquer caixa; e
    qualquer outro host *.r2.cloudflarestorage.com que sobrar também. Toda
    mensagem que vem do R2, do botocore ou da rede passa por aqui antes de
    ir à tela (R8-A) — `chaves` None: só a troca genérica."""
    trocas = []
    if chaves is not None:
        endpoint = (chaves.endpoint or '').rstrip('/')
        host = urlparse(endpoint).hostname or ''
        trocas = [(endpoint, MARCA_DO_ENDPOINT), (host, MARCA_DO_ENDPOINT),
                  (host.split('.')[0], '<conta>'),
                  (chaves.access_key_id, '<chave>'), (chaves.secret_access_key, '<chave>')]
    for valor, marcador in trocas:
        if valor:
            texto = re.sub(re.escape(valor), marcador, texto, flags=re.IGNORECASE)
    return _HOST_DO_R2.sub(MARCA_DO_ENDPOINT, texto)


def _codigo_do_erro(erro):
    """O Error.Code de um ClientError do botocore ('404', 'AccessDenied'),
    ou None — só o do próprio erro."""
    resposta = getattr(erro, 'response', None)
    if not isinstance(resposta, dict) or not isinstance(resposta.get('Error'), dict):
        return None
    codigo = resposta['Error'].get('Code')
    return str(codigo) if codigo else None


def _codigo_na_cadeia(erro):
    """O Error.Code do erro ou de um que ele embrulha: o boto3 lança o erro
    do envio como S3UploadFailedError ("Failed to upload <caminho local> to
    <balde>/<chave>: ..."), com o ClientError no __context__ — e, com o
    caminho da entrega longo, o código do texto cairia depois do corte."""
    vistos = set()
    while erro is not None and id(erro) not in vistos:
        vistos.add(id(erro))
        codigo = _codigo_do_erro(erro)
        if codigo:
            return codigo
        erro = erro.__cause__ or erro.__context__
    return None


def descrever_erro(erro, chaves):
    """O que vai à tela de um erro do R2, do botocore ou da rede: o tipo (e o
    Error.Code do ClientError, dele ou do que ele embrulha) e a mensagem
    LIMPA — limpa antes de cortada, para nenhum pedaço do endpoint escapar
    do corte."""
    codigo = _codigo_na_cadeia(erro)
    nome = type(erro).__name__ + (f' ({codigo})' if codigo else '')
    return limpar_mensagem(f'{nome}: {erro}', chaves)[:LIMITE_DA_MENSAGEM]


def _nao_existe(erro):
    # Só o código do PRÓPRIO erro do HEAD: um 404 no meio da cadeia não é
    # "o objeto não existe".
    return _codigo_do_erro(erro) in ('404', 'NoSuchKey', 'NotFound')


def _cabeca(cliente, balde, chave):
    try:
        return cliente.head_object(Bucket=balde, Key=chave)
    except Exception as e:  # noqa: BLE001 — o 404 é resposta, o resto sobe
        if _nao_existe(e):
            return None
        raise


def _estado_no_r2(cliente, chave, balde=BALDE):
    """(bytes, sha256 dos metadados) do objeto no balde, ou None se ele não
    existe. Objeto sem o sha256 nos metadados volta com None no lugar dele —
    e nunca é "o mesmo conteúdo"."""
    cabeca = _cabeca(cliente, balde, chave)
    if cabeca is None:
        return None
    return cabeca.get('ContentLength'), (cabeca.get('Metadata') or {}).get('sha256')


# ---------------------------------------------------------------------------
# A chave de cada vídeo no R2: nunca sobrescrever conteúdo diferente (R8-B)
# ---------------------------------------------------------------------------

NOVO, JA_ESTAVA, TROCADO = 'novo', 'já estava', 'trocado (chave nova)'
_CHAVE_DE_VIDEO = re.compile(r'video/(t\d+)/(\d{2})-(catolico|evangelico)(?:-([0-9a-f]{8}))?\.mp4',
                             re.ASCII)


@dataclass
class Video:
    """Um vídeo da entrega e o destino dele: `chave` é a chave de mídia (o
    `arquivo` do JSON; no R2, prefixo + chave); `sobe` diz se ela precisa
    subir; no TROCADO, `velha` é a chave fixa, que fica intocada."""
    capitulo: CapituloDaEntrega
    tradicao: str
    arquivo: Path
    bytes: int
    sha256: str
    chave: str = ''
    estado: str = ''
    sobe: bool = False
    velha: str = ''
    recusada: str = ''     # a chave fixa com OUTRO conteúdo, quando o plano recusa


def videos_da_entrega(entrega):
    """Os vídeos, na ordem dos capítulos (católico, evangélico), com o
    tamanho e o sha256 medidos na conferência."""
    return [Video(capitulo=c, tradicao=t, arquivo=c.videos[t], bytes=c.videos[t].stat().st_size,
                  sha256=c.shas[t]) for c in entrega.capitulos for t in TRADICOES]


def chave_do_video(entrega, capitulo, tradicao):
    """A chave FIXA do vídeo: video/<t>/<nn>-<tradicao>.mp4."""
    return f'video/{entrega.id}/{capitulo.nn}-{tradicao}.mp4'


def chave_versionada(entrega, capitulo, tradicao, sha256):
    """A chave do vídeo TROCADO: video/<t>/<nn>-<tradicao>-<sha8>.mp4, com
    sha8 = os 8 primeiros caracteres hex minúsculos do sha256 do arquivo (o
    app confere que batem com o sha256 que o próprio JSON declara)."""
    return f'video/{entrega.id}/{capitulo.nn}-{tradicao}-{sha256[:8].lower()}.mp4'


def videos_publicados(midia, id_):
    """{(n, tradição): {arquivo, bytes, sha256}} do novela/<t>.json JÁ
    publicado na raiz de mídia — só as chaves de vídeo do capítulo e da
    tradição certos (a fixa ou uma versionada); {} se ele não existe ou não
    dá para ler (ele vai ser regravado de qualquer jeito)."""
    try:
        dados = json.loads((Path(midia) / 'novela' / f'{id_}.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return _videos_do_json(dados, id_)


def videos_no_ultimo_commit(midia, id_):
    """O mesmo de videos_publicados, do novela/<t>.json do ÚLTIMO COMMIT da
    raiz de mídia (git show HEAD:./novela/<t>.json) — o que os aparelhos
    podem ter, mesmo que a pasta já não o tenha; {} fora de um repositório
    git, sem commit ou sem o arquivo nele."""
    try:
        r = subprocess.run(['git', '-C', str(midia), 'show', f'HEAD:./novela/{id_}.json'],
                           capture_output=True)
    except OSError:
        return {}
    if r.returncode != 0:
        return {}
    try:
        dados = json.loads(r.stdout.decode('utf-8-sig'))
    except (ValueError, UnicodeDecodeError):
        return {}
    return _videos_do_json(dados, id_)


def _videos_do_json(dados, id_):
    """{(n, tradição): {arquivo, bytes, sha256}} de um novela/<t>.json já
    lido: só as chaves de vídeo do capítulo e da tradição certos."""
    capitulos = dados.get('capitulos') if isinstance(dados, dict) else None
    publicados = {}
    for cap in capitulos if isinstance(capitulos, list) else []:
        if not isinstance(cap, dict) or not isinstance(cap.get('video'), dict):
            continue
        n = cap.get('n')
        for tradicao in TRADICOES:
            video = cap['video'].get(tradicao)
            arquivo = video.get('arquivo') if isinstance(video, dict) else None
            m = _CHAVE_DE_VIDEO.fullmatch(arquivo) if isinstance(arquivo, str) else None
            if (m and m.group(1) == id_ and isinstance(n, int) and not isinstance(n, bool)
                    and int(m.group(2)) == n and m.group(3) == tradicao):
                publicados[n, tradicao] = {'arquivo': arquivo, 'bytes': video.get('bytes'),
                                           'sha256': video.get('sha256')}
    return publicados


def r2_segundo_o_json_publicado(publicados):
    """O `consultar` da simulação, que não toca o R2: o que o novela/<t>.json
    publicado diz que está lá — cada chave com o tamanho e o sha256 dele; e
    a chave fixa de um vídeo que ele já dá numa versionada existe com OUTRO
    conteúdo (foi por isso que a versionada nasceu)."""
    conhecidos = {}
    for video in publicados.values():
        conhecidos[video['arquivo']] = (video.get('bytes'), video.get('sha256'))
    for video in publicados.values():
        m = _CHAVE_DE_VIDEO.fullmatch(video['arquivo'])
        if m.group(4):
            conhecidos.setdefault(f'video/{m.group(1)}/{m.group(2)}-{m.group(3)}.mp4', (None, None))
    return conhecidos.get


def planejar_videos(entrega, videos, publicados, consultar, substituir, prefixo=''):
    """Escolhe a chave de cada vídeo SEM nunca sobrescrever no R2 um objeto
    com outro conteúdo, com ou sem opção — só consultando:
      1. a chave que o novela/<t>.json já publicado dá para o capítulo e a
         tradição, se o objeto lá é este (mesmo tamanho e sha256): já estava;
      2. senão a chave fixa video/<t>/<nn>-<tradicao>.mp4 — ausente: novo;
         com este conteúdo: já estava;
      3. senão (a fixa tem outro conteúdo): trocado. Sem `substituir`, é uma
         RECUSA (chave, capítulo e data); com ele, a chave versionada
         ...-<sha8>.mp4 — ausente: sobe; com este conteúdo: reusa; com
         outro: problema. O objeto velho fica intocado: o aparelho com o
         JSON velho baixa o velho, o com o novo baixa o novo, sem depender
         de cache da borda.
    `consultar(chave)` -> (bytes, sha256) do objeto em prefixo + chave, ou
    None se ele não existe. Preenche os `videos` e devolve (problemas,
    recusas)."""
    vistos = {}

    def no_r2(chave):
        if chave not in vistos:
            vistos[chave] = consultar(chave)
        return vistos[chave]

    problemas, recusas = [], []
    for v in videos:
        este = (v.bytes, v.sha256)
        anterior = (publicados.get((v.capitulo.n, v.tradicao)) or {}).get('arquivo')
        if anterior and no_r2(anterior) == este:
            v.chave, v.estado, v.sobe = anterior, JA_ESTAVA, False
            continue
        fixa = chave_do_video(entrega, v.capitulo, v.tradicao)
        la = no_r2(fixa)
        if la is None:
            v.chave, v.estado, v.sobe = fixa, NOVO, True
        elif la == este:
            v.chave, v.estado, v.sobe = fixa, JA_ESTAVA, False
        elif not substituir:
            v.recusada = fixa
            recusas.append(f'{prefixo}{fixa} (cap. {v.capitulo.n}, '
                           f'{entrega.id_do_capitulo(v.capitulo)}, {v.capitulo.dados["data"]})')
        else:
            nova = chave_versionada(entrega, v.capitulo, v.tradicao, v.sha256)
            la_nova = no_r2(nova)
            if la_nova is not None and la_nova != este:
                problemas.append(f'{prefixo}{nova}: já está no R2 com outro conteúdo — nada é '
                                 'sobrescrito; confira o objeto à mão antes de publicar')
                continue
            v.chave, v.estado, v.sobe, v.velha = nova, TROCADO, la_nova is None, fixa
    return problemas, recusas


def consultar_url_publica(url, tempo=20):
    """O Content-Length que a URL PÚBLICA dá num HEAD (None se ela não dá
    nenhum); erro HTTP ou de rede sobe. É o ponto que os testes trocam por
    dublê."""
    pedido = urllib.request.Request(url, method='HEAD',
                                    headers={'User-Agent': 'manhadefe-publicar-temporada'})
    with urllib.request.urlopen(pedido, timeout=tempo) as resposta:  # noqa: S310 — só http(s)
        tamanho = resposta.headers.get('Content-Length')
    return int(tamanho) if tamanho is not None and tamanho.strip().isdigit() else None


def conferir_pela_url_publica(videos, base, chaves):
    """[problemas] de cada vídeo — o que subiu e o que já estava — pela URL
    que o app vai pedir, <base><chave>: o HEAD tem de dar o Content-Length =
    bytes. Pega a base que não serve o objeto (outro prefixo, outro
    domínio, o balde sem acesso público). O erro sai limpo (R8-A)."""
    problemas = []
    for v in videos:
        url = base + v.chave
        try:
            tamanho = consultar_url_publica(url)
        except Exception as e:  # noqa: BLE001 — erro de rede: limpo, nunca cru
            problemas.append(limpar_mensagem(f'{url}: {descrever_erro(e, chaves)}', chaves))
            continue
        if tamanho != v.bytes:
            dado = 'nenhum' if tamanho is None else _milhar(tamanho)
            problemas.append(limpar_mensagem(f'{url}: o HEAD deu Content-Length {dado} — o vídeo '
                                             f'tem {_milhar(v.bytes)} bytes', chaves))
    return problemas


def subir_videos(cliente, videos, prefixo='', balde=BALDE):
    """Sobe os vídeos que o plano manda subir (`sobe`), com o sha256 nos
    metadados, e confere cada um depois (HEAD: o mesmo tamanho e sha256).
    O plano só manda subir para chave ausente, e a ausência é conferida de
    novo logo antes do envio — isso ESTREITA a janela, não impede a
    corrida: o objeto só aparece no R2 quando o PUT termina. Quem impede
    duas publicações ao mesmo tempo é a trava (tomar_trava). Nada é apagado
    (esta ferramenta não apaga no R2)."""
    for v in videos:
        if not v.sobe:
            continue
        chave = prefixo + v.chave
        if _estado_no_r2(cliente, chave, balde) is not None:
            raise RuntimeError(f'{chave}: apareceu no R2 durante a publicação — nada foi '
                               'sobrescrito; rode de novo')
        cliente.upload_file(str(v.arquivo), balde, chave,
                            ExtraArgs={'ContentType': 'video/mp4', 'Metadata': {'sha256': v.sha256}})
        if _estado_no_r2(cliente, chave, balde) != (v.bytes, v.sha256):
            raise RuntimeError(f'{chave}: depois do envio, o R2 não mostra o mesmo tamanho e sha256')


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


def temporada_no_formato_do_app(entrega, videos):
    """O <t>.json que Temporada.fromJson lê. `videos`: {(n, tradição):
    Video}, com a chave que o plano escolheu (a fixa ou a versionada)."""
    capitulos = []
    for c in entrega.capitulos:
        id_ = entrega.id_do_capitulo(c)
        saida = {'id': id_, 'n': c.n, 'data': c.dados['data']}
        for campo in (*CAMPOS_DE_TEXTO, 'duracaoS'):
            saida[campo] = c.dados[campo]
        saida['capa'] = f'assets/images/cartoes/{id_}.webp'
        if c.legenda is not None:
            saida['legenda'] = f'novela/{id_}.srt'
        saida['video'] = {t: {'arquivo': videos[c.n, t].chave, 'bytes': videos[c.n, t].bytes,
                              'sha256': videos[c.n, t].sha256}
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


_DO_CAPITULO = re.compile(r'(t\d+)c(\d+)\.(webp|srt|m4a|m4a\.origem)')


def limpar_sobras(midia, entrega):
    """Apaga o que uma versão anterior DESTA temporada deixou e a nova não
    tem: capa e voz (com o registro .origem dela) de capítulo que sumiu,
    legenda que saiu. Nada de outra temporada nem de outro conteúdo é
    tocado."""
    com_legenda = {c.n for c in entrega.capitulos if c.legenda is not None}
    total = len(entrega.capitulos)
    candidatos = [*(midia / 'imagens').glob(f'{entrega.id}c*.webp'),
                  *(midia / 'novela').glob(f'{entrega.id}c*.srt'),
                  *(p for t in TRADICOES for p in (midia / 'narracao' / t).glob(f'{entrega.id}c*.m4a')),
                  *(p for t in TRADICOES
                    for p in (midia / 'narracao' / t).glob(f'{entrega.id}c*.m4a.origem'))]
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


def escrever(midia, entrega, videos, base, indice):
    """Os JSONs, as capas e as legendas; o índice por último. `videos`:
    {(n, tradição): Video}. Devolve os caminhos escritos e os removidos
    (relativos a `midia`)."""
    escritos = []
    escrever_json(midia / 'novela' / f'{entrega.id}.json',
                  temporada_no_formato_do_app(entrega, videos))
    escritos.append(f'novela/{entrega.id}.json')
    for c in entrega.capitulos:
        id_ = entrega.id_do_capitulo(c)
        destino = midia / 'imagens' / f'{id_}.webp'
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(c.capa, destino)
        escritos.append(f'imagens/{id_}.webp')
        if c.legenda is not None:
            if c.legenda_ajustada is not None:
                # A conferência dividiu falas (FM3): vai o SRT ajustado; o
                # da entrega não muda.
                bruto = c.legenda_ajustada.encode('utf-8')
            else:
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

def comandos_do_manifesto(dart, midia, app):
    return [([dart, 'run', 'tool/midia/gerar_manifesto.dart', str(midia)], app),
            ([dart, 'run', 'tool/lint_conteudo.dart', f'--manifesto={midia / "manifesto.json"}'], app)]


def _caminhos_da_voz(ids):
    return {f'narracao/{t}/{id_}.m4a' for id_ in ids for t in TRADICOES}


def fora_do_manifesto(midia, entrega, com_voz):
    """As chaves da temporada que o manifesto recém-gerado NÃO lista. O app
    só baixa o que está nele: o gerar_manifesto de um app anterior à Task 7
    ignora novela/ (e o lint antigo nem olharia), e a temporada não chegaria
    a ninguém."""
    try:
        arquivos = json.loads((midia / 'manifesto.json').read_text(encoding='utf-8'))['arquivos']
        if not isinstance(arquivos, dict):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError):
        return ['manifesto.json (não deu para ler)']
    esperados = ['novela/temporadas.json', f'novela/{entrega.id}.json']
    for c in entrega.capitulos:
        id_ = entrega.id_do_capitulo(c)
        esperados.append(f'imagens/{id_}.webp')
        if c.legenda is not None:
            esperados.append(f'novela/{id_}.srt')
    if com_voz:
        esperados += sorted(_caminhos_da_voz([entrega.id_do_capitulo(c) for c in entrega.capitulos]))
    return [chave for chave in esperados if chave not in arquivos]


def comandos_da_voz(dart, midia, app, ids, motor):
    """Os três comandos da voz na forma geral — texto_narrado, narrar (todos
    os ids) e conferir_stt (todos os ids) —, o que o --simular mostra. A
    rodada real monta cada um só com o que precisa (gerar_voz)."""
    return [comando_do_texto_narrado(dart, midia, app), comando_do_narrar(midia, ids, motor),
            comando_do_stt(midia, ids)]


def comando_do_texto_narrado(dart, midia, app):
    return ([dart, 'run', 'tool/midia/texto_narrado.dart',
             f'--saida={midia / "ferramentas" / "narracao" / "narracoes.jsonl"}',
             f'--temporadas={midia / "novela"}', str(app)], app)


def comando_do_narrar(midia, ids, motor, tradicao=None):
    """O narrar.py da cópia de DENTRO de --midia (ele grava na raiz em que
    está), com --refazer: ele próprio só pularia o arquivo que existe; quem
    decide o que gerar é o registro .origem, aqui. Só a `tradicao`, quando
    vem uma (a outra já está certa)."""
    cmd = [sys.executable, str(midia / 'ferramentas' / 'narrar.py'), '--motor', motor,
           '--ids', ','.join(ids)]
    if tradicao:
        cmd += ['--tradicao', tradicao]
    return cmd + ['--refazer'], midia


def comando_do_stt(midia, ids):
    return ([sys.executable, str(midia / 'ferramentas' / 'conferir_stt.py'), '--stt', 'whisper',
             '--ids', ','.join(ids)], midia)


# ---------------------------------------------------------------------------
# O registro de origem de cada narração: narrar só o que mudou (M-I2)
# ---------------------------------------------------------------------------

SUFIXO_DA_ORIGEM = '.origem'


def identificar_voz(motor, tradicao):
    """O identificador da voz que lê a `tradicao` neste `motor` — a voice_id
    da ElevenLabs, o nome da voz da Microsoft —, pelo narrar.py ao lado
    deste script (o mesmo código da cópia em --midia). É a parte "voz" do
    registro .origem: trocar a voz no narrar.py regenera a narração."""
    pasta = str(RAIZ / 'ferramentas')
    if pasta not in sys.path:
        sys.path.insert(0, pasta)
    import narrar  # noqa: PLC0415 — só na rodada real; nada de rede
    return narrar.voz_de({'tradicao': tradicao}, motor)


def assinatura_da_narracao(texto, motor, tradicao):
    """O registro <arquivo>.origem de uma narração: o sha256 do texto
    narrado (com as pausas), o motor e a voz. Igual = a mesma narração, não
    precisa gerar de novo."""
    return {'texto_sha256': hashlib.sha256(texto.encode('utf-8')).hexdigest(),
            'motor': motor, 'voz': identificar_voz(motor, tradicao)}


def ler_origem(arquivo):
    """O registro ao lado de `arquivo` (um .m4a), ou None se não há ou não lê."""
    try:
        dados = json.loads(Path(f'{arquivo}{SUFIXO_DA_ORIGEM}').read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return dados if isinstance(dados, dict) else None


def escrever_origem(arquivo, assinatura):
    """Grava o registro ao lado do .m4a (UTF-8, LF). Não é mídia: o
    gerar_manifesto só pega .m4a, e o lint não o vê; vai no commit junto do
    .m4a, para a cópia seguinte do repositório também saber a origem."""
    Path(f'{arquivo}{SUFIXO_DA_ORIGEM}').write_text(
        json.dumps(assinatura, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='')


def _narracoes_dos_capitulos(midia, ids):
    """{caminho: item} do narracoes.jsonl para os `ids` — o que o
    texto_narrado.dart emitiu para a temporada."""
    jsonl = midia / 'ferramentas' / 'narracao' / 'narracoes.jsonl'
    itens = {}
    for linha in jsonl.read_text(encoding='utf-8').splitlines():
        if linha.strip():
            item = json.loads(linha)
            if item.get('id') in ids and isinstance(item.get('caminho'), str):
                itens[item['caminho']] = item
    return itens


def _pendentes_no_stt(midia, ids):
    """As vozes dos `ids` que o stt.log.jsonl ainda não aprovou com os bytes
    de hoje: sem registro, reprovadas, ou com outro tamanho (o arquivo mudou
    depois da conferência)."""
    registros = _registros_do_stt(midia, ids)
    pendentes = []
    for caminho in sorted(_caminhos_da_voz(ids)):
        arquivo, r = midia / caminho, registros.get(caminho)
        if (not arquivo.exists() or r is None or not r.get('aprovado')
                or r.get('bytes') != arquivo.stat().st_size):
            pendentes.append(caminho)
    return pendentes


def _comandos_do_narrar(midia, caminhos, itens, ids, motor):
    """Um narrar.py por tradição que precisa — ou um só, sem --tradicao,
    quando as duas precisam dos mesmos ids (o motor da Microsoft então gera
    o texto igual uma vez e copia)."""
    por_tradicao = {}
    for t in TRADICOES:
        lista = sorted({itens[c]['id'] for c in caminhos if itens[c]['tradicao'] == t},
                       key=ids.index)
        if lista:
            por_tradicao[t] = lista
    if len(por_tradicao) == len(TRADICOES) and len({tuple(v) for v in por_tradicao.values()}) == 1:
        return [comando_do_narrar(midia, next(iter(por_tradicao.values())), motor)]
    return [comando_do_narrar(midia, lista, motor, tradicao=t) for t, lista in por_tradicao.items()]


@dataclass
class Voz:
    """O que a etapa da voz fez — ou onde parou (`falha`)."""
    falha: str | None = None
    geradas: list = field(default_factory=list)      # os caminhos narrados nesta rodada
    puladas: int = 0                                 # já estavam com este texto, motor e voz
    conferidas: list = field(default_factory=list)   # os caminhos que passaram pelo STT agora


def gerar_voz(dart, midia, app, ids, motor, refazer, tocados):
    """texto_narrado -> narrar (só o que mudou) -> conferir_stt (só o que
    ainda não foi aprovado). `tocados` recebe cada caminho gravado (os .m4a
    e os .origem), para o bloco de como desfazer. Devolve a Voz."""
    voz = Voz()
    texto, cwd_texto = comando_do_texto_narrado(dart, midia, app)
    if rodar(texto, cwd=cwd_texto) != 0:
        voz.falha = ('o texto_narrado.dart falhou (a opção --temporadas é da Task 7 do app: o app '
                     'apontado já a tem?)')
        return voz
    itens = _narracoes_dos_capitulos(midia, ids)
    faltam = sorted(_caminhos_da_voz(ids) - set(itens))
    if faltam:
        voz.falha = (f'o texto_narrado.dart não emitiu a voz dos capítulos ({", ".join(faltam)}): a '
                     'opção --temporadas é da Task 7 do app — o app apontado já a tem?')
        return voz
    # (M-I2 b) Só o que mudou: o registro .origem ao lado de cada .m4a diz
    # com que texto, motor e voz ele foi gerado.
    assinaturas = {c: assinatura_da_narracao(item['texto'], motor, item['tradicao'])
                   for c, item in itens.items()}
    a_gerar = sorted(c for c in itens
                     if refazer or not (midia / c).exists() or (midia / c).stat().st_size == 0
                     or ler_origem(midia / c) != assinaturas[c])
    voz.puladas = len(itens) - len(a_gerar)
    if not a_gerar:
        print(f'voz: nada a gerar — as {len(itens)} narrações já estão com este texto, motor e voz '
              '(registro .origem)')
    else:
        print(f'voz: {len(a_gerar)} narração(ões) a gerar ({motor}): {", ".join(a_gerar)}; '
              f'{voz.puladas} já estava(m) com este texto, motor e voz')
        for cmd, cwd in _comandos_do_narrar(midia, a_gerar, itens, ids, motor):
            codigo = rodar(cmd, cwd=cwd)
            tocados += [c for c in a_gerar if (midia / c).exists() and c not in tocados]
            if codigo != 0:
                voz.falha = 'o narrar.py falhou (a saída está acima)'
                return voz
        nao_gravadas = sorted(c for c in a_gerar
                              if not (midia / c).exists() or (midia / c).stat().st_size == 0)
        if nao_gravadas:
            voz.falha = f'o narrar.py não gravou {", ".join(nao_gravadas)}'
            return voz
        for c in a_gerar:
            escrever_origem(midia / c, assinaturas[c])
            tocados.append(f'{c}{SUFIXO_DA_ORIGEM}')
        voz.geradas = a_gerar
    # O STT: o que foi gerado agora e o que o log ainda não aprovou.
    pendentes = sorted(set(voz.geradas) | set(_pendentes_no_stt(midia, ids)))
    if not pendentes:
        print(f'STT: nada a conferir — as {len(itens)} narrações já foram aprovadas (stt.log.jsonl)')
        return voz
    ids_do_stt = sorted({itens[c]['id'] for c in pendentes}, key=ids.index)
    voz.conferidas = pendentes
    stt, cwd_stt = comando_do_stt(midia, ids_do_stt)
    if rodar(stt, cwd=cwd_stt) != 0:
        reprovados = _reprovados_no_log(midia, ids_do_stt)
        # (M-I2 c) O registro do reprovado sai: a rodada seguinte gera só ele.
        for c in reprovados:
            origem = f'{c}{SUFIXO_DA_ORIGEM}'
            Path(midia / origem).unlink(missing_ok=True)
            if origem in tocados:
                tocados.remove(origem)
        ids_reprovados = sorted({itens[c]['id'] for c in reprovados if c in itens}, key=ids.index)
        lista = (f' de {", ".join(ids_reprovados)} ({", ".join(reprovados)})' if reprovados
                 else ' (a lista está acima)')
        voz.falha = (f'a conferência por STT reprovou a voz{lista} — rode a publicação de novo: ela '
                     'pula as narrações aprovadas e gera só essa(s) (o registro .origem delas foi '
                     'apagado); se reprovar outra vez, ouça o arquivo e, se estiver bom, aceite à '
                     'mão em ferramentas/narracao/stt-aceitos.txt')
        return voz
    return voz


def _versionados_no_git(midia, caminhos):
    """Os caminhos (relativos a `midia`, com /) que o git dela versiona —
    também os apagados do disco; None se ela não é um repositório git (ou o
    git não roda)."""
    try:
        r = subprocess.run(['git', '-C', str(midia), 'ls-files', '-z', '--', *caminhos],
                           capture_output=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return set(r.stdout.decode('utf-8', errors='replace').split('\0')) - {''}


def como_desfazer(midia, escritos, removidos):
    """O que vai à tela quando a publicação para DEPOIS de escrever na raiz
    de mídia (a voz reprovada, o manifesto, o lint): em destaque, que NÃO se
    roda o gerar_manifesto nem se faz commit; cada caminho escrito e
    removido nesta rodada; e os comandos exatos para desfazer — git
    checkout -- <os versionados> (voltam como estão no commit) e git clean
    -f -- <os novos> (saem). Nada é movido para quarentena."""
    faixa = '=' * 76
    linhas = ['', faixa,
              'NÃO rode o gerar_manifesto nem faça commit: a publicação parou no meio, e a raiz',
              f'de mídia ({midia}) ficou com o que esta rodada escreveu:', faixa]
    linhas += [f'  escrito:  {caminho}' for caminho in escritos]
    linhas += [f'  removido: {caminho}' for caminho in removidos]
    versionados = _versionados_no_git(midia, escritos + removidos)
    if versionados is None:
        linhas.append('a raiz de mídia não é um repositório git: restaure ou apague à mão os '
                      'caminhos acima')
        return linhas
    a_restaurar = [c for c in escritos + removidos if c in versionados]
    a_apagar = [c for c in escritos if c not in versionados and (midia / c).exists()]
    linhas.append(f'para desfazer (na pasta {midia}):')
    if a_restaurar:
        linhas.append('  git checkout -- ' + ' '.join(a_restaurar))
    if a_apagar:
        linhas.append('  git clean -f -- ' + ' '.join(a_apagar))
    return linhas


def _registros_do_stt(midia, ids):
    """{caminho: o ÚLTIMO registro do stt.log.jsonl} das vozes dos `ids`.
    Uma linha truncada (um conferir_stt.py morto no meio da escrita, numa
    rodada anterior) é pulada, não derruba a publicação (M-m2)."""
    log = midia / 'ferramentas' / 'narracao' / 'stt.log.jsonl'
    if not log.exists():
        return {}
    caminhos = _caminhos_da_voz(ids)
    ultimo = {}
    for linha in log.read_text(encoding='utf-8').splitlines():
        if not linha.strip():
            continue
        try:
            r = json.loads(linha)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get('caminho') in caminhos:
            ultimo[r['caminho']] = r
    return ultimo


def _reprovados_no_log(midia, ids):
    return sorted(c for c, r in _registros_do_stt(midia, ids).items() if not r.get('aprovado'))


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
    ap.add_argument('--refazer', action='store_true',
                    help='gera de novo TODA a voz dos capítulos, mesmo a que o registro .origem diz '
                         'que não mudou (texto, motor e voz iguais)')
    ap.add_argument('--substituir-videos', action='store_true',
                    help='o vídeo já publicado com OUTRO conteúdo sobe numa chave nova '
                         '(video/<t>/<nn>-<tradicao>-<sha8>.mp4) e o JSON aponta para ela; o objeto '
                         'velho fica intocado. Sem ela, a publicação recusa antes de subir ou '
                         'escrever qualquer coisa')
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
    # Antes de tudo: a simulação nunca escreve num repositório.
    if args.simular:
        conferir_raiz_da_simulacao(args.midia, args.app)
    midia = Path(args.midia).absolute() if args.midia else MIDIA_PADRAO
    app = Path(args.app).absolute() if args.app else APP_PADRAO
    prefixo = normalizar_prefixo(args.r2_prefixo)
    if args.simular:
        return _publicar(args, midia, app, prefixo)
    # A rodada real: uma por vez nesta raiz de mídia (R8-N). A trava vem
    # antes de qualquer conferência, HEAD ou envio, e sai no finally —
    # também na falha e numa interrupção. O tomar_trava fica DENTRO do try
    # (F15): um Ctrl+C entre a criação dela e o try não a deixaria; o
    # finally só apaga a trava desta publicação (a de outra, tomar_trava
    # nem devolve).
    trava = None
    try:
        trava, recusa = tomar_trava(midia)
        if trava is None:
            print(f'trava: {recusa}')
            return 1
        return _publicar(args, midia, app, prefixo)
    finally:
        if trava is not None:
            soltar_trava(trava)


def _publicar(args, midia, app, prefixo):
    """A publicação, da conferência ao resumo (na rodada real, com a trava
    já tomada)."""
    # 1. Conferência: tudo, antes de qualquer envio ou escrita.
    avisos_da_entrega = []
    entrega, problemas = conferir_entrega(Path(args.entrega), avisos=avisos_da_entrega)
    indice, problemas_do_indice = ler_indice(midia)
    problemas += problemas_do_indice
    chaves = dart = None
    if not args.simular:
        chaves, dart, p = conferir_o_caminho_real(args, midia, app)
        problemas += p
    # A simulação nunca lê o arquivo de chaves: a base sem --videos-base e
    # sem índice é o marcador.
    publica = MARCADOR_DA_URL_PUBLICA if args.simular else (chaves.url_publica if chaves else None)
    base, p = resolver_base(args.videos_base, indice, publica, prefixo)
    problemas += p
    # O índice FINAL, inteiro, pelas regras do app (que o recusa inteiro).
    if entrega is not None and base is not None and not problemas_do_indice:
        problemas += conferir_indice(indice_atualizado(indice, entrega, base))
    if problemas:
        print(f'conferência: {len(problemas)} problema(s) — nada foi enviado nem escrito:')
        for problema in problemas:
            print(f'  - {problema}')
        # O aviso não recusa, mas a entrega volta para ser refeita: vai junto.
        for aviso in avisos_da_entrega:
            print(f'aviso (não recusa): {aviso}')
        return 1
    ids = [entrega.id_do_capitulo(c) for c in entrega.capitulos]
    print(f'conferência ok: {entrega.id}, {len(ids)} capítulo(s), de {entrega.inicio} a {entrega.fim}')
    avisos = avisos_da_base(base, prefixo)
    for aviso in avisos_da_entrega + avisos:
        print(f'aviso: {aviso}')

    # 2. O R2, antes de qualquer escrita local (nenhum JSON aponta para um
    #    vídeo que não está lá): a chave de cada vídeo, só consultando — o
    #    que trocaria um vídeo publicado é recusado aqui, antes de subir
    #    qualquer coisa —, e depois o envio do que falta.
    videos = videos_da_entrega(entrega)
    publicados = videos_publicados(midia, entrega.id)
    if args.simular:
        problemas, recusas = planejar_videos(entrega, videos, publicados,
                                             r2_segundo_o_json_publicado(publicados),
                                             args.substituir_videos, prefixo)
    else:
        try:
            cliente = criar_cliente_r2(chaves)
            problemas, recusas = planejar_videos(
                entrega, videos, publicados,
                lambda chave: _estado_no_r2(cliente, prefixo + chave),
                args.substituir_videos, prefixo)
        except Exception as e:  # noqa: BLE001 — qualquer erro do R2: limpo, nunca cru
            print(f'R2: a consulta falhou ({descrever_erro(e, chaves)}); nada foi enviado nem '
                  'escrito')
            return 1
    if recusas or problemas:
        simulado = ' (simulado, pelo novela/<t>.json publicado)' if args.simular else ''
        # A regra não muda: nada no R2 é sobrescrito. Muda a explicação
        # (R8-O): o vídeo que nenhum novela/<t>.json aponta — nem o da pasta
        # nem o do último commit dela — é provavelmente sobra de uma rodada
        # interrompida, que subiu e parou antes de gravar o JSON.
        apontados = set(publicados) | set(videos_no_ultimo_commit(midia, entrega.id))
        recusados = list(zip((v for v in videos if v.recusada), recusas))
        no_ar = [r for v, r in recusados if (v.capitulo.n, v.tradicao) in apontados]
        sobras = [r for v, r in recusados if (v.capitulo.n, v.tradicao) not in apontados]
        if no_ar:
            print(f'R2{simulado}: {len(no_ar)} vídeo(s) já publicado(s) com OUTRO conteúdo — '
                  'nada foi enviado nem escrito:')
            for recusa in no_ar:
                print(f'  - {recusa}')
            print('  sobrescrever quebraria o capítulo em todo aparelho que ainda tem o JSON velho '
                  '(o sha256 não bate e o vídeo é recusado). Para publicar a versão nova numa chave '
                  'nova (video/<t>/<nn>-<tradicao>-<sha8>.mp4), com o objeto velho intocado, rode '
                  'de novo com --substituir-videos')
        if sobras:
            print(f'R2{simulado}: {len(sobras)} vídeo(s) no R2 com OUTRO conteúdo, que nenhum '
                  f'novela/{entrega.id}.json aponta (nem o da pasta, nem o do último commit) — nada '
                  'foi enviado nem escrito:')
            for recusa in sobras:
                print(f'  - {recusa}')
            print('  é provavelmente sobra de uma rodada interrompida (que subiu o vídeo e parou '
                  'antes de gravar o JSON): nenhum aparelho o usa, e publicar com '
                  '--substituir-videos é seguro — a chave nova vai no JSON, e a fixa fica como '
                  'sobra (centavos). Nem a sobra é sobrescrita: o HEAD público daquela rodada pode '
                  'tê-la posto no cache da borda')
        for problema in problemas:
            print(f'R2{simulado}: {problema}')
        return 1
    if args.simular:
        print(f'R2 (simulado): subiria ao balde {BALDE}:')
        for v in videos:
            if v.sobe:
                print(f'    {prefixo}{v.chave}  {_milhar(v.bytes)} bytes  sha256 {v.sha256}')
        if not any(v.sobe for v in videos):
            print('    (nada: todos já estão lá, segundo o novela/<t>.json publicado)')
    else:
        try:
            subir_videos(cliente, videos, prefixo)
        except Exception as e:  # noqa: BLE001 — qualquer erro do R2: limpo, nunca cru
            print(f'R2: o envio falhou ({descrever_erro(e, chaves)}); nada foi escrito — '
                  'rode de novo (o que já subiu com o mesmo sha256 não sobe outra vez)')
            return 1
        # Cada vídeo pela URL que o app vai pedir (também o que já estava).
        problemas = conferir_pela_url_publica(videos, base, chaves)
        if problemas:
            print(f'URL pública: {len(problemas)} vídeo(s) não conferem pela base "videos" — '
                  'nada foi escrito:')
            for problema in problemas:
                print(f'  - {problema}')
            print('  o app pediria os vídeos ali: confira a base (--videos-base ou a do índice) e o '
                  'acesso público do balde; o que subiu fica no R2 e não sobe de novo')
            return 1
    por_capitulo = {(v.capitulo.n, v.tradicao): v for v in videos}

    # 3. Os JSONs, as capas e as legendas.
    escritos, removidos = escrever(midia, entrega, por_capitulo, base, indice)

    # 4. Voz, manifesto e lint.
    if args.simular:
        if args.sem_voz:
            print('voz (simulado): pulada (--sem-voz)')
        else:
            print('voz (simulado): rodaria — na forma geral; a rodada real gera só a narração cujo '
                  'registro .origem não bate e confere só a que o stt.log.jsonl ainda não aprovou')
            for cmd, cwd in comandos_da_voz('dart', midia, app, ids, args.motor):
                print(_mostrar(cmd, cwd))
        print('manifesto e lint (simulado): rodaria')
        for cmd, cwd in comandos_do_manifesto('dart', midia, app):
            print(_mostrar(cmd, cwd))
    else:
        # Daqui em diante a raiz de mídia já tem o que esta rodada escreveu:
        # parar é dizer o quê e como desfazer (R8-H) — também quando a
        # rodada morre por um Ctrl+C ou por uma exceção imprevista (M-m2):
        # o mesmo bloco sai, e a exceção segue subindo. `tocados` é o que o
        # passo 4 vai gravando além de `escritos`.
        tocados = []

        def parar(mensagem):
            print(mensagem)
            for linha in como_desfazer(midia, escritos + tocados, removidos):
                print(linha)
            return 1

        def voz_no_disco():
            return [c for c in sorted(_caminhos_da_voz(ids)) if (midia / c).exists()]

        voz = Voz()
        try:
            (manifesto, cwd_manifesto), (lint, cwd_lint) = comandos_do_manifesto(dart, midia, app)

            def manifesto_e_lint(com_voz):
                """None se passou; senão o código da parada (com o bloco)."""
                # Começou a ser refeito: conta como tocado, mesmo que falhe no meio.
                if 'manifesto.json' not in tocados:
                    tocados.append('manifesto.json')
                if rodar(manifesto, cwd=cwd_manifesto) != 0:
                    return parar('manifesto: o gerar_manifesto.dart falhou (a saída está acima)')
                faltam = fora_do_manifesto(midia, entrega, com_voz=com_voz)
                if faltam:
                    return parar(f'manifesto: não lista {", ".join(faltam)} — o gerar_manifesto.dart '
                                 'do app apontado conhece a pasta novela/ (Task 7)? Sem isso o app '
                                 'não baixa a temporada')
                if rodar(lint, cwd=cwd_lint) != 0:
                    antes_da_voz = '' if com_voz or args.sem_voz else ' (nenhuma voz foi gerada)'
                    return parar('lint: o lint_conteudo.dart achou erro (a saída está acima) — '
                                 f'corrija e publique de novo{antes_da_voz}')
                return None

            # (M-I2 a) O manifesto e o lint ANTES da voz: o lint é a palavra
            # final sobre os textos, e um texto que ele recusa não gasta um
            # crédito de voz (a narração ausente é pendência da regra 2,
            # não erro). Depois da voz, os dois de novo, com ela dentro.
            codigo = manifesto_e_lint(com_voz=False)
            if codigo is not None:
                return codigo
            if not args.sem_voz:
                voz = gerar_voz(dart, midia, app, ids, args.motor, args.refazer, tocados)
                if voz.falha:
                    return parar(f'voz: {voz.falha}')
                codigo = manifesto_e_lint(com_voz=True)
                if codigo is not None:
                    return codigo
        except BaseException as e:  # noqa: BLE001 — o Ctrl+C não é Exception; tudo sobe depois do bloco
            # A voz pode ter sido gravada antes de o gerar_voz devolver (o
            # Ctrl+C no whisper): o que está no disco entra na lista.
            if not args.sem_voz and not any(c.startswith('narracao/') for c in tocados):
                tocados += voz_no_disco()
            detalhe = f': {e}' if str(e) else ''
            parar(f'a publicação foi interrompida depois da escrita ({type(e).__name__}{detalhe})')
            raise

    # 5. O resumo.
    print()
    print(f'== resumo{" (SIMULADO)" if args.simular else ""} ==')
    print(f'temporada {entrega.id} ("{entrega.titulo}"): {len(ids)} capítulo(s), de '
          f'{entrega.inicio} a {entrega.fim}')
    for c in entrega.capitulos:
        tamanhos = '  '.join(f'{c.nn}-{t}.mp4 {_milhar(por_capitulo[c.n, t].bytes)} bytes'
                             for t in TRADICOES)
        print(f'  {entrega.id_do_capitulo(c)}  {c.dados["data"]}  {tamanhos}  '
              f'legenda: {"sim" if c.legenda else "não"}')
    for aviso in avisos_da_entrega:
        print(f'  aviso: {aviso}')
    contagem = ', '.join(f'{estado}: {sum(1 for v in videos if v.estado == estado)}'
                         for estado in (NOVO, JA_ESTAVA, TROCADO))
    nota = ('; simulado: o R2 não foi consultado — o estado vem do novela/<t>.json publicado'
            if args.simular else '')
    print(f'R2 (balde {BALDE}{nota}): {contagem}')
    for v in videos:
        if args.simular:
            acao = 'subiria' if v.sobe else 'não subiria'
        else:
            acao = 'subiu' if v.sobe else 'não subiu'
        velha = (f' — {prefixo}{v.velha} fica intocado (o JSON velho ainda aponta para ele)'
                 if v.estado == TROCADO else '')
        print(f'  {prefixo}{v.chave}  {_milhar(v.bytes)} bytes  {v.estado}: {acao}{velha}')
    if args.simular:
        print('URL pública: não conferida (simulado)')
    else:
        print(f'URL pública: os {len(videos)} vídeos conferidos por HEAD em {base} (Content-Length '
              '= bytes)')
    print(f'base "videos": {base}')
    if base.startswith(MARCADOR_DA_URL_PUBLICA):
        print('  (simulado: o arquivo de chaves não é lido — a rodada real põe aqui a Public '
              'Development URL do R2)')
    for aviso in avisos:
        print(f'  aviso: {aviso}')
    if indice and indice.get('videos') and indice['videos'] != base:
        print(f'  (era {indice["videos"]}: o vídeo que já está no aparelho não baixa de novo — o '
              'app o reconhece pelo sha256)')
    print(f'escrito em {midia}: {", ".join(escritos)}')
    if removidos:
        print(f'removido (sobra da versão anterior): {", ".join(removidos)}')
    if args.simular:
        print('voz, manifesto e lint: não rodaram (simulado)')
    else:
        da_voz = ('pulada (--sem-voz)' if args.sem_voz
                  else f'{args.motor}: {len(voz.geradas)} narração(ões) gerada(s), {voz.puladas} já '
                       f'estava(m) (registro .origem); STT: {len(voz.conferidas)} conferida(s), ok')
        print(f'voz: {da_voz}; manifesto refeito; lint sem erro')
    print('lembrete: commit por caminho (git add -- <novos>; git commit -- <caminhos>), com cada '
          '.origem junto do .m4a dele + push SÓ com OK do Gregory.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
