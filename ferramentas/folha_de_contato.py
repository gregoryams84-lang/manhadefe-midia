#!/usr/bin/env python3
"""Folhas de contato para a conferência visual das imagens geradas.

Uso: python ferramentas/folha_de_contato.py [pasta=imagens] [saida=ferramentas/imagens/qa] [padrao=*.webp]

O padrão filtra os arquivos (ex.: '*-catolico.webp' só a arte sacra; 'comum-*.webp').

Monta grades de 3 x 4 miniaturas (270 x 338 cada) com o id escrito embaixo,
uma folha por 12 imagens, em ordem alfabética. Quem confere (revisor ou
Gregory) olha folha por folha e anota os ids reprovados; o gerador refaz só
esses (`gerar_imagens.py --refazer id,id`).
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parents[1]
COLUNAS, LINHAS = 3, 4
LARG, ALT, RODAPE, MARGEM = 270, 338, 28, 12


def main():
    pasta = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / 'imagens'
    saida = Path(sys.argv[2]) if len(sys.argv) > 2 else RAIZ / 'ferramentas' / 'imagens' / 'qa'
    saida.mkdir(parents=True, exist_ok=True)
    padrao = sys.argv[3] if len(sys.argv) > 3 else '*.webp'
    arquivos = sorted(pasta.glob(padrao))
    if not arquivos:
        sys.exit(f'nenhum .webp em {pasta}')
    try:
        fonte = ImageFont.truetype('arial.ttf', 16)
    except OSError:
        fonte = ImageFont.load_default()
    por_folha = COLUNAS * LINHAS
    total = (len(arquivos) + por_folha - 1) // por_folha
    for n in range(total):
        lote = arquivos[n * por_folha:(n + 1) * por_folha]
        folha = Image.new('RGB', (COLUNAS * (LARG + MARGEM) + MARGEM,
                                  LINHAS * (ALT + RODAPE + MARGEM) + MARGEM),
                          '#FBF6EC')
        desenho = ImageDraw.Draw(folha)
        for i, arq in enumerate(lote):
            im = Image.open(arq).convert('RGB')
            im.thumbnail((LARG, ALT))
            x = MARGEM + (i % COLUNAS) * (LARG + MARGEM)
            y = MARGEM + (i // COLUNAS) * (ALT + RODAPE + MARGEM)
            folha.paste(im, (x, y))
            desenho.text((x, y + ALT + 6), arq.stem, fill='#221D18', font=fonte)
        destino = saida / f'folha-{n + 1:02d}.png'
        folha.save(destino, optimize=True)
        print(f'{destino.name}: {lote[0].stem} … {lote[-1].stem}')
    print(f'{total} folhas, {len(arquivos)} imagens')


if __name__ == '__main__':
    main()
