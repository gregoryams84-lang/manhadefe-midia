#!/usr/bin/env python3
"""Narração em massa do Manhã de Fé (ElevenLabs, eleven_multilingual_v2).

Entrada: ferramentas/narracao/narracoes.jsonl, gerado no repo do app por
         `dart run tool/midia/texto_narrado.dart`; uma linha por áudio:
         {"id": "comum-001", "tradicao": "catolico",
          "caminho": "narracao/catolico/comum-001.m4a", "texto": "..."}
Saída:   <raiz do repo>/<caminho>  em AAC mono ~32 kbps (.m4a)
Log:     ferramentas/narracao/narrar.log.jsonl (uma linha por tentativa)

Vozes e parâmetros: os aprovados por Gregory em 14/09/2026
(docs/fase4/narracao-parametros.md, no repo do app). As pausas vão como tags
<break time="..."/> dentro do texto; a voz não lê as tags.

Depois de gerar, rode ferramentas/conferir_stt.py: todo arquivo passa por
reconhecimento de fala e o texto reconhecido é comparado com o enviado.

A chave da ElevenLabs vem de ELEVENLABS_API_KEY ou do arquivo de Gregory
(caminho em CHAVE_PADRAO). Nunca é impressa nem gravada.

Uso:
  python ferramentas/narrar.py --so-contar                 # caracteres e saldo
  python ferramentas/narrar.py --prefixos comum,advento,natal --paralelo 4
  python ferramentas/narrar.py --ids comum-001 --refazer
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / 'ferramentas' / 'narracao' / 'narracoes.jsonl'
LOG = RAIZ / 'ferramentas' / 'narracao' / 'narrar.log.jsonl'
CHAVE_PADRAO = Path('C:/Users/robot/OneDrive/Área de Trabalho/NUVEM GREGORY/'
                    'Eleven 1/Eleven 1.md')
API = 'https://api.elevenlabs.io/v1'
MODELO = 'eleven_multilingual_v2'

VOZES = {
    'evangelico': {
        'voice_id': 'dSaUrotvfAiroXLetqrt',  # "Pastor do Evangelho"
        'voice_settings': {'stability': 0.62, 'similarity_boost': 0.80,
                           'style': 0.10, 'use_speaker_boost': True,
                           'speed': 0.82},
    },
    'catolico': {
        'voice_id': 'sd6xYPXxCQaSyru9acjV',  # "Padre Católico"
        'voice_settings': {'stability': 0.58, 'similarity_boost': 0.85,
                           'style': 0.20, 'use_speaker_boost': True,
                           'speed': 0.85},
    },
}

_trava_log = threading.Lock()


def chave_api():
    k = os.environ.get('ELEVENLABS_API_KEY')
    if k:
        return k.strip()
    texto = CHAVE_PADRAO.read_text(encoding='utf-8', errors='replace')
    m = re.search(r'sk_[A-Za-z0-9]+', texto)
    if not m:
        sys.exit('chave da ElevenLabs (sk_...) não encontrada')
    return m.group(0)


def saldo(chave):
    """O saldo da conta, ou None se a ElevenLabs recusar a chave.

    Devolver None em vez de estourar deixa o --so-contar continuar servindo
    para planejar o lote nos dias em que a chave esta vencida ou trocada.
    """
    req = urllib.request.Request(f'{API}/user/subscription',
                                 headers={'xi-api-key': chave})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        corpo = e.read()[:200].decode('utf-8', 'replace')
        print(f'aviso: a ElevenLabs recusou a chave (HTTP {e.code}): {corpo}')
        return None
    return {'plano': d.get('tier'), 'usados': d.get('character_count'),
            'limite': d.get('character_limit'),
            'restam': (d.get('character_limit') or 0) - (d.get('character_count') or 0)}


def ler_entrada(caminho):
    itens = []
    with open(caminho, encoding='utf-8') as f:
        for n, linha in enumerate(f, 1):
            linha = linha.strip()
            if not linha:
                continue
            item = json.loads(linha)
            for campo in ('id', 'tradicao', 'caminho', 'texto'):
                if campo not in item:
                    sys.exit(f'{caminho}:{n}: falta "{campo}"')
            if item['tradicao'] not in VOZES:
                sys.exit(f'{caminho}:{n}: tradição desconhecida {item["tradicao"]!r}')
            itens.append(item)
    return itens


def sintetizar(chave, item, normalizacao):
    voz = VOZES[item['tradicao']]
    corpo = {'text': item['texto'], 'model_id': MODELO,
             'voice_settings': voz['voice_settings'],
             'apply_text_normalization': normalizacao}
    url = f'{API}/text-to-speech/{voz["voice_id"]}?output_format=mp3_44100_128'
    req = urllib.request.Request(
        url, data=json.dumps(corpo).encode('utf-8'), method='POST',
        headers={'xi-api-key': chave, 'Content-Type': 'application/json',
                 'Accept': 'audio/mpeg'})
    for tentativa in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read(), r.headers.get('request-id')
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


# O formato de entrega de toda narração do app (docs/fase4/narracao-parametros.md):
# AAC mono ~32 kbps. Fica numa constante porque narrar_trechos.py monta os
# áudios embutidos (terço e orações) com o mesmo codec — um só lugar para mudar.
PARAMETROS_AAC = ['-c:a', 'aac', '-b:a', '32k', '-ac', '1', '-ar', '44100',
                  '-movflags', '+faststart']


def duracao_segundos(caminho):
    """A duração real do arquivo, medida pelo ffprobe (nunca estimada)."""
    dur = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nw=1:nk=1', str(caminho)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(dur)


def para_m4a(mp3, destino):
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as t:
        t.write(mp3)
        origem = t.name
    parcial = destino.with_suffix('.parte.m4a')
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-loglevel', 'error', '-i', origem,
             *PARAMETROS_AAC, str(parcial)],
            check=True)
        parcial.replace(destino)
    finally:
        os.unlink(origem)
        if parcial.exists():
            parcial.unlink()
    return duracao_segundos(destino), destino.stat().st_size


def registrar(registro, arquivo=LOG):
    """Uma linha de jsonl por tentativa. `arquivo` existe porque
    narrar_trechos.py tem o próprio log, na mesma pasta."""
    with _trava_log:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        with open(arquivo, 'a', encoding='utf-8') as f:
            f.write(json.dumps(registro, ensure_ascii=False) + '\n')


def fazer(chave, item, normalizacao):
    destino = RAIZ / item['caminho']
    registro = {'caminho': item['caminho'], 'id': item['id'],
                'tradicao': item['tradicao'], 'caracteres': len(item['texto']),
                'quando': time.strftime('%Y-%m-%dT%H:%M:%S')}
    try:
        mp3, pedido = sintetizar(chave, item, normalizacao)
        segundos, tamanho = para_m4a(mp3, destino)
        registro.update(ok=True, segundos=round(segundos, 2), bytes=tamanho,
                        pedido=pedido)
    except Exception as e:  # noqa: BLE001
        registro.update(ok=False, erro=str(e)[:300])
    registrar(registro)
    return registro


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entrada', default=str(ENTRADA))
    ap.add_argument('--prefixos', help='ids que começam por: comum,advento,natal,10-,movel-')
    ap.add_argument('--ids', help='ids exatos, separados por vírgula')
    ap.add_argument('--tradicao', choices=sorted(VOZES))
    ap.add_argument('--pastas', help='primeira pasta do caminho: narracao,santos')
    ap.add_argument('--limite', type=int, default=0)
    ap.add_argument('--refazer', action='store_true')
    ap.add_argument('--paralelo', type=int, default=3)
    ap.add_argument('--normalizacao', default='auto', choices=['auto', 'on', 'off'])
    ap.add_argument('--so-contar', action='store_true')
    ap.add_argument('--forcar', action='store_true',
                    help='segue mesmo se o saldo não cobrir tudo')
    args = ap.parse_args()

    itens = ler_entrada(args.entrada)
    if args.prefixos:
        pref = tuple(p.strip() for p in args.prefixos.split(','))
        itens = [i for i in itens if i['id'].startswith(pref)]
    if args.ids:
        quero = set(args.ids.split(','))
        itens = [i for i in itens if i['id'] in quero]
    if args.tradicao:
        itens = [i for i in itens if i['tradicao'] == args.tradicao]
    if args.pastas:
        pastas = tuple(p.strip() + '/' for p in args.pastas.split(','))
        itens = [i for i in itens if i['caminho'].startswith(pastas)]
    if not args.refazer:
        itens = [i for i in itens if not (RAIZ / i['caminho']).exists()]
    if args.limite:
        itens = itens[:args.limite]

    total = sum(len(i['texto']) for i in itens)
    milhar = f'{total:,}'.replace(',', '.')
    print(f'a gerar: {len(itens)} áudios, {milhar} caracteres')
    chave = chave_api()
    s = saldo(chave)
    if s:
        print(f'plano {s["plano"]}: {s["usados"]} usados de {s["limite"]}, restam {s["restam"]}')
    if args.so_contar or not itens:
        return 0
    if s is None:
        sys.exit(f'sem chave válida: troque a chave em {CHAVE_PADRAO.name} '
                 '(ou em ELEVENLABS_API_KEY) e rode de novo')
    if total > s['restam'] and not args.forcar:
        sys.exit('o saldo não cobre este lote; reduza com --prefixos/--limite ou use --forcar')

    feitos = erros = 0
    inicio = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.paralelo)) as pool:
        futuros = {pool.submit(fazer, chave, i, args.normalizacao): i for i in itens}
        for n, fut in enumerate(as_completed(futuros), 1):
            r = fut.result()
            if r['ok']:
                feitos += 1
                print(f'[{n}/{len(itens)}] ok   {r["caminho"]}  {r["segundos"]}s  {r["bytes"] // 1024} KB')
            else:
                erros += 1
                print(f'[{n}/{len(itens)}] ERRO {r["caminho"]}  {r["erro"]}')
    minutos = (time.time() - inicio) / 60
    print(f'\ngerados {feitos} - erros {erros} - {minutos:.1f} min')
    return 1 if erros else 0


if __name__ == '__main__':
    sys.exit(main())
