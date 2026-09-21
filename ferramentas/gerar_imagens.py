#!/usr/bin/env python3
"""Gera as imagens neutras do Manhã de Fé (estilo B, aquarela) com o Gemini.

Entrada: ferramentas/imagens/cenas.json  {"<id>": "<primeira frase da cena>"}
Saída:   imagens/<id>.webp  (1080 x 1350, WebP, alvo <= 120 KB)
Log:     ferramentas/imagens/gerar.log.jsonl  (uma linha por tentativa)

A receita é a de docs/fase4/estilo-das-imagens.md (repo do app): só a primeira
frase muda por cartão; o bloco de estilo é fixo e a referência aprovada vai
anexada em toda geração. Imagem reprovada na conferência é gerada de novo
(--refazer id,id), nunca editada à mão.

A chave do Gemini vem da variável GOOGLE_AI_API_KEY ou da configuração do
MCP nanobanana em ~/.claude.json. Nunca é impressa nem gravada.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
CENAS = RAIZ / 'ferramentas' / 'imagens' / 'cenas.json'
LOG = RAIZ / 'ferramentas' / 'imagens' / 'gerar.log.jsonl'
SAIDA = RAIZ / 'imagens'
REFERENCIA = Path(
    'C:/Users/robot/dev/manha-de-fe-app/docs/fase4/referencias/'
    'estilo-B-aquarela-comum-001.png')
MODELO = 'gemini-3.1-flash-image-preview'
LARGURA, ALTURA = 1080, 1350
ALVO_BYTES = 120 * 1024

ABERTURA = 'Pintura suave e serena para um aplicativo devocional: '
BLOCO_FIXO = (
    'Sem pessoas, sem rostos, sem mãos, sem símbolos religiosos, sem texto '
    'nem letras. Paleta: creme quente #FBF6EC dominante, dourado #C8952E, '
    'verde suave, toques de azul #1E3A5F. Estilo aquarela/guache delicado, '
    'granulado de papel, sensação de calma. As bordas superior e inferior se '
    'dissolvem gradualmente em creme #FBF6EC (vinheta clara), para fundir '
    'com fundo creme. Composição vertical 4:5, horizonte baixo, muito espaço '
    'respirável. Mesmo estilo, granulado de papel, luz e paleta da imagem de '
    'referência anexada.')
# Cenas simbólicas do Santo do dia (camada católica): o mesmo estilo, mas
# aqui cruz, terço, hábito dobrado e cálice PODEM aparecer. Continua sem
# pessoa nenhuma: é o lugar e os objetos do santo, nunca um retrato.
BLOCO_SANTOS = BLOCO_FIXO.replace(
    'Sem pessoas, sem rostos, sem mãos, sem símbolos religiosos, sem texto '
    'nem letras.',
    'Sem pessoas, sem rostos, sem mãos, sem figuras humanas nem estátuas de '
    'gente, sem texto nem letras. Objetos de devoção católica podem aparecer '
    'com discrição.')
assert BLOCO_SANTOS != BLOCO_FIXO


def chave_api():
    k = os.environ.get('GOOGLE_AI_API_KEY')
    if k:
        return k
    cfg = json.load(open(Path.home() / '.claude.json', encoding='utf-8'))

    def procurar(no):
        if isinstance(no, dict):
            if 'nanobanana-mcp' in no:
                return no['nanobanana-mcp']['env']['GOOGLE_AI_API_KEY']
            for v in no.values():
                r = procurar(v)
                if r:
                    return r
        elif isinstance(no, list):
            for v in no:
                r = procurar(v)
                if r:
                    return r
        return None

    k = procurar(cfg)
    if not k:
        sys.exit('chave do Gemini não encontrada (GOOGLE_AI_API_KEY)')
    return k


def prompt_de(cena, santos=False):
    bloco = BLOCO_SANTOS if santos else BLOCO_FIXO
    return ABERTURA + cena.strip().rstrip('.') + '. ' + bloco


def gerar_png(chave, modelo, prompt, referencia_b64):
    corpo = {
        'contents': [{
            'parts': [
                {'text': prompt},
                {'inlineData': {'mimeType': 'image/png', 'data': referencia_b64}},
            ],
        }],
        'generationConfig': {
            'responseModalities': ['IMAGE'],
            'imageConfig': {'aspectRatio': '4:5'},
        },
    }
    url = ('https://generativelanguage.googleapis.com/v1beta/models/'
           f'{modelo}:generateContent')
    req = urllib.request.Request(
        url, data=json.dumps(corpo).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-goog-api-key': chave},
        method='POST')
    dados = None
    for tentativa in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                dados = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            texto = e.read()[:300].decode('utf-8', 'replace')
            if e.code in (429, 500, 502, 503, 504) and tentativa < 5:
                espera = 12 * tentativa
                print(f'    HTTP {e.code}, tentando de novo em {espera}s: {texto}')
                time.sleep(espera)
                continue
            raise RuntimeError(f'HTTP {e.code}: {texto}') from None
    for cand in dados.get('candidates', []):
        for parte in cand.get('content', {}).get('parts', []):
            d = parte.get('inlineData', {}).get('data')
            if d:
                return base64.b64decode(d)
    motivo = json.dumps(dados)[:400]
    raise RuntimeError(f'resposta sem imagem: {motivo}')


def para_webp(png_bytes, destino):
    im = Image.open(io.BytesIO(png_bytes)).convert('RGB')
    w, h = im.size
    escala = max(LARGURA / w, ALTURA / h)
    im = im.resize((round(w * escala), round(h * escala)), Image.LANCZOS)
    w, h = im.size
    x0, y0 = (w - LARGURA) // 2, (h - ALTURA) // 2
    im = im.crop((x0, y0, x0 + LARGURA, y0 + ALTURA))
    q = 82
    while True:
        buf = io.BytesIO()
        im.save(buf, 'WEBP', quality=q, method=6)
        if buf.tell() <= ALVO_BYTES or q <= 60:
            break
        q -= 6
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(buf.getvalue())
    return buf.tell(), q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cenas', default=str(CENAS))
    ap.add_argument('--saida', default=str(SAIDA))
    ap.add_argument('--ids', help='lista separada por vírgula')
    ap.add_argument('--limite', type=int, default=0)
    ap.add_argument('--refazer', help='ids a gerar de novo mesmo existindo')
    ap.add_argument('--modelo', default=MODELO)
    ap.add_argument('--pausa', type=float, default=2.0)
    ap.add_argument('--santos', action='store_true',
                    help='cenas simbólicas do Santo do dia: objetos de devoção '
                         'católica permitidos (use com --cenas .../cenas-santos.json '
                         '--saida santos)')
    args = ap.parse_args()

    cenas = json.load(open(args.cenas, encoding='utf-8'))
    saida = Path(args.saida)
    refazer = set(args.refazer.split(',')) if args.refazer else set()
    ids = args.ids.split(',') if args.ids else list(cenas)
    if args.limite:
        ids = ids[:args.limite]
    chave = chave_api()
    ref_b64 = base64.b64encode(REFERENCIA.read_bytes()).decode('ascii')

    feitos = pulados = erros = 0
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as log:
        for i, id_ in enumerate(ids, 1):
            destino = saida / f'{id_}.webp'
            if destino.exists() and id_ not in refazer:
                pulados += 1
                continue
            cena = cenas[id_]
            prompt = prompt_de(cena, santos=args.santos)
            print(f'[{i}/{len(ids)}] {id_}: {cena[:70]}...')
            registro = {'id': id_, 'modelo': args.modelo, 'cena': cena,
                        'quando': time.strftime('%Y-%m-%dT%H:%M:%S')}
            try:
                png = gerar_png(chave, args.modelo, prompt, ref_b64)
                tamanho, q = para_webp(png, destino)
                registro.update(ok=True, bytes=tamanho, qualidade=q)
                feitos += 1
                print(f'    ok  {tamanho // 1024} KB  q={q}')
            except Exception as e:  # noqa: BLE001
                registro.update(ok=False, erro=str(e)[:300])
                erros += 1
                print(f'    ERRO {e}')
            log.write(json.dumps(registro, ensure_ascii=False) + '\n')
            log.flush()
            time.sleep(args.pausa)
    print(f'\ngeradas {feitos} - ja existiam {pulados} - erros {erros}')
    return 1 if erros else 0


if __name__ == '__main__':
    sys.exit(main())
