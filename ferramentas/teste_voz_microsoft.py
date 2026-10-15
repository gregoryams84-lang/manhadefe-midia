#!/usr/bin/env python3
"""Testes do motor da Microsoft (voz_microsoft.py), do agrupamento por voz e
texto em narrar.py e dos dois ouvidos do conferir_stt.py. Nenhum toca a
rede: a voz é trocada por um sinal gerado aqui; ffmpeg/ffprobe são reais.

  python -m pytest ferramentas/teste_voz_microsoft.py
  python ferramentas/teste_voz_microsoft.py          # sem pytest
"""
import math
import struct
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conferir_stt  # noqa: E402
import narrar  # noqa: E402
import voz_microsoft as vm  # noqa: E402

TAXA = vm.TAXA


def tom(segundos, antes=0.0, depois=0.0, amplitude=8000):
    """Um tom de 440 Hz com silêncio de `antes` e `depois` nas pontas."""
    fala = [int(amplitude * math.sin(2 * math.pi * 440 * i / TAXA))
            for i in range(int(segundos * TAXA))]
    return (bytes(int(antes * TAXA) * 2) + struct.pack(f'<{len(fala)}h', *fala)
            + bytes(int(depois * TAXA) * 2))


def teste_segmentar_corta_nas_tags_e_guarda_a_pausa_de_cada_trecho():
    texto = ('O Senhor é o meu pastor. <break time="1.2s" /> Salmo, capítulo 23, versículo 1. '
             '<break time="1.4s" /> Oração. <break time="0.8s" /> Guie os meus passos '
             '<break time="0.6s" /> Amém.')
    assert vm.segmentar(texto) == [
        ('O Senhor é o meu pastor.', 1.2), ('Salmo, capítulo 23, versículo 1.', 1.4),
        ('Oração.', 0.8), ('Guie os meus passos', 0.6), ('Amém.', 0.0)]


def teste_segmentar_tags_seguidas_somam_e_tag_inicial_e_ignorada():
    assert vm.segmentar('<break time="1.0s" /> A <break time="0.5s" /><break time="0.5s" /> B') == [
        ('A', 1.0), ('B', 0.0)]
    assert vm.segmentar('Só texto, sem tag') == [('Só texto, sem tag', 0.0)]
    assert vm.segmentar('   ') == []


def teste_texto_sem_tags():
    assert vm.texto_sem_tags('A <break time="1.2s" /> B  C') == 'A B C'


def teste_aparar_deixa_so_as_margens_em_volta_da_fala():
    pcm = tom(1.0, antes=0.5, depois=1.0)
    aparado = vm.aparar(pcm)
    esperado = 1.0 + vm.MARGEM_ANTES + vm.MARGEM_DEPOIS
    assert abs(vm.segundos_de(aparado) - esperado) < 0.01, vm.segundos_de(aparado)
    # Borda menor que a margem: fica o que há, nunca passa do começo.
    curto = tom(0.5, antes=0.02, depois=0.05)
    assert abs(vm.segundos_de(vm.aparar(curto)) - 0.57) < 0.01
    assert vm.aparar(bytes(TAXA * 2)) == b''


def teste_narrar_monta_trechos_aparados_com_pausas_exatas_e_silencio_final():
    pedidos = []

    def falsa(texto, voz, velocidade):
        pedidos.append((texto, voz, velocidade))
        return tom(1.0, antes=0.3, depois=0.9)  # bordas como as da Microsoft

    texto = 'A <break time="1.2s" /> B <break time="0.8s" /> C'
    pcm, trechos = vm.narrar(texto, 'catolico', sintetizar=falsa)
    assert [p[0] for p in pedidos] == ['A', 'B', 'C']
    assert {p[1] for p in pedidos} == {vm.VOZES['catolico']}
    assert {p[2] for p in pedidos} == {vm.VELOCIDADE}
    fala = 1.0 + vm.MARGEM_ANTES + vm.MARGEM_DEPOIS
    esperado = 3 * fala + 1.2 + 0.8 + vm.SILENCIO_FINAL
    assert abs(vm.segundos_de(pcm) - esperado) < 0.01, vm.segundos_de(pcm)
    assert [t['pausa'] for t in trechos] == [1.2, 0.8, 0.0]
    assert all(abs(t['segundos'] - fala) < 0.01 for t in trechos)


def teste_narrar_recusa_trecho_que_voltou_so_silencio():
    try:
        vm.narrar('A <break time="1.0s" /> B', 'evangelico',
                  sintetizar=lambda *_: bytes(TAXA))
    except RuntimeError as e:
        assert 'só silêncio' in str(e)
    else:
        raise AssertionError('aceitou silêncio no lugar da voz')


def teste_incompleto_pega_a_resposta_cortada_pela_ultima_palavra_ou_pela_duracao():
    texto = 'Tomaram um certo Simão, cireneu, e puseram-lhe a cruz às costas.'
    inteiro = [('Tomaram', 0.5), ('um', 0.7), ('certo', 1.1), ('Simão', 1.6), ('cireneu', 2.3),
               ('e', 2.4), ('puseram-lhe', 3.1), ('a', 3.2), ('cruz', 3.6), ('às', 3.8), ('costas', 4.3)]
    assert vm.incompleto(texto, inteiro, 4.5) is None
    assert vm.incompleto(texto, inteiro, 4.1) is None  # a folga do fim
    assert 'parou em "cruz"' in vm.incompleto(texto, inteiro[:-2], 4.5)
    assert 'tem 2.00 s' in vm.incompleto(texto, inteiro, 2.0)
    assert 'sem limites' in vm.incompleto(texto, [], 4.5)
    assert vm.incompleto('Amém.', [('Amém', 0.6)], 1.0) is None
    assert vm.incompleto('   ', [], 0.0) is None


def teste_wav_e_m4a_gravados_tem_a_duracao_do_pcm():
    pcm = tom(2.0)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / 'a.wav'
        wav.write_bytes(vm.wav_de(pcm))
        assert abs(narrar.duracao_segundos(wav) - 2.0) < 0.01
        m4a = Path(tmp) / 'sub' / 'a.m4a'
        vm.gravar_m4a(pcm, m4a, narrar.PARAMETROS_AAC)
        assert m4a.exists() and not m4a.with_suffix('.parte.m4a').exists()
        assert abs(narrar.duracao_segundos(m4a) - 2.0) < 0.15  # priming do AAC


def teste_agrupar_junta_o_mesmo_texto_na_mesma_voz_so_no_motor_microsoft():
    itens = [{'id': 'x', 'tradicao': 'catolico', 'caminho': 'narracao/catolico/x.m4a', 'texto': 'T'},
             {'id': 'x', 'tradicao': 'evangelico', 'caminho': 'narracao/evangelico/x.m4a', 'texto': 'T'},
             {'id': 'y', 'tradicao': 'catolico', 'caminho': 'narracao/catolico/y.m4a', 'texto': 'U'}]
    assert [len(g) for g in narrar.agrupar(itens, 'microsoft')] == [2, 1]
    assert [len(g) for g in narrar.agrupar(itens, 'elevenlabs')] == [1, 1, 1]


def teste_fazer_grupo_gera_uma_vez_e_copia_para_os_outros_caminhos():
    itens = [{'id': 'x', 'tradicao': 'catolico', 'caminho': 'narracao/catolico/x.m4a', 'texto': 'T'},
             {'id': 'x', 'tradicao': 'evangelico', 'caminho': 'narracao/evangelico/x.m4a', 'texto': 'T'}]
    # `registrar` tem o LOG real como argumento padrão (ligado na definição):
    # trocar narrar.LOG não bastaria, e a linha falsa iria para o log de
    # verdade. Aqui o registro é recolhido numa lista.
    raiz_antes, registrar_antes = narrar.RAIZ, narrar.registrar
    registrados = []
    with tempfile.TemporaryDirectory() as tmp:
        narrar.RAIZ, narrar.registrar = Path(tmp), lambda r, arquivo=None: registrados.append(r)
        try:
            chamadas = []

            def falsa(chave, item, normalizacao, motor):
                chamadas.append(item['caminho'])
                destino = narrar.RAIZ / item['caminho']
                destino.parent.mkdir(parents=True)
                destino.write_bytes(b'audio')
                return dict(narrar._registro_de(item, motor), ok=True, segundos=1.0, bytes=5)

            original = narrar.fazer
            narrar.fazer = falsa
            try:
                registros = narrar.fazer_grupo(None, itens, 'auto', 'microsoft')
            finally:
                narrar.fazer = original
            assert chamadas == ['narracao/catolico/x.m4a']
            assert (Path(tmp) / 'narracao/evangelico/x.m4a').read_bytes() == b'audio'
            assert registros[1]['copiado_de'] == 'narracao/catolico/x.m4a'
            assert [r['caminho'] for r in registrados] == ['narracao/evangelico/x.m4a']
        finally:
            narrar.RAIZ, narrar.registrar = raiz_antes, registrar_antes


def teste_cruzar_confirma_so_o_que_os_dois_ouvidos_erraram_no_mesmo_lugar():
    rapido = [{'op': 'replace', 'esperado': 'acalme', 'ouvido': 'acalma'},
              {'op': 'delete', 'esperado': 'hoje', 'ouvido': ''}]
    fino = [{'op': 'replace', 'esperado': 'acalme', 'ouvido': 'acalmo'},
            {'op': 'insert', 'esperado': '', 'ouvido': 'amor'}]
    confirmadas, duvidas = conferir_stt.cruzar(rapido, fino)
    assert [c['esperado'] for c in confirmadas] == ['acalme']
    assert sorted(d.get('esperado') or d['ouvido'] for d in duvidas) == ['amor', 'hoje']
    assert conferir_stt.cruzar([], fino) == ([], fino)


def teste_comparar_tolera_capitulo_engolido_antes_do_numero_e_so_isso():
    esperado = 'Salmo, capítulo 23, versículo 1. O Senhor é o meu pastor.'
    _, duras, leves = conferir_stt.comparar(esperado, 'Salmo 23, versículo 1. O Senhor é o meu pastor.')
    assert duras == [] and [l['tipo'] for l in leves] == ['referencia']
    _, duras, _ = conferir_stt.comparar(esperado, 'Salmo, capítulo 23, versículo 1. O Senhor é o meu.')
    assert [d['esperado'] for d in duras] == ['pastor']


def teste_comparar_tolera_o_que_soa_igual_e_as_palavras_curtas_mas_nao_o_trecho_que_faltou():
    casos_leves = [
        ('Guia os meus passos e acalma o meu coração.', 'Guie os meus passos e acalme o meu coração.', 'som'),
        ('Há um buraco que todos já aprenderam a desviar.', 'A um buraco que todos já aprenderam a desviar.', 'som'),
        ('onde fora posto', 'onde for aposto', 'som'),
        ('De onde me provém isto a mim', 'De onde me provei isto a mim', 'som'),
        ('Põe um pouco de fé', 'Ponha o pouco de fé', 'curta'),
        ('venha visitar-me a mãe do meu Senhor', 'venha visitar minha mãe do meu Senhor', 'som'),
        ('a casa de Nazaré', 'a casa Nazaré', 'curta'),
        ('bendita sois vós entre as mulheres', 'bendita suas voz entre as mulheres', 'som'),
        ('a Moisés face a face, como', 'a Moisés fez se a face, como', 'som'),
        ('foge, cala-te, fica em paz.', 'foge, cala-te, fique em paz.', 'som'),
    ]
    for esperado, ouvido, tipo in casos_leves:
        _, duras, leves = conferir_stt.comparar(esperado, ouvido)
        assert duras == [], (esperado, duras)
        # `tipo` documenta a tolerância que pegou no piloto; o normalizador
        # pode mudar a palavra ("um" vira "1" depois de "a") e outra pegar.
        assert {l['tipo'] for l in leves} & {tipo, 'som', 'curta'}, (esperado, leves)
    # O erro grande continua reprovando: a frase que faltou, o nome trocado.
    esperado = 'O Senhor é o meu pastor, nada me faltará. Você acorda hoje com a lista do que falta.'
    _, duras, _ = conferir_stt.comparar(esperado, 'O Senhor é o meu pastor, nada me faltará.')
    assert len(duras) == 1 and duras[0]['op'] == 'delete'
    _, duras, _ = conferir_stt.comparar('Santa Rita de Cássia rezava.', 'Santa Clara de Assis rezava.')
    assert duras, 'nome trocado tem de reprovar'


def teste_aceitos_a_mao_exige_caminho_e_motivo():
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / 'aceitos.txt'
        arq.write_text(chr(10).join(['# comentário', '', 'narracao/catolico/x.m4a | o ouvido troca a palavra', '']),
                       encoding='utf-8')
        assert conferir_stt.aceitos_a_mao(arq) == {'narracao/catolico/x.m4a': 'o ouvido troca a palavra'}
        assert conferir_stt.aceitos_a_mao(Path(tmp) / 'nao-existe.txt') == {}
        arq.write_text('narracao/catolico/x.m4a |   ' + chr(10), encoding='utf-8')
        try:
            conferir_stt.aceitos_a_mao(arq)
        except SystemExit as e:
            assert 'motivo' in str(e)
        else:
            raise AssertionError('aceitou um aceite sem motivo')


def main():
    """Roda tudo sem pytest."""
    testes = [(n, o) for n, o in sorted(globals().items()) if n.startswith('teste_') and callable(o)]
    falhas = 0
    for nome, teste in testes:
        try:
            teste()
            print(f'ok    {nome}')
        except Exception:  # noqa: BLE001
            falhas += 1
            print(f'FALHA {nome}')
            traceback.print_exc()
    print(f'{chr(10)}{len(testes) - falhas} ok, {falhas} falha(s)')
    return 1 if falhas else 0


if __name__ == '__main__':
    sys.exit(main())
