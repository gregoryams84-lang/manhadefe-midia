#!/usr/bin/env python3
"""Monta a ENTREGA da temporada de teste `t0` — 2 capítulos de 10 s — para
o passeio no emulador (Task 9 da versão 5). Não publica nada: a pasta sai
no mesmo formato que o chat da novela entrega, e quem publica é o
publicar_temporada.py, num ambiente de teste (nada no main):

  python ferramentas/publicar_temporada.py <pasta> --midia <cópia temporária>
         --r2-prefixo teste/midia/ --motor microsoft

O que sai na pasta:
  temporada.json   id t0, "Temporada de teste", capítulos em datas
                   consecutivas a partir de --inicio, com os textos de dois
                   cartões reais do app (comum-001 e comum-002) — o lint do
                   app já os aprova
  NN-catolico.mp4, NN-evangelico.mp4   10 s de testsrc 720x1280 (ffmpeg),
                   com o título do capítulo e a tradição desenhados (no
                   passeio dá para ver QUAL versão tocou) e um tom senoidal
                   diferente por tradição
  NN.webp          a capa 1080x1350, com o título
  NN.srt           duas falas curtas

Uso:
  python ferramentas/temporada_de_teste.py <pasta de saída> --inicio AAAA-MM-DD [--app <raiz>]
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publicar_temporada as pt  # noqa: E402

ID = 't0'
TITULO = 'Temporada de teste'
CARTOES = ('comum-001', 'comum-002')
SEGUNDOS = 10
TOM = {'catolico': 440, 'evangelico': 660}
ROTULO = {'catolico': 'versão católica', 'evangelico': 'versão evangélica'}
# A fonte do título desenhado (drawtext); --fonte manda por cima.
FONTES = (Path('C:/Windows/Fonts/arial.ttf'), Path('C:/Windows/Fonts/segoeui.ttf'),
          Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
          Path('/System/Library/Fonts/Supplemental/Arial.ttf'))
SRT = ('1\n00:00:01,000 --> 00:00:04,000\nTemporada de teste, capítulo {n}.\n\n'
       '2\n00:00:05,000 --> 00:00:08,500\nManhã de Fé.\n')


def _ffmpeg(args, cwd):
    r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', *args], cwd=str(cwd),
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError(f'ffmpeg falhou: {r.stderr.strip()[:400]}')


def _texto(trabalho, nome, texto):
    """O texto do drawtext vai por arquivo (textfile=), relativo à pasta de
    trabalho: nem acento nem dois-pontos de caminho do Windows passam pela
    sintaxe de filtros do ffmpeg."""
    (trabalho / nome).write_text(texto, encoding='utf-8', newline='')
    return nome


def _desenho(arquivo_de_texto, tamanho, y):
    return (f'drawtext=fontfile=fonte.ttf:textfile={arquivo_de_texto}:fontcolor=white:'
            f'fontsize={tamanho}:x=(w-text_w)/2:y={y}')


def video(destino, trabalho, titulo, tradicao):
    largura, altura = pt.TAMANHO_DO_VIDEO
    filtro = ','.join([
        f'testsrc=size={largura}x{altura}:rate=25:duration={SEGUNDOS}',
        'drawbox=x=0:y=480:w=iw:h=300:color=black@0.7:t=fill',
        _desenho(_texto(trabalho, 'titulo.txt', titulo), 58, 530),
        _desenho(_texto(trabalho, 'tradicao.txt', ROTULO[tradicao]), 46, 640)])
    _ffmpeg(['-f', 'lavfi', '-i', filtro,
             '-f', 'lavfi', '-i', f'sine=frequency={TOM[tradicao]}:sample_rate=44100:duration={SEGUNDOS}',
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '64k', '-shortest', '-movflags', '+faststart',
             str(destino)], trabalho)


def capa(destino, trabalho, titulo):
    largura, altura = pt.TAMANHO_DA_CAPA
    filtro = ','.join([
        f'color=c=0x2E5E4E:size={largura}x{altura}:rate=1',
        _desenho(_texto(trabalho, 'temporada.txt', TITULO), 72, 560),
        _desenho(_texto(trabalho, 'titulo.txt', titulo), 60, 680)])
    _ffmpeg(['-f', 'lavfi', '-i', filtro, '-frames:v', '1', '-c:v', 'libwebp', '-quality', '80',
             str(destino)], trabalho)


def achar_fonte(pedida=None):
    for candidata in ([Path(pedida)] if pedida else FONTES):
        if candidata.exists():
            return candidata
    sys.exit(f'nenhuma fonte para o título (tentei {", ".join(str(f) for f in FONTES)}): '
             'aponte uma .ttf com --fonte')


def montar(saida, inicio, app, fonte):
    """Grava a entrega em `saida` (uma pasta nova ou vazia) e devolve o
    temporada.json escrito."""
    capitulos = []
    with tempfile.TemporaryDirectory(prefix='temporada-de-teste-') as tmp:
        trabalho = Path(tmp)
        shutil.copyfile(fonte, trabalho / 'fonte.ttf')
        for n, cartao in enumerate(CARTOES, 1):
            dados = json.loads((app / 'assets' / 'content' / 'cartoes' / f'{cartao}.json')
                               .read_text(encoding='utf-8'))
            titulo = f'Capítulo de teste {n}'
            capitulos.append({
                'n': n, 'data': (inicio + timedelta(days=n - 1)).isoformat(), 'titulo': titulo,
                'gancho': f'Teste da novela: o capítulo {n} de {len(CARTOES)}.',
                'referenciaBiblica': dados['referenciaBiblica'], 'versiculo': dados['versiculo'],
                'reflexao': dados['reflexao'], 'oracao': dados['oracao'], 'duracaoS': SEGUNDOS})
            for tradicao in pt.TRADICOES:
                video(saida / f'{n:02d}-{tradicao}.mp4', trabalho, titulo, tradicao)
            capa(saida / f'{n:02d}.webp', trabalho, titulo)
            (saida / f'{n:02d}.srt').write_text(SRT.format(n=n), encoding='utf-8', newline='')
    temporada = {'id': ID, 'titulo': TITULO, 'inicio': inicio.isoformat(), 'capitulos': capitulos}
    (saida / 'temporada.json').write_text(json.dumps(temporada, ensure_ascii=False, indent=2) + '\n',
                                          encoding='utf-8', newline='')
    return temporada


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('saida', help='a pasta da entrega (nova ou vazia)')
    ap.add_argument('--inicio', required=True, help='a data do capítulo 1, AAAA-MM-DD')
    ap.add_argument('--app', help='raiz do repo manha-de-fe-app, de onde vêm os textos '
                                  '(padrão: pasta-irmã, ou MANHA_DE_FE_APP)')
    ap.add_argument('--fonte', help='a .ttf do título desenhado (padrão: Arial do Windows)')
    args = ap.parse_args(argv)
    inicio = pt.data_valida(args.inicio)
    if inicio is None:
        sys.exit(f'--inicio "{args.inicio}" não é uma data AAAA-MM-DD que exista')
    app = Path(args.app) if args.app else pt.APP_PADRAO
    if not all((app / 'assets' / 'content' / 'cartoes' / f'{c}.json').exists() for c in CARTOES):
        sys.exit(f'{app} não tem assets/content/cartoes/{CARTOES[0]}.json e {CARTOES[1]}.json: '
                 'aponte o repo do app com --app')
    saida = Path(args.saida)
    if saida.exists() and any(saida.iterdir()):
        sys.exit(f'{saida} já tem arquivos: aponte uma pasta nova ou vazia (uma entrega não se '
                 'mistura com outra)')
    fonte = achar_fonte(args.fonte)
    saida.mkdir(parents=True, exist_ok=True)
    temporada = montar(saida, inicio, app, fonte)
    fim = temporada['capitulos'][-1]['data']
    print(f'entrega {ID} em {saida}: {len(CARTOES)} capítulos de {SEGUNDOS} s, de '
          f'{temporada["inicio"]} a {fim} (textos de {", ".join(CARTOES)})')
    print('publicar num ambiente de teste (nada no main): python ferramentas/publicar_temporada.py '
          f'"{saida}" --midia <cópia temporária do repo de mídia> --r2-prefixo teste/midia/ '
          '--motor microsoft')
    return 0


if __name__ == '__main__':
    sys.exit(main())
