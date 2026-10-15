#!/usr/bin/env python3
"""A voz gratuita da Microsoft (Edge, pelo pacote edge-tts) nas narrações do
Manhã de Fé.

FASE ATUAL (decisão de Gregory, 14/10/2026): o app sai com a voz neural
`pt-BR-AntonioNeural` em TODAS as narrações — cartões e dias fixos (as duas
tradições), santos, Terço e orações guiadas — até as vozes do bispo e do
pastor (ElevenLabs, narrar.py) entrarem, em novembro, mês a mês. Trocar a
voz depois é só gerar e publicar: o app baixa de novo todo arquivo cujo
sha256 muda no manifesto (lib/midia/cache_de_midia.dart).

O ritmo é o aprovado em 14/09 (docs/fase4/narracao-parametros.md, no repo do
app): ~120 palavras por minuto no total, com as pausas do molde. Como a voz
da Microsoft não lê as tags <break> (o edge-tts não aceita SSML), o texto é
cortado nas tags e cada trecho vira um pedido próprio; a Microsoft deixa
bordas de silêncio em cada resposta (~0,18 s antes e ~0,88 s depois, medido
em 14/10), que são aparadas até uma margem curta; e a pausa da tag entra
como silêncio EXATO, em PCM, antes de uma única codificação AAC.

A velocidade (-12%) foi calibrada em 14/10 no cartão comum-001 com este
mesmo caminho: 38,6 s no total e 33,2 s de fala, contra 39,1 s / 32,3 s do
padre e 38,0 s / 31,8 s do pastor aprovados (5 - Histórico e amostras/
Amostras de voz (aprovadas)). Mudar VELOCIDADE muda o ritmo de tudo.

O edge-tts fala com um serviço não documentado do Edge: sem chave, sem
custo, sem garantia. Falha de rede é tentada de novo; silêncio no lugar da
voz nunca passa (a resposta sem áudio é erro). Todo arquivo gerado passa
depois por conferir_stt.py.
"""
import asyncio
import re
import struct
import subprocess
import time

MOTOR = 'microsoft'
# As duas tradições na mesma voz nesta fase (ver o topo). O dicionário tem as
# duas chaves porque narrar.py e narrar_trechos.py escolhem a voz pela
# tradição — quando o pastor e o padre entrarem, cada uma volta à sua.
VOZES = {'catolico': 'pt-BR-AntonioNeural', 'evangelico': 'pt-BR-AntonioNeural'}
VELOCIDADE = '-12%'
TAXA = 44100  # PCM mono nesta taxa, a mesma dos .m4a do projeto
# Bordas: o que sobra de silêncio em volta da fala de cada trecho depois de
# aparar. A de depois imita a respiração curta no fim de uma frase; o
# silêncio da pausa (tag) vem além dela.
MARGEM_ANTES = 0.10
MARGEM_DEPOIS = 0.20
# Abaixo disto (de 32767; uns -44 dB) é silêncio para o aparador.
LIMIAR_DE_SILENCIO = 200
# Silêncio no fim do arquivo de um cartão/santo, para o "Amém" (ou a frase
# do santo) não terminar seco — o mesmo papel da PAUSA_DE_SAIDA do Terço.
SILENCIO_FINAL = 0.5
TENTATIVAS = 5
TEMPO_LIMITE = 120  # segundos por pedido

_BREAK = re.compile(r'\s*<break time="([0-9.]+)s"\s*/>\s*')


def segmentar(texto):
    """[(trecho, pausa depois em segundos)] a partir do texto com tags
    <break time="1.2s" />. Tags seguidas somam; tag antes de qualquer texto
    é ignorada (não há o que esperar); o último trecho fica com pausa 0 —
    quem monta decide o silêncio final."""
    partes = _BREAK.split(texto)
    trechos = []
    for i in range(0, len(partes), 2):
        trecho = partes[i].strip()
        pausa = float(partes[i + 1]) if i + 1 < len(partes) else 0.0
        if trecho:
            trechos.append([trecho, pausa])
        elif trechos:
            trechos[-1][1] += pausa
    return [(t, round(p, 3)) for t, p in trechos]


def texto_sem_tags(texto):
    return re.sub(r'\s+', ' ', _BREAK.sub(' ', texto)).strip()


def aparar(pcm, antes=MARGEM_ANTES, depois=MARGEM_DEPOIS, limiar=LIMIAR_DE_SILENCIO):
    """Tira o silêncio das pontas do PCM (16 bits mono), guardando as
    margens. PCM todo silencioso volta vazio: a montagem acusa."""
    n = len(pcm) // 2
    valores = struct.unpack(f'<{n}h', pcm[:n * 2])
    i = 0
    while i < n and abs(valores[i]) < limiar:
        i += 1
    if i == n:
        return b''
    j = n
    while j > i and abs(valores[j - 1]) < limiar:
        j -= 1
    i = max(0, i - int(antes * TAXA))
    j = min(n, j + int(depois * TAXA))
    return pcm[i * 2:j * 2]


def silencio(segundos):
    return bytes(int(round(segundos * TAXA)) * 2)


def segundos_de(pcm):
    return len(pcm) / (TAXA * 2)


def _ffmpeg(args, entrada):
    r = subprocess.run(['ffmpeg', '-v', 'error', *args], input=entrada,
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f'ffmpeg falhou: {r.stderr.decode("utf-8", "replace")[:400]}')
    return r.stdout


def pcm_de_audio(audio):
    """Qualquer áudio (o mp3 da Microsoft) → PCM 16 bits mono na TAXA."""
    return _ffmpeg(['-i', '-', '-f', 's16le', '-ac', '1', '-ar', str(TAXA), '-'], audio)


async def _pedir(texto, voz, velocidade):
    """(mp3, limites): o áudio e os limites de palavra que o Edge manda
    junto — `(texto da palavra, fim em segundos)`, na ordem."""
    import edge_tts  # só aqui: o resto do módulo (segmentar, aparar) não precisa dele
    partes, limites = [], []
    comunicado = edge_tts.Communicate(texto, voz, rate=velocidade, boundary='WordBoundary')
    async for parte in comunicado.stream():
        if parte['type'] == 'audio':
            partes.append(parte['data'])
        elif parte['type'] == 'WordBoundary':
            limites.append((parte['text'], (parte['offset'] + parte['duration']) / 1e7))
    return b''.join(partes), limites


_PALAVRA = re.compile(r'[^\W_]+', re.UNICODE)


def _miolo(palavra):
    """Só letras e algarismos, minúsculos: "puseram-lhe." e "puseram-lhe"
    são a mesma palavra."""
    return ''.join(_PALAVRA.findall(palavra)).lower()


# A Microsoft às vezes corta a resposta no meio e não avisa: em 14/10, três
# de 1.185 áudios vieram com 1 a 15 s a menos, sem erro nenhum — a
# conferência por voz é que pegou. Os limites de palavra denunciam o corte:
# a última palavra do texto tem de ter chegado, e o áudio tem de durar até
# o fim dela.
FOLGA_DO_FIM = 0.3  # segundos: o fim do último limite pode passar um pouco do áudio decodificado


def incompleto(texto, limites, segundos):
    """None se a resposta está inteira; senão, o motivo. Função pura — os
    testes a conferem com limites inventados.

    Um limite costuma ser uma palavra, mas data, número e numeral romano
    chegam num limite só ("em 5 de setembro de 1997", "João XXIII"): por
    isso a prova é o FIM do que chegou, juntando todos os limites, contra a
    última palavra do texto — e não o texto do último limite sozinho (em
    15/10 isso recusou 125 santos inteiros)."""
    palavras = [p for p in (_miolo(p) for p in texto.split()) if p]
    if not palavras:
        return None
    if not limites:
        return 'sem limites de palavra na resposta'
    chegou = ''.join(_miolo(t) for t, _ in limites)
    if not chegou.endswith(palavras[-1]):
        return f'a resposta parou em "{limites[-1][0]}" (a última palavra é "{palavras[-1]}")'
    fim = limites[-1][1]
    if segundos + FOLGA_DO_FIM < fim:
        return f'o áudio tem {segundos:.2f} s e a última palavra termina em {fim:.2f} s'
    return None


def sintetizar_pcm(texto, voz, velocidade=VELOCIDADE):
    """O PCM de um trecho, pedido ao Edge e conferido inteiro ([incompleto]);
    tenta de novo em falha de rede, resposta vazia ou cortada. Pode rodar
    em várias threads (cada chamada tem o seu event loop)."""
    erro = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            mp3, limites = asyncio.run(asyncio.wait_for(_pedir(texto, voz, velocidade), TEMPO_LIMITE))
            if not mp3:
                erro = 'resposta sem áudio'
            else:
                pcm = pcm_de_audio(mp3)
                erro = incompleto(texto, limites, segundos_de(pcm))
                if erro is None:
                    return pcm
        except Exception as e:  # noqa: BLE001 — rede, serviço, tempo esgotado
            erro = f'{type(e).__name__}: {str(e)[:200]}'
        if tentativa < TENTATIVAS:
            time.sleep(5 * tentativa)
    raise RuntimeError(f'Microsoft ({voz}) não entregou "{texto[:40]}…" inteiro: {erro}')


def narrar(texto, tradicao, velocidade=VELOCIDADE, silencio_final=SILENCIO_FINAL,
           sintetizar=sintetizar_pcm):
    """O PCM completo de um texto com tags: trecho a trecho, bordas aparadas,
    pausas exatas, silêncio final. Devolve (pcm, trechos) — `trechos` é a
    lista `{texto, segundos, pausa}` para o log. `sintetizar(texto, voz,
    velocidade) -> pcm` existe para os testes trocarem a voz por um sinal."""
    voz = VOZES[tradicao]
    pedacos, trechos = [], []
    for n, (trecho, pausa) in enumerate(segmentar(texto), 1):
        pcm = aparar(sintetizar(trecho, voz, velocidade))
        if not pcm:
            raise RuntimeError(f'trecho {n} voltou só silêncio: "{trecho[:40]}…"')
        pedacos.append(pcm)
        pedacos.append(silencio(pausa))
        trechos.append({'texto': trecho, 'segundos': round(segundos_de(pcm), 3), 'pausa': pausa})
    if not trechos:
        raise RuntimeError('texto sem nada para narrar')
    pedacos.append(silencio(silencio_final))
    return b''.join(pedacos), trechos


def wav_de(pcm):
    """O PCM com cabeçalho WAV (16 bits, mono, TAXA): sem ffmpeg."""
    cabecalho = (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVE'
                 + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 1, TAXA, TAXA * 2, 2, 16)
                 + b'data' + struct.pack('<I', len(pcm)))
    return cabecalho + pcm


def gravar_m4a(pcm, destino, parametros_aac):
    """Codifica o PCM no AAC do projeto (PARAMETROS_AAC de narrar.py), via
    arquivo .parte: nunca fica um .m4a pela metade no lugar do final."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix('.parte.m4a')
    try:
        _ffmpeg(['-y', '-f', 's16le', '-ac', '1', '-ar', str(TAXA), '-i', '-',
                 *parametros_aac, str(parcial)], pcm)
        parcial.replace(destino)
    finally:
        if parcial.exists():
            parcial.unlink()
