#!/usr/bin/env python3
"""Baixa pinturas em domínio público do Wikimedia Commons e recorta em 4:5.

Serve para a arte sacra do perfil católico (imagens/<id>-catolico.webp) e
para os retratos dos santos (santos/<slug>.webp).

Entrada: um JSON de escolhas, por destino relativo ao repo de mídia:

    {
      "imagens/comum-001-catolico.webp": {
        "arquivo": "File:Bloch-SermonOnTheMount.jpg",
        "foco": 0.45,               # opcional: 0 = topo, 0.5 = centro, 1 = base
        "recorte": [x0, y0, x1, y1] # opcional: fração 0..1 da largura/altura
      },
      "santos/sao-benedito.webp": { "arquivo": "File:..." }
    }

Saída: o .webp em 1080 x 1350 (q82, alvo <= 120 KB; a qualidade desce de 82 até 40 para chegar lá) e, ao lado do JSON de
entrada, um <nome>-creditos.json com título, artista, data, licença e URL de
cada arquivo (vai para a tela de Créditos do app). Só aceita licenças de
domínio público (PD-*, CC0) — qualquer outra é recusada e registrada.

Uso: python ferramentas/baixar_commons.py ferramentas/imagens/arte-sacra.json [--refazer]
"""
import argparse
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
API = 'https://commons.wikimedia.org/w/api.php'
AGENTE = 'ManhaDeFeMidia/1.0 (contato@manhadefe.com.br)'
LARGURA, ALTURA = 1080, 1350
ALVO_BYTES = 120 * 1024
LICENCAS_OK = re.compile(r'^(pd|public domain|cc0)', re.I)


def api(params):
    params = dict(params, format='json')
    url = API + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': AGENTE})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def info_do_arquivo(titulo):
    dados = api({'action': 'query', 'titles': titulo, 'prop': 'imageinfo',
                 'iiprop': 'url|extmetadata|size', 'iiurlwidth': 2000})
    paginas = dados['query']['pages']
    pagina = next(iter(paginas.values()))
    if 'missing' in pagina or 'imageinfo' not in pagina:
        raise RuntimeError(f'{titulo}: não existe no Commons')
    ii = pagina['imageinfo'][0]
    meta = ii.get('extmetadata', {})

    def campo(nome):
        return re.sub(r'<[^>]+>', '', meta.get(nome, {}).get('value', '')).strip()

    return {
        'titulo': limpar_titulo(campo('ObjectName') or campo('ImageDescription')),
        'artista': campo('Artist'),
        'data': limpar_data(campo('DateTimeOriginal')),
        'licenca': campo('LicenseShortName'),
        'url': ii.get('descriptionurl'),
        'thumb': ii.get('thumburl') or ii['url'],
        'largura': ii.get('width'),
        'altura': ii.get('height'),
    }


def limpar_titulo(texto):
    """O Commons devolve o título com marcação multilíngue ('title QS:P1476,
    da:...label QS:Len,...'); fica só o rótulo em português, senão o inglês,
    senão o primeiro texto antes da marcação."""
    for lingua in ('pt', 'en'):
        m = re.search(r'label QS:L' + lingua + r',"([^"]+)"', texto)
        if m:
            return m.group(1).strip()
    texto = re.split(r'title QS:|label QS:', texto)[0]
    texto = re.sub(r'^[A-Za-z]+:\s*', '', texto)  # "Danish: " e afins
    return texto.strip()[:120]


def limpar_data(texto):
    """O Commons cola marcação do Wikidata na data ('1660 date QS:P571,...')."""
    return re.split(r'\s*date QS:|\s*QS:P', texto)[0].strip()


def baixar(url):
    req = urllib.request.Request(url, headers={'User-Agent': AGENTE})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def recortar(dados, foco, recorte):
    im = Image.open(io.BytesIO(dados)).convert('RGB')
    w, h = im.size
    if recorte:
        x0, y0, x1, y1 = recorte
        im = im.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))
        w, h = im.size
    alvo = LARGURA / ALTURA
    if w / h > alvo:  # larga demais: corta os lados, centrado
        nw = round(h * alvo)
        x0 = (w - nw) // 2
        im = im.crop((x0, 0, x0 + nw, h))
    else:  # alta demais: corta em cima/embaixo conforme o foco
        nh = round(w / alvo)
        y0 = round((h - nh) * foco)
        im = im.crop((0, y0, w, y0 + nh))
    im = im.resize((LARGURA, ALTURA), Image.LANCZOS)
    q = 82
    while True:
        buf = io.BytesIO()
        im.save(buf, 'WEBP', quality=q, method=6)
        if buf.tell() <= ALVO_BYTES or q <= 40:
            return buf.getvalue(), q
        q -= 6


def main():
    # Nomes de arquivo em cirílico ou grego derrubavam o print no console do
    # Windows (cp1252) e o script morria no meio, sem mensagem.
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, 'reconfigure'):
            fluxo.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('escolhas')
    ap.add_argument('--refazer', action='store_true')
    ap.add_argument('--refazer-acima-de', type=int, default=0, metavar='BYTES',
                    help='refaz só os arquivos já baixados que passam deste tamanho')
    ap.add_argument('--pausa', type=float, default=1.0)
    args = ap.parse_args()

    entrada = Path(args.escolhas)
    escolhas = json.load(open(entrada, encoding='utf-8'))
    creditos_path = entrada.with_name(entrada.stem + '-creditos.json')
    creditos = {}
    if creditos_path.exists():
        creditos = json.load(open(creditos_path, encoding='utf-8'))

    feitos = pulados = erros = 0
    for destino_rel, escolha in escolhas.items():
        destino = RAIZ / destino_rel
        pesado = (args.refazer_acima_de and destino.exists()
                  and destino.stat().st_size > args.refazer_acima_de)
        if destino.exists() and not args.refazer and not pesado and destino_rel in creditos:
            pulados += 1
            continue
        titulo = escolha['arquivo']
        print(f'{destino_rel} <- {titulo}')
        try:
            info = info_do_arquivo(titulo)
            if not LICENCAS_OK.match(info['licenca'] or ''):
                raise RuntimeError(f'licença não aceita: {info["licenca"]!r}')
            if (info['largura'] or 0) < 900:
                raise RuntimeError(f'resolução baixa: {info["largura"]}px')
            dados = baixar(info['thumb'])
            webp, q = recortar(dados, escolha.get('foco', 0.5), escolha.get('recorte'))
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(webp)
            creditos[destino_rel] = {
                'arquivo': titulo,
                'titulo': escolha.get('titulo') or info['titulo'],
                'artista': info['artista'], 'data': info['data'],
                'licenca': info['licenca'], 'url': info['url'],
            }
            feitos += 1
            print(f'    ok  {len(webp) // 1024} KB  q={q}  {info["licenca"]}  {info["artista"][:40]}')
        except Exception as e:  # noqa: BLE001
            erros += 1
            print(f'    ERRO {e}')
        json.dump(creditos, open(creditos_path, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2, sort_keys=True)
        time.sleep(args.pausa)
    print(f'\nbaixadas {feitos} - ja existiam {pulados} - erros {erros}')
    return 1 if erros else 0


if __name__ == '__main__':
    sys.exit(main())
