#!/usr/bin/env python3
"""Confere ferramentas/imagens/cenas.json contra os cartões do app Manhã de Fé.

Uso:
    python conferir_cenas.py [--app CAMINHO_DO_REPO_DO_APP] [--motivos]

Verifica:
  1. cobertura exata: as chaves são os ids de baralhos.json + dias/*.json (392), na ordem
     comum, quaresma, pascoa, advento, natal e depois os dias em ordem alfabética;
  2. cada frase tem 12 a 40 palavras, começa por "Um "/"Uma ", termina em ponto,
     é uma linha só e cita alguma luz;
  3. nenhuma palavra proibida (pessoas, corpo, texto, símbolos de uma tradição,
     termos do bloco fixo de estilo);
  4. motivo principal (primeiro substantivo da frase, normalizado) não se repete em
     ids consecutivos do mesmo baralho e nenhum motivo passa de 15% do total;
  5. pomba/chama (pomba, chama, vela, fogueira, brasas) em no máximo 10% das cenas.

Sai com código 1 se houver erro. Avisos não derrubam.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, OrderedDict
from pathlib import Path

AQUI = Path(__file__).resolve().parent
APP_PADRAO = AQUI.parent.parent.parent / "manha-de-fe-app"
BARALHOS = ["comum", "quaresma", "pascoa", "advento", "natal"]

MIN_PALAVRAS, MAX_PALAVRAS = 12, 40
TETO_MOTIVO = 0.15
TETO_POMBA_CHAMA = 0.10

# Palavras proibidas (comparação sem acento, palavra inteira). Plurais listados.
PROIBIDAS = {
    # pessoas e partes do corpo
    "pessoa", "pessoas", "rosto", "rostos", "mao", "maos", "silhueta", "silhuetas",
    "figura", "figuras", "alguem", "ninguem", "homem", "homens", "mulher", "mulheres",
    "crianca", "criancas", "menino", "meninos", "menina", "meninas", "gente", "familia",
    "pai", "mae", "filho", "filha", "filhos", "filhas", "avo", "avos", "neto", "neta", "netos",
    "irmao", "irma", "irmaos", "amigo", "amiga", "amigos", "vizinho", "vizinha", "vizinhos",
    "viuva", "viuvo", "pastor", "pastores", "pescador", "pescadores", "lavrador", "lavradores",
    "jardineiro", "carpinteiro", "rei", "profeta", "servo", "serva", "casal", "bebe",
    "braco", "bracos", "dedo", "dedos", "pes", "olho", "olhos", "cabelo", "cabelos",
    "vulto", "vultos", "pegada", "pegadas", "sombra humana",
    # texto
    "texto", "textos", "letra", "letras", "placa", "placas", "palavra", "palavras",
    "escrito", "escrita", "inscricao", "numero", "numeros",
    # símbolos de uma tradição / religiosos explícitos
    "cruz", "cruzes", "crucifixo", "terco", "rosario", "santo", "santa", "santos", "santas",
    "imagem", "imagens", "estatua", "estatuas", "igreja", "igrejas", "capela", "altar",
    "hostia", "calice", "vitral", "vitrais", "biblia", "senhora", "anjo", "anjos",
    "templo", "sinagoga", "catedral", "mosteiro", "convento", "ermida", "oratorio",
    "presepio", "manjedoura", "sino", "sinos", "cordeiro", "cordeiros", "taca", "vinho",
    "serpente", "jesus", "cristo", "deus", "senhor", "espirito", "maria", "jose",
    # bloco fixo de estilo (não entra na frase da cena)
    "aquarela", "guache", "pintura", "paleta", "vinheta", "creme", "granulado",
}

# Normalização do motivo principal (primeiro substantivo -> motivo).
SINONIMOS = {
    "estrada": "caminho", "trilha": "caminho", "vereda": "caminho",
    "riacho": "rio", "correnteza": "rio", "margem": "rio",
    "praia": "mar", "enseada": "mar", "onda": "mar", "ondas": "mar",
    "encosta": "colina", "morro": "colina",
    "monte": "montanha", "serra": "montanha", "mirante": "montanha", "pico": "montanha",
    "figueira": "arvore", "mangueira": "arvore", "oliveira": "arvore", "tronco": "arvore",
    "zimbro": "arvore", "arbusto": "arvore", "carvalho": "arvore", "ipe": "arvore",
    "vinha": "videira", "parreira": "videira",
    "muda": "semente", "broto": "semente", "brotos": "semente",
    "pedra": "rocha", "rochedo": "rocha", "abertura": "rocha",
    "lirio": "flor", "roseira": "flor", "rosa": "flor", "flores": "flor",
    "canteiro": "horta",
    "portao": "porta",
    "lampiao": "lamparina", "candeeiro": "lamparina", "lanterna": "lamparina",
    "calcada": "rua", "esquina": "rua",
    "salao": "sala", "corredor": "sala",
    "poltrona": "cadeira", "banco": "cadeira", "bancos": "cadeira",
    "degrau": "escada", "degraus": "escada",
    "trigal": "trigo", "seara": "trigo",
    "pasto": "campo", "campos": "campo", "lavoura": "campo",
    "nascente": "fonte",
    "bancada": "oficina",
    "pia": "cozinha", "panela": "cozinha", "despensa": "cozinha",
    "cesto": "cesta",
    "por": "entardecer",
    "amanhecer": "aurora", "manha": "aurora", "madrugada": "aurora",
    "xicara": "xicara", "bule": "xicara",
    "caixa": "caixa", "bau": "caixa", "gaveta": "caixa", "armario": "caixa", "estante": "caixa",
}

# Se a primeira palavra depois do artigo for um destes adjetivos/numerais, pula para a seguinte.
PULAR = {"primeira", "primeiro", "pequena", "pequeno", "grande", "velha", "velho", "unica", "unico"}

POMBA_CHAMA = {"pomba", "pombas", "chama", "chamas", "vela", "velas", "fogueira", "fogueiras", "brasa", "brasas"}

LUZ = re.compile(
    r"\b(luz|sol|amanhecer|aurora|entardecer|luar|lua|estrela|estrelas|estrelado|nascer|"
    r"clarea\w*|dourad\w*|acesa|aceso|acesas|iluminad\w*|ensolarad\w*|dia claro|manh[ãa]|noite|tarde|"
    r"meio-dia|anoitecer|madrugada|p[oô]r do sol|raios?)\b",
    re.IGNORECASE,
)


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def carregar_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def ids_esperados(app: Path) -> "OrderedDict[str, str]":
    """id -> baralho ('dias' para os dias fixos), na ordem esperada."""
    baralhos = carregar_json(app / "assets" / "content" / "baralhos.json")
    ordem: "OrderedDict[str, str]" = OrderedDict()
    for b in BARALHOS:
        for cid in baralhos[b]:
            ordem[cid] = b
    dias = sorted(p.stem for p in (app / "assets" / "content" / "dias").glob("*.json"))
    for cid in dias:
        ordem[cid] = "dias"
    return ordem


def motivo_de(frase: str) -> str:
    toks = [sem_acento(t) for t in re.findall(r"[\wÀ-ÿ'-]+", frase)]
    if toks and toks[0] in {"um", "uma"}:
        toks = toks[1:]
    while toks and toks[0] in PULAR:
        toks = toks[1:]
    if not toks:
        return "?"
    raiz = toks[0]
    return SINONIMOS.get(raiz, raiz)


def palavras_proibidas(frase: str) -> list[str]:
    plano = sem_acento(frase)
    achadas = []
    for w in PROIBIDAS:
        if " " in w:
            if w in plano:
                achadas.append(w)
        elif re.search(r"\b" + re.escape(w) + r"\b", plano):
            achadas.append(w)
    return sorted(achadas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", type=Path, default=APP_PADRAO, help="repo do app (padrão: ../../../manha-de-fe-app)")
    ap.add_argument("--cenas", type=Path, default=AQUI / "cenas.json")
    ap.add_argument("--motivos", action="store_true", help="imprime id -> motivo de cada cena")
    args = ap.parse_args()
    try:  # console do Windows costuma vir em cp1252
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    erros: list[str] = []
    avisos: list[str] = []

    esperados = ids_esperados(args.app)
    bruto = args.cenas.read_text(encoding="utf-8-sig")
    cenas: "OrderedDict[str, str]" = json.loads(bruto, object_pairs_hook=OrderedDict)

    # 1. cobertura e ordem
    faltam = [i for i in esperados if i not in cenas]
    sobram = [i for i in cenas if i not in esperados]
    if faltam:
        erros.append(f"faltam {len(faltam)} ids: {faltam[:10]}{' ...' if len(faltam) > 10 else ''}")
    if sobram:
        erros.append(f"sobram {len(sobram)} ids: {sobram[:10]}{' ...' if len(sobram) > 10 else ''}")
    if not faltam and not sobram and list(cenas) != list(esperados):
        erros.append("ordem das chaves difere da ordem esperada (baralhos.json e depois dias/ em ordem alfabética)")

    # 2 e 3. frase a frase
    motivos: "OrderedDict[str, str]" = OrderedDict()
    for cid, frase in cenas.items():
        if not isinstance(frase, str):
            erros.append(f"{cid}: valor não é string")
            continue
        n = len(frase.split())
        if not MIN_PALAVRAS <= n <= MAX_PALAVRAS:
            erros.append(f"{cid}: {n} palavras (esperado {MIN_PALAVRAS}-{MAX_PALAVRAS})")
        if "\n" in frase or "\r" in frase:
            erros.append(f"{cid}: quebra de linha na frase")
        if not re.match(r"^Uma? [a-záéíóúâêôãõç]", frase):
            erros.append(f"{cid}: não começa com 'Um '/'Uma ' seguido de substantivo minúsculo")
        if not frase.rstrip().endswith("."):
            erros.append(f"{cid}: não termina em ponto")
        if frase != frase.strip():
            erros.append(f"{cid}: espaço sobrando no começo ou no fim")
        ruins = palavras_proibidas(frase)
        if ruins:
            erros.append(f"{cid}: palavra proibida {ruins}")
        if not LUZ.search(frase):
            avisos.append(f"{cid}: não cita luz/hora do dia")
        motivos[cid] = motivo_de(frase)

    # 4. motivo principal
    total = len(cenas) or 1
    anterior: dict[str, tuple[str, str]] = {}
    for cid, mot in motivos.items():
        b = esperados.get(cid, "?")
        if b in anterior and anterior[b][1] == mot:
            erros.append(f"{cid}: motivo '{mot}' repete o do id anterior do baralho ({anterior[b][0]})")
        anterior[b] = (cid, mot)
    contagem = Counter(motivos.values())
    for mot, qtd in contagem.most_common():
        if qtd / total > TETO_MOTIVO:
            erros.append(f"motivo '{mot}' em {qtd} cenas = {qtd / total:.1%} (teto {TETO_MOTIVO:.0%})")

    # 5. pomba/chama
    com_pc = [cid for cid, f in cenas.items()
              if any(re.search(r"\b" + w + r"\b", sem_acento(f)) for w in POMBA_CHAMA)]
    if len(com_pc) / total > TETO_POMBA_CHAMA:
        erros.append(f"pomba/chama em {len(com_pc)} cenas = {len(com_pc) / total:.1%} (teto {TETO_POMBA_CHAMA:.0%})")

    # resumo
    por_baralho = Counter(esperados[c] for c in cenas if c in esperados)
    print(f"cenas: {len(cenas)} (esperadas {len(esperados)})  por baralho: {dict(por_baralho)}")
    tam = [len(f.split()) for f in cenas.values() if isinstance(f, str)]
    if tam:
        print(f"palavras por cena: min {min(tam)}  média {sum(tam) / len(tam):.1f}  max {max(tam)}")
    print(f"motivos distintos: {len(contagem)}  pomba/chama: {len(com_pc)} ({len(com_pc) / total:.1%})")
    lamp = sum(1 for f in cenas.values() if re.search(r"\blampari", sem_acento(f)))
    print(f"cenas que citam lamparina (objeto, informativo): {lamp} ({lamp / total:.1%})")
    print("distribuição de motivos (todos):")
    largura = max(len(m) for m in contagem) if contagem else 8
    for mot, qtd in contagem.most_common():
        print(f"  {mot:<{largura}} {qtd:>3}  {qtd / total:5.1%}")
    if args.motivos:
        print("motivo por cena:")
        for cid, mot in motivos.items():
            print(f"  {cid}: {mot}")

    for a in avisos:
        print("AVISO:", a)
    for e in erros:
        print("ERRO:", e)
    print(f"{len(erros)} erro(s), {len(avisos)} aviso(s)")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
