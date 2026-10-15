#!/usr/bin/env python3
"""Confere cada narração gerada: reconhecimento de fala x texto enviado.

Regra herdada dos vídeos do Toca o Negócio: todo áudio gerado passa pelo
ElevenLabs Scribe (scribe_v1, idioma por) e o texto reconhecido é comparado,
palavra a palavra, com o texto enviado sem as tags de pausa. Divergência de
palavra reprova o arquivo; o reprovado é gerado de novo com
`narrar.py --ids <id> --refazer` e conferido outra vez.

Números: o texto enviado traz algarismos ("capítulo 23, versículo 1") e o
Scribe pode devolver algarismos ou palavras; os dois lados são normalizados
para algarismos antes da comparação (0 a 199, o que cobre capítulos e
versículos). Anos ("em 1597"), numerais romanos ("Pio XII", "século IV") e
ordinais variam demais de forma: uma diferença em que os DOIS lados são só
números fica registrada como "numero" e não reprova. O mesmo vale para nome
próprio com grafia parecida ("Roccaporena" x "Rocaporena"): fica como "grafia".
Qualquer outra palavra trocada, a mais ou a menos, reprova.

Resultado: ferramentas/narracao/stt.log.jsonl (uma linha por arquivo, com a
semelhança e as diferenças) e, no fim, a lista dos reprovados.

FASE ATUAL (14/10/2026): `--stt whisper` — reconhecimento LOCAL e gratuito
(whisper.cpp pelo pacote pywhispercpp, modelos ggml do cache do HyperFrames
em ~/.cache/hyperframes/whisper/models, ou WHISPER_MODELOS), sem a
ElevenLabs. Em dois ouvidos: o modelo `small` ouve tudo (uns 4x mais rápido
que o áudio); o que ele reprova, o `medium` ouve de novo. Só reprova o que os
DOIS ouviram errado no mesmo lugar — um erro do áudio soa igual para os dois
ouvidos; o erro de um ouvido só é do ouvido, e fica no log como `duvidas`.
Um modelo de cada vez (whisper.cpp não é seguro entre threads): --paralelo
não vale para ele. Além dos números, uma palavra "capítulo"/"versículo(s)"
que o ouvido engole antes do número fica como "referencia" e não reprova
(o whisper escreve "Salmo 23, versículo 1" para "Salmo, capítulo 23,
versículo 1"); e duas tolerâncias pequenas, medidas no piloto de 14/10
(`soa_igual`, `palavras_curtas`): a troca curta que soa igual ("guia" por
"guie", "há" por "a") e o artigo ou preposição engolido, trocado ou
acrescentado. O que reprova é o erro grande — o trecho que faltou, a
frase cortada, o nome lido errado — e ele sempre passa por essas duas.

Uso:
  python ferramentas/conferir_stt.py                 # tudo que ainda não foi conferido
  python ferramentas/conferir_stt.py --ids comum-001
  python ferramentas/conferir_stt.py --stt whisper                       # a fase atual
  python ferramentas/conferir_stt.py --stt whisper --pecas ferramentas/narracao/trechos-microsoft   # Terço e orações, peça a peça
  python ferramentas/conferir_stt.py --so-listar     # reprovados do log
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from narrar import API, ENTRADA, RAIZ, chave_api, ler_entrada  # noqa: E402

LOG = RAIZ / 'ferramentas' / 'narracao' / 'stt.log.jsonl'
MODELOS_WHISPER = Path(os.environ.get(
    'WHISPER_MODELOS', Path.home() / '.cache' / 'hyperframes' / 'whisper' / 'models'))
WHISPER_RAPIDO, WHISPER_FINO = 'small', 'medium'
# O que reprova é a diferença dura; a semelhança é só uma rede por baixo
# (um arquivo que só tem diferenças toleradas mas é 40% diferente não
# existe de verdade). Era 0,90 e reprovava peça curta do Terço com duas
# trocas toleradas ("perdoai"/"perdoe", "dai"/"dá" numa frase de 9 palavras).
SEMELHANCA_MINIMA = 0.60
# Palavras que o ouvido engole antes de um número sem o áudio estar errado.
PALAVRAS_DE_REFERENCIA = {'capitulo', 'versiculo', 'versiculos'}

UNIDADES = {'zero': 0, 'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3,
            'quatro': 4, 'cinco': 5, 'seis': 6, 'sete': 7, 'oito': 8,
            'nove': 9, 'dez': 10, 'onze': 11, 'doze': 12, 'treze': 13,
            'catorze': 14, 'quatorze': 14, 'quinze': 15, 'dezesseis': 16,
            'dezasseis': 16, 'dezessete': 17, 'dezassete': 17, 'dezoito': 18,
            'dezenove': 19, 'dezanove': 19}
DEZENAS = {'vinte': 20, 'trinta': 30, 'quarenta': 40, 'cinquenta': 50,
           'sessenta': 60, 'setenta': 70, 'oitenta': 80, 'noventa': 90}
CENTENAS = {'cem': 100, 'cento': 100}

OUTROS_NUMEROS = {'e', 'mil', 'duzentos', 'trezentos', 'quatrocentos',
                  'quinhentos', 'seiscentos', 'setecentos', 'oitocentos',
                  'novecentos', 'primeiro', 'primeira', 'segundo', 'segunda',
                  'terceiro', 'terceira', 'quarto', 'quarta', 'quinto',
                  'quinta', 'sexto', 'sexta', 'setimo', 'setima', 'oitavo',
                  'oitava', 'nono', 'nona', 'decimo', 'decima', 'vigesimo',
                  'vigesima', 'trigesimo', 'undecimo', 'duodecimo'}
ROMANO = re.compile(r'^m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$')

_trava = threading.Lock()


def e_numero(tok):
    return (tok.isdigit() or tok in UNIDADES or tok in DEZENAS or tok in CENTENAS
            or tok in OUTROS_NUMEROS or bool(tok and ROMANO.match(tok)))


def nomes_proprios(texto):
    """Palavras que aparecem com maiúscula no MEIO de uma frase."""
    texto = re.sub(r'<break[^>]*>', ' ', texto)
    nomes = set()
    for m in re.finditer(r'[A-Za-zÀ-ÿ]+', texto):
        p = m.group(0)
        if not p[0].isupper():
            continue
        antes = texto[:m.start()].rstrip()
        if not antes or antes[-1] in '.!?:"“':
            continue  # início de frase: a maiúscula não diz nada
        nomes.add(sem_acento(p.lower()))
    return nomes


def sem_acento(t):
    return ''.join(c for c in unicodedata.normalize('NFD', t)
                   if unicodedata.category(c) != 'Mn')


def palavras(texto):
    texto = re.sub(r'<break[^>]*>', ' ', texto)
    texto = sem_acento(texto.lower())
    texto = re.sub(r'(\d)[.,](\d)', r'\1 \2', texto)
    return re.findall(r'[a-z0-9]+', texto)


def numeros_em_algarismos(toks):
    """Junta 'cento e vinte e tres' -> '123' (até 199); o 'e' entre partes some."""
    saida, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t in CENTENAS or t in DEZENAS or t in UNIDADES:
            valor, j, achou = 0, i, False
            if toks[j] in CENTENAS:
                valor += 100
                j += 1
                achou = True
                if j < len(toks) and toks[j] == 'e':
                    j += 1
            if j < len(toks) and toks[j] in DEZENAS:
                valor += DEZENAS[toks[j]]
                j += 1
                achou = True
                if j + 1 < len(toks) and toks[j] == 'e' and toks[j + 1] in UNIDADES \
                        and UNIDADES[toks[j + 1]] < 10:
                    valor += UNIDADES[toks[j + 1]]
                    j += 2
            elif j < len(toks) and toks[j] in UNIDADES:
                valor += UNIDADES[toks[j]]
                j += 1
                achou = True
            if achou and j > i:
                # "um"/"uma" soltos são artigo, não número: só converte se
                # fizer parte de um número maior ou vier depois de
                # "capitulo"/"versiculo(s)"/"a".
                solto = (j - i == 1 and t in ('um', 'uma'))
                antes = saida[-1] if saida else ''
                if solto and antes not in ('capitulo', 'versiculo', 'versiculos', 'a'):
                    saida.append(t)
                else:
                    saida.append(str(valor))
                i = j
                continue
        saida.append(t)
        i += 1
    return saida


def normalizar(texto):
    return numeros_em_algarismos(palavras(texto))


def transcrever(chave, arquivo):
    limite = uuid.uuid4().hex
    partes = []
    for nome, valor in (('model_id', 'scribe_v1'), ('language_code', 'por'),
                        ('tag_audio_events', 'false'), ('diarize', 'false')):
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; '
                      f'name="{nome}"\r\n\r\n{valor}\r\n'.encode())
    partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="file"; '
                  f'filename="{arquivo.name}"\r\nContent-Type: audio/mp4\r\n\r\n'.encode())
    partes.append(arquivo.read_bytes())
    partes.append(f'\r\n--{limite}--\r\n'.encode())
    req = urllib.request.Request(
        f'{API}/speech-to-text', data=b''.join(partes), method='POST',
        headers={'xi-api-key': chave,
                 'Content-Type': f'multipart/form-data; boundary={limite}'})
    for tentativa in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r).get('text', '')
        except urllib.error.HTTPError as e:
            texto = e.read()[:300].decode('utf-8', 'replace')
            if e.code in (429, 500, 502, 503, 504) and tentativa < 5:
                time.sleep(15 * tentativa)
                continue
            raise RuntimeError(f'HTTP {e.code}: {texto}') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if tentativa < 5:
                time.sleep(10 * tentativa)
                continue
            raise RuntimeError(f'rede: {e}') from None
    raise RuntimeError('sem resposta')


def comparar(esperado, ouvido):
    """Devolve (semelhança, diferenças que reprovam, diferenças toleradas)."""
    a, b = normalizar(esperado), normalizar(ouvido)
    nomes = nomes_proprios(esperado)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    duras, leves = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        ta, tb = a[i1:i2], b[j1:j2]
        d = {'op': op, 'esperado': ' '.join(ta), 'ouvido': ' '.join(tb)}
        if ta and tb and all(e_numero(t) for t in ta) and all(e_numero(t) for t in tb):
            leves.append(dict(d, tipo='numero'))
        elif ta and tb and any(t in nomes for t in ta) and                 difflib.SequenceMatcher(a=''.join(ta), b=''.join(tb)).ratio() >= 0.75:
            leves.append(dict(d, tipo='grafia'))
        elif op == 'delete' and all(t in PALAVRAS_DE_REFERENCIA for t in ta):
            leves.append(dict(d, tipo='referencia'))
        elif soa_igual(ta, tb):
            leves.append(dict(d, tipo='som'))
        elif palavras_curtas(ta, tb):
            leves.append(dict(d, tipo='curta'))
        else:
            duras.append(d)
    return round(sm.ratio(), 4), duras, leves


# O ouvido do whisper (os dois tamanhos, do mesmo jeito) "corrige" o que ouve
# para a forma que lhe parece mais comum: "guia os meus passos" vira "guie",
# "há" vira "a", "fora posto" vira "for aposto", "põe" vira "ponha", "me a"
# vira "minha". Nada disso é erro do áudio — a voz lê o texto que recebeu —,
# e reprovar por isso mandaria refazer arquivos certos. O erro que a voz
# pode cometer é grande: trecho que faltou, frase cortada, nome lido
# errado. Por isso duas tolerâncias curtas, só para diferenças pequenas:
SOM_MINIMO = 0.5  # 'sois vos'/'suas voz' e 'me a'/'minha' dão 0,57 no piloto
PALAVRAS_NO_MAXIMO = 3
LETRAS_DA_PALAVRA_CURTA = 3


def _som(toks):
    """O que se ouve: sem espaços, sem o h mudo."""
    return ''.join(toks).replace('h', '')


def soa_igual(ta, tb):
    """Troca pequena (até 3 palavras de cada lado) em que os dois lados soam
    parecidos: a grafia junta, sem o h mudo, com metade ou mais em comum
    ("guia"/"guie", "ha"/"a", "fora posto"/"for aposto", "provem"/"provei")."""
    if not ta or not tb or len(ta) > PALAVRAS_NO_MAXIMO or len(tb) > PALAVRAS_NO_MAXIMO:
        return False
    a, b = _som(ta), _som(tb)
    return a == b or difflib.SequenceMatcher(a=a, b=b).ratio() >= SOM_MINIMO


def palavras_curtas(ta, tb):
    """Até duas palavras de até 3 letras de um lado, e no máximo duas do
    outro: o artigo e a preposição que o ouvido engole, troca ou acrescenta
    ("um"/"o", "a" a menos, "de" a mais, "poe"/"ponha")."""
    curto = ta if ta else tb
    return (len(curto) <= 2 and all(len(t) <= LETRAS_DA_PALAVRA_CURTA for t in curto)
            and len(ta) <= 2 and len(tb) <= 2)


def _palavras_da_diferenca(d):
    return set((d['esperado'] or d['ouvido']).split())


def cruzar(duras_rapido, duras_fino):
    """(confirmadas, dúvidas) entre as diferenças duras de dois ouvidos. Uma
    diferença do ouvido fino é confirmada quando o rápido tropeçou nas
    mesmas palavras (do texto esperado; numa inserção, nas ouvidas): o que
    só um dos dois ouviu errado é dúvida — do ouvido, não do áudio."""
    tropecos = set()
    for d in duras_rapido:
        tropecos |= _palavras_da_diferenca(d)
    confirmadas, duvidas = [], []
    for d in duras_fino:
        (confirmadas if _palavras_da_diferenca(d) & tropecos else duvidas).append(d)
    duvidas += [dict(d, ouvido_por=WHISPER_RAPIDO) for d in duras_rapido
                if not (_palavras_da_diferenca(d)
                        & set().union(*(_palavras_da_diferenca(c) for c in confirmadas)))]
    return confirmadas, duvidas


class Scribe:
    """O ouvido da ElevenLabs (scribe_v1): uma passada, qualquer palavra
    trocada reprova."""
    nome = 'scribe'
    paralelo = True

    def __init__(self, chave):
        self.chave = chave

    def avaliar(self, arquivo, esperado):
        ouvido = transcrever(self.chave, arquivo)
        semelhanca, duras, leves = comparar(esperado, ouvido)
        return {'semelhanca': semelhanca, 'diferencas': duras, 'toleradas': leves,
                'aprovado': not duras and semelhanca >= SEMELHANCA_MINIMA,
                'ouvido': ouvido}


class Whisper:
    """O ouvido local (whisper.cpp), em dois passos — ver o topo do arquivo."""
    nome = 'whisper'
    paralelo = False

    def __init__(self, pasta=MODELOS_WHISPER, rapido=WHISPER_RAPIDO, fino=WHISPER_FINO):
        self.pasta, self.rapido, self.fino = Path(pasta), rapido, fino
        self._modelos = {}
        for nome in (rapido, fino):
            if not (self.pasta / f'ggml-{nome}.bin').exists():
                sys.exit(f'modelo whisper ggml-{nome}.bin não está em {self.pasta} '
                         '(aponte a pasta em WHISPER_MODELOS)')

    def modelo(self, nome):
        if nome not in self._modelos:
            from pywhispercpp.model import Model
            self._modelos[nome] = Model(str(self.pasta / f'ggml-{nome}.bin'),
                                        n_threads=max(1, (os.cpu_count() or 4) - 2),
                                        print_realtime=False, print_progress=False)
        return self._modelos[nome]

    def transcrever(self, nome, arquivo):
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
            wav16 = Path(t.name)
        try:
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(arquivo),
                            '-ac', '1', '-ar', '16000', str(wav16)], check=True)
            segmentos = self.modelo(nome).transcribe(str(wav16), language='pt')
        finally:
            wav16.unlink(missing_ok=True)
        return ' '.join(s.text.strip() for s in segmentos)

    def avaliar(self, arquivo, esperado):
        ouvido1 = self.transcrever(self.rapido, arquivo)
        sem1, duras1, leves1 = comparar(esperado, ouvido1)
        if not duras1 and sem1 >= SEMELHANCA_MINIMA:
            return {'semelhanca': sem1, 'diferencas': [], 'toleradas': leves1,
                    'aprovado': True, 'ouvido': ouvido1, 'modelo': self.rapido}
        ouvido2 = self.transcrever(self.fino, arquivo)
        sem2, duras2, leves2 = comparar(esperado, ouvido2)
        confirmadas, duvidas = cruzar(duras1, duras2)
        return {'semelhanca': sem2, 'semelhanca_rapido': sem1,
                'diferencas': confirmadas, 'duvidas': duvidas, 'toleradas': leves2,
                'aprovado': not confirmadas and max(sem1, sem2) >= SEMELHANCA_MINIMA,
                'ouvido': ouvido2, 'ouvido_rapido': ouvido1, 'modelo': self.fino}


def sha256_de(arquivo):
    return hashlib.sha256(arquivo.read_bytes()).hexdigest()


def _registrar(registro):
    with _trava:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(registro, ensure_ascii=False) + '\n')


def conferir(ouvido, item):
    arquivo = RAIZ / item['caminho']
    registro = {'caminho': item['caminho'], 'id': item['id'], 'stt': ouvido.nome,
                'quando': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'bytes': arquivo.stat().st_size, 'sha256': sha256_de(arquivo)}
    try:
        resultado = ouvido.avaliar(arquivo, item['texto'])
        if resultado['aprovado']:
            resultado.pop('ouvido', None)
            resultado.pop('ouvido_rapido', None)
        registro.update(ok=True, **resultado)
    except Exception as e:  # noqa: BLE001
        registro.update(ok=False, erro=str(e)[:300], aprovado=False)
    _registrar(registro)
    return registro


def conferir_grupo(ouvido, itens):
    """Itens com o MESMO arquivo (mesmo sha256 e mesmo texto — a cópia
    evangélica do cartão católico, com o motor da Microsoft) são ouvidos uma
    vez: o veredito do primeiro vale para os outros, cada um com a sua
    linha no log (`igual_a` diz de quem veio)."""
    primeiro = conferir(ouvido, itens[0])
    registros = [primeiro]
    for item in itens[1:]:
        copia = dict(primeiro, caminho=item['caminho'], id=item['id'],
                     igual_a=primeiro['caminho'], quando=time.strftime('%Y-%m-%dT%H:%M:%S'))
        _registrar(copia)
        registros.append(copia)
    return registros


def agrupar_iguais(itens):
    grupos = {}
    for item in itens:
        grupos.setdefault((sha256_de(RAIZ / item['caminho']), item['texto']), []).append(item)
    return list(grupos.values())


def itens_das_pecas(trabalho):
    """O Terço e as orações são conferidos PEÇA a peça: cada peça do diretório
    de trabalho de narrar_trechos.py (o .wav medido e o .json com o texto)
    vira um item como os do narracoes.jsonl, com o caminho relativo a este
    repo. Conferir o arquivo montado (3 a 5 min, 53 Ave-Marias iguais)
    confunde o ouvido — no piloto de 14/10 a mesma Ave-Maria passou sozinha
    e "falhou" dentro da abertura —, e a montagem já é provada pela duração
    (narrar_trechos.montar: o arquivo final tem de somar as peças e os
    silêncios, com 0,15 s de folga)."""
    trabalho = Path(trabalho)
    itens = []
    for meta in sorted((trabalho / 'pecas').glob('*/*.json')):
        dados = json.loads(meta.read_text(encoding='utf-8'))
        wav = meta.with_suffix('.wav')
        if not wav.exists() or dados.get('simulado'):
            continue
        itens.append({'id': f'peca-{dados["chave"]}', 'tradicao': dados['tradicao'],
                      'caminho': wav.resolve().relative_to(RAIZ.resolve()).as_posix(),
                      'texto': dados['texto']})
    if not itens:
        sys.exit(f'nenhuma peça real em {trabalho / "pecas"}')
    return itens


def ultimo_por_caminho():
    vistos = {}
    if LOG.exists():
        for linha in open(LOG, encoding='utf-8'):
            r = json.loads(linha)
            vistos[r['caminho']] = r
    return vistos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entrada', default=str(ENTRADA))
    ap.add_argument('--pecas', metavar='TRABALHO',
                    help='em vez da entrada, as peças do Terço e das orações neste diretório '
                         'de trabalho de narrar_trechos.py (ferramentas/narracao/trechos-microsoft)')
    ap.add_argument('--ids')
    ap.add_argument('--paralelo', type=int, default=3)
    ap.add_argument('--limite', type=int, default=0)
    ap.add_argument('--so-listar', action='store_true')
    ap.add_argument('--stt', choices=(Scribe.nome, Whisper.nome), default=Scribe.nome,
                    help='scribe (ElevenLabs, pago) ou whisper (local, gratuito — a fase atual)')
    ap.add_argument('--modelos', default=str(MODELOS_WHISPER),
                    help='pasta dos modelos ggml do whisper (small e medium)')
    args = ap.parse_args()

    vistos = ultimo_por_caminho()
    if args.so_listar:
        ruins = [r for r in vistos.values() if not r.get('aprovado')]
        for r in ruins:
            print(r['caminho'], r.get('semelhanca'), r.get('diferencas') or r.get('erro'))
        print(f'{len(ruins)} reprovados de {len(vistos)} conferidos')
        return 1 if ruins else 0

    itens = itens_das_pecas(args.pecas) if args.pecas else ler_entrada(args.entrada)
    itens = [i for i in itens if (RAIZ / i['caminho']).exists()]
    if args.ids:
        quero = set(args.ids.split(','))
        itens = [i for i in itens if i['id'] in quero]
    else:
        # só o que ainda não foi conferido, ou mudou de tamanho desde a conferência
        itens = [i for i in itens
                 if i['caminho'] not in vistos
                 or vistos[i['caminho']].get('bytes') != (RAIZ / i['caminho']).stat().st_size
                 or not vistos[i['caminho']].get('ok')]
    if args.limite:
        itens = itens[:args.limite]
    print(f'a conferir: {len(itens)} arquivos')
    if not itens:
        return 0

    ouvido = Whisper(args.modelos) if args.stt == Whisper.nome else Scribe(chave_api())
    LOG.parent.mkdir(parents=True, exist_ok=True)
    grupos = agrupar_iguais(itens)
    if len(grupos) < len(itens):
        print(f'({len(itens) - len(grupos)} são cópias de outro arquivo da lista: ouvidas uma vez)')
    reprovados = []
    paralelo = max(1, args.paralelo) if ouvido.paralelo else 1
    inicio = time.time()
    n = 0
    with ThreadPoolExecutor(max_workers=paralelo) as pool:
        futuros = [pool.submit(conferir_grupo, ouvido, g) for g in grupos]
        for fut in as_completed(futuros):
            for r in fut.result():
                n += 1
                marca = 'ok  ' if r['aprovado'] else 'REPROVADO'
                modelo = f' ({r["modelo"]})' if r.get('modelo') else ''
                duvidas = f'  dúvidas: {len(r["duvidas"])}' if r.get('duvidas') else ''
                igual = '  (igual)' if r.get('igual_a') else ''
                print(f'[{n}/{len(itens)}] {marca} {r["caminho"]}  '
                      f'{r.get("semelhanca", r.get("erro"))}{modelo}{duvidas}{igual}', flush=True)
                if not r['aprovado']:
                    reprovados.append(r)
    print(f'\naprovados {len(itens) - len(reprovados)} - reprovados {len(reprovados)} - '
          f'{(time.time() - inicio) / 60:.1f} min')
    for r in reprovados:
        print(' ', r['id'], r.get('diferencas') or r.get('erro'))
    if reprovados:
        cartoes = sorted({r['id'] for r in reprovados if not r['id'].startswith('peca-')})
        pecas = sorted({r['id'][5:] for r in reprovados if r['id'].startswith('peca-')})
        if cartoes:
            print(f'\nrefazer: python ferramentas/narrar.py --ids {",".join(cartoes)} --refazer')
        if pecas:
            print('\nrefazer as peças: apague o .wav de cada uma em pecas/<tradicao>/ e rode '
                  'narrar_trechos.py de novo (ele regera o que falta e remonta quem as usa): '
                  + ' '.join(pecas))
    return 1 if reprovados else 0


if __name__ == '__main__':
    sys.exit(main())
