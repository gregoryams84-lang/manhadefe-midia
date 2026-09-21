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
versículos).

Resultado: ferramentas/narracao/stt.log.jsonl (uma linha por arquivo, com a
semelhança e as diferenças) e, no fim, a lista dos reprovados.

Uso:
  python ferramentas/conferir_stt.py                 # tudo que ainda não foi conferido
  python ferramentas/conferir_stt.py --ids comum-001
  python ferramentas/conferir_stt.py --so-listar     # reprovados do log
"""
import argparse
import difflib
import json
import os
import re
import sys
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
LIMIAR = 0.97  # abaixo disto, ou com palavra trocada, reprova

UNIDADES = {'zero': 0, 'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3,
            'quatro': 4, 'cinco': 5, 'seis': 6, 'sete': 7, 'oito': 8,
            'nove': 9, 'dez': 10, 'onze': 11, 'doze': 12, 'treze': 13,
            'catorze': 14, 'quatorze': 14, 'quinze': 15, 'dezesseis': 16,
            'dezasseis': 16, 'dezessete': 17, 'dezassete': 17, 'dezoito': 18,
            'dezenove': 19, 'dezanove': 19}
DEZENAS = {'vinte': 20, 'trinta': 30, 'quarenta': 40, 'cinquenta': 50,
           'sessenta': 60, 'setenta': 70, 'oitenta': 80, 'noventa': 90}
CENTENAS = {'cem': 100, 'cento': 100}

_trava = threading.Lock()


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
    a, b = normalizar(esperado), normalizar(ouvido)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    diferencas = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != 'equal':
            diferencas.append({'op': op, 'esperado': ' '.join(a[i1:i2]),
                               'ouvido': ' '.join(b[j1:j2])})
    return round(sm.ratio(), 4), diferencas


def conferir(chave, item):
    arquivo = RAIZ / item['caminho']
    registro = {'caminho': item['caminho'], 'id': item['id'],
                'quando': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'bytes': arquivo.stat().st_size}
    try:
        ouvido = transcrever(chave, arquivo)
        semelhanca, diferencas = comparar(item['texto'], ouvido)
        registro.update(ok=True, semelhanca=semelhanca, diferencas=diferencas,
                        aprovado=(semelhanca >= LIMIAR and not diferencas) or
                                 (semelhanca >= 0.995))
        if not registro['aprovado']:
            registro['ouvido'] = ouvido
    except Exception as e:  # noqa: BLE001
        registro.update(ok=False, erro=str(e)[:300], aprovado=False)
    with _trava:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(registro, ensure_ascii=False) + '\n')
    return registro


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
    ap.add_argument('--ids')
    ap.add_argument('--paralelo', type=int, default=3)
    ap.add_argument('--limite', type=int, default=0)
    ap.add_argument('--so-listar', action='store_true')
    args = ap.parse_args()

    vistos = ultimo_por_caminho()
    if args.so_listar:
        ruins = [r for r in vistos.values() if not r.get('aprovado')]
        for r in ruins:
            print(r['caminho'], r.get('semelhanca'), r.get('diferencas') or r.get('erro'))
        print(f'{len(ruins)} reprovados de {len(vistos)} conferidos')
        return 1 if ruins else 0

    itens = [i for i in ler_entrada(args.entrada) if (RAIZ / i['caminho']).exists()]
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

    chave = chave_api()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    reprovados = []
    with ThreadPoolExecutor(max_workers=max(1, args.paralelo)) as pool:
        futuros = [pool.submit(conferir, chave, i) for i in itens]
        for n, fut in enumerate(as_completed(futuros), 1):
            r = fut.result()
            marca = 'ok  ' if r['aprovado'] else 'REPROVADO'
            print(f'[{n}/{len(itens)}] {marca} {r["caminho"]}  {r.get("semelhanca", r.get("erro"))}')
            if not r['aprovado']:
                reprovados.append(r)
    print(f'\naprovados {len(itens) - len(reprovados)} - reprovados {len(reprovados)}')
    for r in reprovados:
        print(' ', r['id'], r.get('diferencas') or r.get('erro'))
    if reprovados:
        ids = ','.join(sorted({r['id'] for r in reprovados}))
        print(f'\nrefazer: python ferramentas/narrar.py --ids {ids} --refazer')
    return 1 if reprovados else 0


if __name__ == '__main__':
    sys.exit(main())
