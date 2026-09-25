#!/usr/bin/env python3
"""Testes de narrar_trechos.py. Nenhum toca a rede nem a chave: tudo roda
no modo simulado (silêncio em vez de voz), com ffmpeg/ffprobe de verdade,
num diretório temporário com uma cópia do conteúdo do app.

  python -m pytest ferramentas/teste_narrar_trechos.py
  python ferramentas/teste_narrar_trechos.py          # sem pytest
"""
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narrar_trechos as nt  # noqa: E402
from narrar_trechos import Peca, Trecho  # noqa: E402

# O conteúdo real do app, SÓ leitura: os testes copiam para um temporário.
APP_REAL = nt.APP_PADRAO


def app_de_teste(tmp):
    app = Path(tmp) / 'app'
    for pasta in ('terco', 'oracoes'):
        shutil.copytree(APP_REAL / 'assets' / 'content' / pasta,
                        app / 'assets' / 'content' / pasta)
    (app / 'pubspec.yaml').write_text('name: teste', encoding='utf-8')
    return app


def trecho_de_teste(tmp, pecas, contas=None, json_=None, posicao=None):
    return Trecho(id='teste', destino=Path(tmp) / 'saida' / 'teste.m4a',
                  tradicao='catolico', pecas=tuple(pecas),
                  contas_esperadas=sum(1 for p in pecas if p.conta) if contas is None else contas,
                  json=json_, posicao=posicao)


def pecas_de_exemplo():
    return [Peca('a', True, 0.0, 'a'), Peca('b', False, 0.8, 'b'),
            Peca('c', True, 1.4, 'c'), Peca('d', True, 2.0, 'd')]


# ---------------------------------------------------------------------------

def teste_marca_e_a_soma_exata_das_duracoes_e_silencios_anteriores():
    duracoes = [1.5, 2.25, 0.5, 3.0]
    marcas, total = nt.calcular_marcas(pecas_de_exemplo(), duracoes)
    assert marcas == [0, round(1.5 + 0.8 + 2.25 + 1.4, 2),
                      round(1.5 + 0.8 + 2.25 + 1.4 + 0.5 + 2.0, 2)]
    assert total == round(sum(duracoes) + 0.8 + 1.4 + 2.0, 3)


def teste_montagem_real_mede_com_ffprobe_e_a_marca_bate():
    with tempfile.TemporaryDirectory() as tmp:
        trabalho = Path(tmp) / 'trabalho'
        duracoes = [1.5, 2.25, 0.5, 3.0]
        wavs = [nt.silencio_wav(trabalho / 'pecas' / f'{n}.wav', d)
                for n, d in enumerate(duracoes)]
        trecho = trecho_de_teste(tmp, pecas_de_exemplo())
        marcas, total = nt.montar(trecho, wavs, trabalho)
        esperadas, previsto = nt.calcular_marcas(trecho.pecas, duracoes)
        assert marcas == esperadas, (marcas, esperadas)
        assert abs(total - previsto) < 0.15, (total, previsto)
        assert trecho.destino.exists() and trecho.destino.stat().st_size > 0


def teste_um_passo_refeito_recalcula_as_marcas_do_trecho_inteiro():
    with tempfile.TemporaryDirectory() as tmp:
        trabalho = Path(tmp) / 'trabalho'
        wavs = [nt.silencio_wav(trabalho / 'pecas' / f'{n}.wav', d)
                for n, d in enumerate([1.5, 2.25, 0.5, 3.0])]
        trecho = trecho_de_teste(tmp, pecas_de_exemplo())
        antes, _ = nt.montar(trecho, wavs, trabalho)
        # A peça 2 (sem conta) fica 2 s mais longa: a marca da peça 3 e a da
        # peça 4 andam 2 s; a da peça 1 não muda.
        nt.silencio_wav(wavs[1], 4.25)
        depois, _ = nt.montar(trecho, wavs, trabalho)
        assert depois[0] == antes[0]
        assert depois[1] == round(antes[1] + 2.0, 2)
        assert depois[2] == round(antes[2] + 2.0, 2)


def teste_refazer_um_passo_pela_linha_de_comando_recalcula_o_trecho():
    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        trabalho, log = Path(tmp) / 'trabalho', Path(tmp) / 'log.jsonl'
        comuns = ['--simular', '--app', str(app), '--trabalho', str(trabalho),
                  '--log', str(log), '--ids', 'oracao-de-entrega']
        assert nt.main(comuns) == 0
        antes = nt.ler_json(app / 'assets' / 'content' / 'oracoes' / 'oracao-de-entrega.json')['marcas']
        ritmo = nt.CARACTERES_POR_SEGUNDO
        try:
            nt.CARACTERES_POR_SEGUNDO = ritmo / 2  # a peça refeita sai 2× mais longa
            assert nt.main(comuns + ['--refazer', '--passos', '2']) == 0
        finally:
            nt.CARACTERES_POR_SEGUNDO = ritmo
        depois = nt.ler_json(app / 'assets' / 'content' / 'oracoes' / 'oracao-de-entrega.json')['marcas']
        assert len(antes) == len(depois) == 3
        assert depois[0] == antes[0] == 0
        assert depois[1] == antes[1]          # a peça 2 começa no mesmo lugar
        assert depois[2] > antes[2]           # a peça 3 começa depois


def teste_peca_refeita_reconstroi_todo_trecho_ja_montado_que_a_usa():
    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        trabalho, log = Path(tmp) / 'trabalho', Path(tmp) / 'log.jsonl'
        comuns = ['--simular', '--app', str(app), '--trabalho', str(trabalho), '--log', str(log)]
        # A abertura usa as mesmas duas peças da Ave-Maria que a oração.
        assert nt.main(comuns + ['--ids', 'ave-maria,gozosos-abertura']) == 0
        gozosos = app / 'assets' / 'content' / 'terco' / 'gozosos.json'
        abertura_antes = nt.ler_json(gozosos)['trechos'][0]['marcas']
        ritmo = nt.CARACTERES_POR_SEGUNDO
        try:
            nt.CARACTERES_POR_SEGUNDO = ritmo / 2
            assert nt.main(comuns + ['--ids', 'ave-maria', '--refazer', '--passos', '1']) == 0
        finally:
            nt.CARACTERES_POR_SEGUNDO = ritmo
        abertura_depois = nt.ler_json(gozosos)['trechos'][0]['marcas']
        # Crucifixo, Pai-Nosso e 1ª Ave-Maria começam onde começavam; a 2ª e a
        # 3ª Ave-Maria andam, porque a primeira metade ficou mais longa.
        assert abertura_depois[:3] == abertura_antes[:3]
        assert abertura_depois[3] > abertura_antes[3] and abertura_depois[4] > abertura_antes[4]
        # Duas rodadas, as duas montaram os dois (a ordem dentro da rodada é a
        # do catálogo, e a propagação vem depois dos escolhidos).
        ids = [json.loads(l)['id'] for l in log.read_text(encoding='utf-8').splitlines()]
        assert sorted(ids[:2]) == sorted(ids[2:]) == ['ave-maria', 'gozosos-abertura'], ids
        # A dezena-1 também usa a peça, mas nunca foi montada: não é puxada.
        assert not (app / 'assets' / 'audio' / 'terco' / 'gozosos-dezena-1.m4a').exists()


def teste_contagem_de_marcas_bate_com_o_que_a_tela_desenha():
    trechos = nt.catalogo(APP_REAL)
    assert len(trechos) == 4 * 7 + 9 + 4
    for t in trechos:
        assert t.contas == t.contas_esperadas, t.id
    for misterio in nt.MISTERIOS:
        do_terco = [t for t in trechos if t.id.startswith(misterio + '-')]
        assert [t.contas for t in do_terco] == [5, 11, 11, 11, 11, 11, 0], misterio
        assert sum(t.contas for t in do_terco) == 60  # ContasDoTerco.total
    # As cópias gêmeas (sem JSON para gravar) são as 4 comuns na voz
    # evangélica; pai-nosso-evangelico também termina em "-evangelico", mas
    # é oração própria, com JSON.
    gemeas = [t for t in trechos if t.json is None]
    assert sorted(t.id for t in gemeas) == sorted(
        slug + nt.SUFIXO_EVANGELICO for slug in nt.ler_json(
            APP_REAL / 'assets' / 'content' / 'oracoes' / 'indice.json')['comum'])
    assert all(t.tradicao == 'evangelico' for t in gemeas)
    for t in trechos:
        if 'oracoes' in t.destino.parts:
            slug = t.id[:-len(nt.SUFIXO_EVANGELICO)] if t.json is None else t.id
            assert t.contas == len(nt.passos_da_oracao(APP_REAL, slug)), t.id


def _chaves(obj):
    """A ordem das chaves, recursiva, para comparar dois JSONs."""
    if isinstance(obj, dict):
        return [(k, _chaves(v)) for k, v in obj.items()]
    if isinstance(obj, list):
        return [_chaves(v) for v in obj]
    return None


def teste_json_gravado_mantem_ordem_das_chaves_e_todos_os_campos():
    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        terco = app / 'assets' / 'content' / 'terco' / 'gozosos.json'
        oracao = app / 'assets' / 'content' / 'oracoes' / 'ave-maria.json'
        for caminho, posicao, novas in ((terco, 3, [7.5, 20, 33.25, 46, 58.9, 71, 84, 97, 110, 123, 136]),
                                        (oracao, None, [0, 9.75])):
            texto_antes = caminho.read_text(encoding='utf-8')
            antes = json.loads(texto_antes)
            nt.gravar_marcas(trecho_de_teste(tmp, [], contas=len(novas), json_=caminho,
                                             posicao=posicao), novas)
            texto_depois = caminho.read_text(encoding='utf-8')
            depois = json.loads(texto_depois)
            assert _chaves(antes) == _chaves(depois)
            if posicao is None:
                assert depois['marcas'] == novas
                depois['marcas'] = antes['marcas']
            else:
                assert depois['trechos'][posicao]['marcas'] == novas
                assert [t['marcas'] for i, t in enumerate(depois['trechos']) if i != posicao] == \
                       [t['marcas'] for i, t in enumerate(antes['trechos']) if i != posicao]
                depois['trechos'][posicao]['marcas'] = antes['trechos'][posicao]['marcas']
            assert depois == antes
            # Byte a byte, só a linha das marcas mudou.
            diff = [(a, b) for a, b in zip(texto_antes.splitlines(), texto_depois.splitlines()) if a != b]
            assert len(diff) == 1 and '"marcas"' in diff[0][0], diff
            assert texto_antes.count(chr(10)) == texto_depois.count(chr(10))


def teste_formatacao_das_marcas_no_json():
    assert nt.formatar_marcas([0, 7.5, 20.0, 33.25]) == '[0, 7.5, 20, 33.25]'
    assert nt.formatar_marcas([]) == '[]'


def teste_marcas_em_ordem_crescente():
    nt.conferir_crescentes([0, 5, 9.5], 'ok')
    for ruins in ([0, 5, 5], [0, 9, 5]):
        try:
            nt.conferir_crescentes(ruins, 'ruim')
        except ValueError:
            pass
        else:
            raise AssertionError(f'{ruins} deveria falhar')
    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        assert nt.main(['--simular', '--app', str(app), '--trabalho', str(Path(tmp) / 'w'),
                        '--log', str(Path(tmp) / 'log.jsonl'), '--ids', 'gozosos-abertura']) == 0
        marcas = nt.ler_json(app / 'assets' / 'content' / 'terco' / 'gozosos.json')['trechos'][0]['marcas']
        assert len(marcas) == 5 and marcas[0] == 0
        assert all(b > a for a, b in zip(marcas, marcas[1:])), marcas


def teste_reaproveitamento_identifica_a_peca_pela_voz_e_pelo_texto():
    ave = Peca('Ave Maria', True, 1.4, 'ave')
    k1 = nt.chave_da_peca(ave, 'catolico', 'gozosos-dezena-1', 7, True)
    k2 = nt.chave_da_peca(ave, 'catolico', 'dolorosos-dezena-5', 25, True)
    assert k1 == k2
    assert nt.chave_da_peca(ave, 'evangelico', 'gozosos-dezena-1', 7, True) != k1
    assert nt.chave_da_peca(ave, 'catolico', 'gozosos-dezena-1', 7, False) != \
           nt.chave_da_peca(ave, 'catolico', 'dolorosos-dezena-5', 25, False)


def teste_simulacao_ponta_a_ponta_grava_arquivos_marcas_e_log():
    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        trabalho, log = Path(tmp) / 'trabalho', Path(tmp) / 'log.jsonl'
        salmo = app / 'assets' / 'content' / 'oracoes' / 'salmo-23.json'
        salmo_antes = nt.ler_json(salmo)['marcas']
        assert nt.main(['--simular', '--app', str(app), '--trabalho', str(trabalho),
                        '--log', str(log), '--ids', 'gozosos-dezena-1,ave-maria,salmo-23-evangelico']) == 0
        assert (app / 'assets' / 'audio' / 'terco' / 'gozosos-dezena-1.m4a').exists()
        assert (app / 'assets' / 'audio' / 'oracoes' / 'ave-maria.m4a').exists()
        assert (app / 'assets' / 'audio' / 'oracoes' / 'salmo-23-evangelico.m4a').exists()
        dezena = nt.ler_json(app / 'assets' / 'content' / 'terco' / 'gozosos.json')['trechos'][1]['marcas']
        assert len(dezena) == 11
        assert dezena[0] > 0, 'a conta do Pai-Nosso acende depois do anúncio, não no zero'
        ave = nt.ler_json(app / 'assets' / 'content' / 'oracoes' / 'ave-maria.json')['marcas']
        assert len(ave) == 2 and ave[0] == 0 and ave[1] > 0
        # O salmo evangélico não tem JSON para gravar: só o log.
        assert nt.ler_json(salmo)['marcas'] == salmo_antes
        registros = [json.loads(l) for l in log.read_text(encoding='utf-8').splitlines()]
        assert [r['id'] for r in registros] == ['gozosos-dezena-1', 'ave-maria', 'salmo-23-evangelico']
        assert all(r['simulado'] for r in registros)
        assert [r['gravou_json'] for r in registros] == [True, True, False]
        assert len(registros[2]['marcas']) == 6
        # A Ave-Maria da dezena e a da oração são a mesma peça: uma geração só.
        pecas = list((trabalho / 'pecas' / 'catolico').glob('*.wav'))
        assert len(pecas) == 2 + 4 + 2 + 1  # anúncio, meditação, pai-nosso ×4, ave-maria ×2, glória


# ---------------------------------------------------------------------------

def main():
    """Roda tudo sem pytest."""
    testes = [(nome, obj) for nome, obj in sorted(globals().items())
              if nome.startswith('teste_') and callable(obj)]
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
