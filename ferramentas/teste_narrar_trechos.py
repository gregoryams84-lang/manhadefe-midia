#!/usr/bin/env python3
"""Testes de narrar_trechos.py. Nenhum toca a rede nem a chave: tudo roda
no modo simulado (silêncio em vez de voz), com ffmpeg/ffprobe de verdade,
num diretório temporário com uma cópia do conteúdo do app.

  python -m pytest ferramentas/teste_narrar_trechos.py
  python ferramentas/teste_narrar_trechos.py          # sem pytest

Os testes leem o conteúdo real do app (manha-de-fe-app, pasta-irmã deste
repo ou MANHA_DE_FE_APP) e copiam para um temporário; nada é escrito nele.
O Terço (baixável desde 25/09) vai para um --midia temporário: nada é escrito
no terco/ deste repo. O teste do catálogo inteiro (~8 min) só roda com
NARRAR_TRECHOS_TESTE_LENTO=1.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narrar_trechos as nt  # noqa: E402
from narrar_trechos import Peca, Trecho  # noqa: E402

# O conteúdo real do app, SÓ leitura: os testes copiam para um temporário.
APP_REAL = nt.APP_PADRAO


def app_real():
    """O repo do app, ou uma falha que diz o que falta e como apontar — sem
    isto, num clone isolado, seis testes morreriam em FileNotFoundError."""
    faltando = [p for p in (APP_REAL / 'pubspec.yaml',
                            APP_REAL / 'assets' / 'content' / 'terco',
                            APP_REAL / 'assets' / 'content' / 'oracoes')
                if not p.exists()]
    if faltando:
        raise RuntimeError(
            f'o repo do app não está em {APP_REAL} (falta {faltando[0]}). Os testes leem '
            'assets/content/terco e assets/content/oracoes de manha-de-fe-app: clone-o como '
            'pasta-irmã de manhadefe-midia ou aponte a raiz dele em MANHA_DE_FE_APP.')
    return APP_REAL


class Pulado(Exception):
    """Teste pulado de propósito (o runner sem pytest o mostra como tal)."""


def pular(motivo):
    if 'pytest' in sys.modules:
        import pytest
        pytest.skip(motivo)
    raise Pulado(motivo)


def app_de_teste(tmp):
    app = Path(tmp) / 'app'
    for pasta in ('terco', 'oracoes'):
        shutil.copytree(app_real() / 'assets' / 'content' / pasta,
                        app / 'assets' / 'content' / pasta)
    (app / 'pubspec.yaml').write_text('name: teste', encoding='utf-8')
    return app


def midia_de_teste(tmp):
    """A raiz de mídia temporária: é onde o Terço é gravado nos testes."""
    return Path(tmp) / 'midia'


def args_comuns(tmp, app):
    """--simular e as três raízes temporárias que todo main() dos testes usa."""
    return ['--simular', '--app', str(app), '--midia', str(midia_de_teste(tmp)),
            '--trabalho', str(Path(tmp) / 'trabalho'), '--log', str(Path(tmp) / 'log.jsonl')]


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
        # O arquivo é as peças e os silêncios entre elas MAIS o silêncio de
        # saída — que fica depois da última marca e não mexe em nenhuma.
        assert abs(total - (previsto + nt.PAUSA_DE_SAIDA)) < 0.15, (total, previsto)
        assert total > previsto + nt.PAUSA_DE_SAIDA - 0.15
        lista = (trabalho / 'montagem' / trecho.id / 'lista.txt').read_text(encoding='utf-8').splitlines()
        assert lista[-1].endswith(f"{nt.PAUSA_DE_SAIDA:.3f}.wav'"), lista[-1]
        assert lista[-2].endswith(f"{wavs[-1].name}'"), lista[-2]
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
        comuns = args_comuns(tmp, app) + ['--ids', 'oracao-de-entrega']
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
        log = Path(tmp) / 'log.jsonl'
        comuns = args_comuns(tmp, app)
        # A abertura usa as mesmas duas peças da Ave-Maria que a oração.
        assert nt.main(comuns + ['--ids', 'ave-maria,gozosos-abertura']) == 0
        assert (midia_de_teste(tmp) / 'terco' / 'gozosos-abertura.m4a').exists()
        assert not (app / 'assets' / 'audio' / 'terco').exists(), 'o Terço não vai mais ao app'
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
        assert not (midia_de_teste(tmp) / 'terco' / 'gozosos-dezena-1.m4a').exists()


def teste_contagem_de_marcas_bate_com_o_que_a_tela_desenha():
    app = app_real()
    trechos = nt.catalogo(app)
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
            app / 'assets' / 'content' / 'oracoes' / 'indice.json')['comum'])
    assert all(t.tradicao == 'evangelico' for t in gemeas)
    for t in trechos:
        if not nt.eh_do_terco(t):
            slug = t.id[:-len(nt.SUFIXO_EVANGELICO)] if t.json is None else t.id
            assert t.contas == len(nt.passos_da_oracao(app, slug)), t.id
            assert t.arquivo == f'assets/audio/oracoes/{t.id}.m4a' and t.destino == app / t.arquivo
        else:
            # Baixável (25/09): a chave publicada e o arquivo em <midia>/terco/.
            assert t.arquivo == f'terco/{t.id}.m4a', t.id
            assert t.destino == nt.MIDIA_PADRAO / 'terco' / f'{t.id}.m4a', t.id
    assert sum(1 for t in trechos if nt.eh_do_terco(t)) == 28
    # --midia troca a raiz de TODO o Terço, e de nada mais.
    outra = nt.catalogo(app, Path('/outra/midia'))
    assert all(t.destino == Path('/outra/midia') / 'terco' / f'{t.id}.m4a'
               for t in outra if nt.eh_do_terco(t))
    assert [t.destino for t in outra if not nt.eh_do_terco(t)] == \
           [t.destino for t in trechos if not nt.eh_do_terco(t)]


def teste_composicao_do_terco_c13_jaculatoria_apos_cada_gloria_e_sinal_da_cruz_no_fecho():
    """C13 (25/09/2026): a jaculatória de Fátima depois de CADA Glória (abertura
    e cinco dezenas) e o Sinal da Cruz como última peça do fecho — as duas sem
    conta, então 5/11×5/0 não muda e os JSONs do app não mudam."""
    app = app_real()
    creio = len(nt.passos_da_oracao(app, 'creio'))
    pai_nosso = len(nt.passos_da_oracao(app, 'pai-nosso-catolico'))
    ave_maria = len(nt.passos_da_oracao(app, 'ave-maria'))
    salve_rainha = len(nt.passos_da_oracao(app, 'salve-rainha'))
    trechos = nt.catalogo(app)
    for misterio in nt.MISTERIOS:
        abertura = _por_id(trechos, f'{misterio}-abertura')
        fecho = _por_id(trechos, f'{misterio}-fecho')
        dezenas = [_por_id(trechos, f'{misterio}-dezena-{n}') for n in range(1, 6)]
        # Quantas peças cada trecho tem (antes da C13: uma a menos em cada).
        assert len(abertura.pecas) == 1 + creio + pai_nosso + 3 * ave_maria + 1 + 1, misterio
        for d in dezenas:
            assert len(d.pecas) == 2 + pai_nosso + 10 * ave_maria + 1 + 1, d.id
        assert len(fecho.pecas) == salve_rainha + 1 + 1, misterio
        # Glória → jaculatória, as duas sem conta, a jaculatória com a pausa
        # de entre contas antes dela (a mesma do Glória).
        for t in [abertura, *dezenas]:
            gloria, jaculatoria = t.pecas[-2], t.pecas[-1]
            assert (gloria.texto, gloria.conta) == (nt.GLORIA, False), t.id
            assert (jaculatoria.texto, jaculatoria.conta) == (nt.JACULATORIA_DE_FATIMA, False), t.id
            assert jaculatoria.pausa_antes == gloria.pausa_antes == nt.PAUSA_ENTRE_CONTAS, t.id
            assert sum(1 for p in t.pecas if p.texto == nt.JACULATORIA_DE_FATIMA) == 1, t.id
        # O fecho termina no Sinal da Cruz (a mesma constante da abertura),
        # sem conta, depois da oração final; nenhuma conta no fecho inteiro.
        assert fecho.pecas[-2].texto == nt.ORACAO_FINAL
        assert (fecho.pecas[-1].texto, fecho.pecas[-1].conta) == (nt.SINAL_DA_CRUZ, False)
        assert fecho.pecas[-1].pausa_antes == nt.PAUSA_ENTRE_CONTAS
        assert fecho.contas == 0 and abertura.contas == 5 and all(d.contas == 11 for d in dezenas)
        assert abertura.pecas[0].texto == nt.SINAL_DA_CRUZ and abertura.pecas[0].conta
    # Reaproveitando, o Sinal da Cruz do fecho e o da abertura são UMA peça.
    assert nt.chave_da_peca(fecho.pecas[-1], 'catolico', fecho.id, len(fecho.pecas), True) == \
           nt.chave_da_peca(abertura.pecas[0], 'catolico', abertura.id, 1, True)


def _indice(app):
    return app / 'assets' / 'content' / 'oracoes' / 'indice.json'


def _nova_oracao(app, slug):
    (app / 'assets' / 'content' / 'oracoes' / f'{slug}.json').write_text(json.dumps({
        'titulo': slug, 'passos': [{'texto': 'Um.'}, {'texto': 'Dois.'}],
        'audioAsset': f'assets/audio/oracoes/{slug}.m4a', 'marcas': [0, 5]}), encoding='utf-8')


def _por_id(trechos, id_):
    return next(t for t in trechos if t.id == id_)


def teste_oracao_nova_no_indice_entra_no_catalogo_com_a_voz_da_camada():
    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        indice = nt.ler_json(_indice(app))
        _nova_oracao(app, 'oracao-nova')
        for camada, esperados in (('catolico', ['oracao-nova']),
                                  ('evangelico', ['oracao-nova']),
                                  ('comum', ['oracao-nova', 'oracao-nova' + nt.SUFIXO_EVANGELICO])):
            dados = json.loads(json.dumps(indice))
            dados[camada].append('oracao-nova')
            _indice(app).write_text(json.dumps(dados), encoding='utf-8')
            trechos = nt.catalogo(app)
            assert len(trechos) == 41 + len(esperados), camada
            for id_ in esperados:
                t = _por_id(trechos, id_)
                assert t.contas == 2 and t.contas_esperadas == 2
                assert t.tradicao == ('evangelico' if camada == 'evangelico' or id_.endswith(nt.SUFIXO_EVANGELICO)
                                      else 'catolico'), (camada, id_)
                assert (t.json is None) == id_.endswith(nt.SUFIXO_EVANGELICO)


def teste_indice_que_nao_bate_com_a_pasta_para_a_ferramenta_em_vez_de_ignorar():
    def deve_parar(app, trecho_da_mensagem):
        try:
            nt.catalogo(app)
        except SystemExit as e:
            assert trecho_da_mensagem in str(e), str(e)
        else:
            raise AssertionError(f'deveria ter parado por {trecho_da_mensagem!r}')

    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        original = _indice(app).read_text(encoding='utf-8')
        indice = json.loads(original)
        # Citada no índice, sem arquivo.
        dados = json.loads(original)
        dados['catolico'].append('fantasma')
        _indice(app).write_text(json.dumps(dados), encoding='utf-8')
        deve_parar(app, 'fantasma')
        # Na pasta, fora do índice.
        _indice(app).write_text(original, encoding='utf-8')
        _nova_oracao(app, 'sobra')
        deve_parar(app, 'sobra')
        (app / 'assets' / 'content' / 'oracoes' / 'sobra.json').unlink()
        # Em duas camadas.
        dados = json.loads(original)
        dados['evangelico'].append(indice['catolico'][0])
        _indice(app).write_text(json.dumps(dados), encoding='utf-8')
        deve_parar(app, indice['catolico'][0])
        # Camada que o app não conhece.
        dados = json.loads(original)
        dados['ortodoxo'] = []
        _indice(app).write_text(json.dumps(dados), encoding='utf-8')
        deve_parar(app, 'ortodoxo')
        # Restaurado, volta a passar.
        _indice(app).write_text(original, encoding='utf-8')
        assert len(nt.catalogo(app)) == 41


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


def teste_gravar_marcas_recusa_arquivo_com_menos_marcas_que_o_esperado():
    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        terco = app / 'assets' / 'content' / 'terco' / 'gozosos.json'
        oracao = app / 'assets' / 'content' / 'oracoes' / 'ave-maria.json'
        # Um trecho do terço sem a chave (6 "marcas" para 7 trechos) e uma
        # oração sem nenhuma: nada é gravado, e o arquivo fica como estava.
        for caminho, posicao, quebra in ((terco, 6, ('"marcas": []', '"marcas_": []')),
                                         (oracao, None, ('"marcas"', '"marcas_"'))):
            texto = caminho.read_text(encoding='utf-8')
            assert quebra[0] in texto
            quebrado = texto.replace(quebra[0], quebra[1], 1)
            caminho.write_text(quebrado, encoding='utf-8')
            try:
                nt.gravar_marcas(trecho_de_teste(tmp, [], contas=1, json_=caminho, posicao=posicao), [0])
            except ValueError as e:
                assert 'marcas' in str(e)
            else:
                raise AssertionError('deveria ter recusado')
            assert caminho.read_text(encoding='utf-8') == quebrado
        try:
            nt.substituir_marcas('{"marcas": [1]}', 1, [2])
        except ValueError:
            pass
        else:
            raise AssertionError('deveria ter recusado a 2ª ocorrência')


def teste_gravar_marcas_no_fecho_vazio_e_de_volta_ao_vazio():
    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        terco = app / 'assets' / 'content' / 'terco' / 'gozosos.json'
        original = terco.read_text(encoding='utf-8')
        assert json.loads(original)['trechos'][6]['marcas'] == []
        fecho = trecho_de_teste(tmp, [], contas=0, json_=terco, posicao=6)
        # [] sobre []: byte a byte igual.
        nt.gravar_marcas(fecho, [])
        assert terco.read_text(encoding='utf-8') == original
        # Valores no fecho, e só nele.
        nt.gravar_marcas(fecho, [1.5, 3])
        dados = json.loads(terco.read_text(encoding='utf-8'))
        assert dados['trechos'][6]['marcas'] == [1.5, 3]
        assert [t['marcas'] for t in dados['trechos'][:6]] == \
               [t['marcas'] for t in json.loads(original)['trechos'][:6]]
        assert '"marcas": [1.5, 3] }' in terco.read_text(encoding='utf-8')
        # E de volta ao vazio: o arquivo original, byte a byte.
        nt.gravar_marcas(fecho, [])
        assert terco.read_text(encoding='utf-8') == original


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
        assert nt.main(args_comuns(tmp, app) + ['--ids', 'gozosos-abertura']) == 0
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
        assert nt.main(args_comuns(tmp, app)
                       + ['--ids', 'gozosos-dezena-1,ave-maria,salmo-23-evangelico']) == 0
        # O Terço vai para <midia>/terco/ (baixável); as orações, para o app.
        assert (midia_de_teste(tmp) / 'terco' / 'gozosos-dezena-1.m4a').exists()
        assert not (app / 'assets' / 'audio' / 'terco').exists()
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
        # O log guarda a chave publicada / o asset — nunca o caminho do disco.
        assert [r['arquivo'] for r in registros] == [
            'terco/gozosos-dezena-1.m4a', 'assets/audio/oracoes/ave-maria.m4a',
            'assets/audio/oracoes/salmo-23-evangelico.m4a']
        assert len(registros[2]['marcas']) == 6
        # A Ave-Maria da dezena e a da oração são a mesma peça: uma geração só.
        pecas = list((trabalho / 'pecas' / 'catolico').glob('*.wav'))
        # anúncio, meditação, pai-nosso ×4, ave-maria ×2, glória, jaculatória (C13)
        assert len(pecas) == 2 + 4 + 2 + 1 + 1


def teste_lento_catalogo_inteiro_montado_pelo_ffmpeg_real():
    """Os 41 arquivos, de verdade (simulados), do começo ao fim: ~8 min."""
    if os.environ.get('NARRAR_TRECHOS_TESTE_LENTO') != '1':
        pular('~8 min: rode com NARRAR_TRECHOS_TESTE_LENTO=1')
    with tempfile.TemporaryDirectory() as tmp:
        app = app_de_teste(tmp)
        log = Path(tmp) / 'log.jsonl'
        inicio = time.time()
        assert nt.main(args_comuns(tmp, app)) == 0
        minutos = (time.time() - inicio) / 60
        trechos = nt.catalogo(app, midia_de_teste(tmp))
        # Os 28 do Terço em <midia>/terco/, e só eles; nada de Terço no app.
        assert sorted(p.name for p in (midia_de_teste(tmp) / 'terco').glob('*.m4a')) == \
               sorted(f'{t.id}.m4a' for t in trechos if nt.eh_do_terco(t))
        assert not (app / 'assets' / 'audio' / 'terco').exists()
        registros = {json.loads(l)['id']: json.loads(l)
                     for l in log.read_text(encoding='utf-8').splitlines()}
        assert len(trechos) == len(registros) == 41
        for t in trechos:
            r = registros[t.id]
            assert t.destino.exists() and t.destino.stat().st_size > 0, t.id
            assert r['simulado'] and abs(r['segundos']) > 0
            assert len(r['marcas']) == t.contas_esperadas, (t.id, r['marcas'])
            assert all(b > a for a, b in zip(r['marcas'], r['marcas'][1:])), (t.id, r['marcas'])
            if t.json is None:
                continue
            dados = nt.ler_json(t.json)
            gravadas = dados['marcas'] if t.posicao is None else dados['trechos'][t.posicao]['marcas']
            assert gravadas == r['marcas'], t.id
        for misterio in nt.MISTERIOS:
            dados = nt.ler_json(app / 'assets' / 'content' / 'terco' / f'{misterio}.json')
            assert [len(t['marcas']) for t in dados['trechos']] == [5, 11, 11, 11, 11, 11, 0]
        print(f'catálogo inteiro simulado em {minutos:.1f} min')


# ---------------------------------------------------------------------------

def main():
    """Roda tudo sem pytest."""
    testes = [(nome, obj) for nome, obj in sorted(globals().items())
              if nome.startswith('teste_') and callable(obj)]
    falhas = pulados = 0
    for nome, teste in testes:
        try:
            teste()
            print(f'ok    {nome}')
        except Pulado as e:
            pulados += 1
            print(f'pulou {nome}: {e}')
        except Exception:  # noqa: BLE001
            falhas += 1
            print(f'FALHA {nome}')
            traceback.print_exc()
    print(f'{chr(10)}{len(testes) - falhas - pulados} ok, {falhas} falha(s), {pulados} pulado(s)')
    return 1 if falhas else 0


if __name__ == '__main__':
    sys.exit(main())
