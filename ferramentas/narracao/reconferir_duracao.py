# Reconferência de 15/10: a Microsoft cortou 3 respostas sem avisar. Regera
# cada texto (com a trava de resposta inteira) e compara a duração com o
# arquivo publicado; o que diferir é substituído (e anotado para reconferir
# por voz). Peças do Terço: só compara e lista.
import io, json, shutil, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, 'ferramentas')
import voz_microsoft as vm
from narrar import PARAMETROS_AAC, duracao_segundos, RAIZ
sys.stdout.reconfigure(encoding='utf-8')
itens = [json.loads(l) for l in io.open('ferramentas/narracao/narracoes.jsonl', encoding='utf-8')]
grupos = {}
for i in itens:
    grupos.setdefault((vm.VOZES[i['tradicao']], i['texto']), []).append(i)
tmp = RAIZ / 'ferramentas' / 'narracao' / 'regerados'
tmp.mkdir(exist_ok=True)

def um(grupo):
    primeiro = grupo[0]
    pcm, _ = vm.narrar(primeiro['texto'], primeiro['tradicao'])
    novo = tmp / Path(primeiro['caminho']).name
    vm.gravar_m4a(pcm, novo, PARAMETROS_AAC)
    atual = duracao_segundos(RAIZ / primeiro['caminho'])
    nova = duracao_segundos(novo)
    trocados = []
    if abs(atual - nova) > 0.1:
        for it in grupo:
            shutil.copyfile(novo, RAIZ / it['caminho'])
            trocados.append(it['caminho'])
    return primeiro['caminho'], atual, nova, trocados

ini = time.time()
diferentes = []
with ThreadPoolExecutor(max_workers=3) as pool:
    futs = [pool.submit(um, g) for g in grupos.values()]
    for n, f in enumerate(as_completed(futs), 1):
        try:
            cam, atual, nova, trocados = f.result()
        except Exception as e:
            print(f'[{n}/{len(futs)}] ERRO {e}', flush=True); continue
        if trocados:
            diferentes.append((cam, atual, nova))
            print(f'[{n}/{len(futs)}] TROCADO {cam}: {atual:.2f} s -> {nova:.2f} s ({len(trocados)} arquivo(s))', flush=True)
        elif n % 50 == 0:
            print(f'[{n}/{len(futs)}] igual até aqui', flush=True)
print(f'cartões/santos: {len(diferentes)} texto(s) trocado(s) de {len(futs)} em {(time.time()-ini)/60:.1f} min')
for cam, a, b in diferentes:
    print('  ', cam, f'{a:.2f} -> {b:.2f}')

# Peças do Terço e das orações: só compara.
pecas = sorted((RAIZ / 'ferramentas/narracao/trechos-microsoft/pecas').glob('*/*.json'))
dif_pecas = []
def peca(meta):
    d = json.loads(meta.read_text(encoding='utf-8'))
    pcm, _ = vm.narrar(d['texto'], d['tradicao'], silencio_final=0.0)
    return meta.stem, d['segundos'], round(vm.segundos_de(pcm), 3), d['texto'][:50]
with ThreadPoolExecutor(max_workers=3) as pool:
    for f in as_completed([pool.submit(peca, m) for m in pecas]):
        chave, antes, agora, texto = f.result()
        if abs(antes - agora) > 0.1:
            dif_pecas.append((chave, antes, agora, texto))
            print(f'PEÇA DIFERENTE {chave}: {antes:.2f} s -> {agora:.2f} s | {texto}', flush=True)
print(f'peças: {len(dif_pecas)} diferente(s) de {len(pecas)}')
print('TROCADOS:', json.dumps([c for c, _, _ in diferentes]))
