# Manhã de Fé — mídia

Arquivos públicos que o aplicativo **Manhã de Fé** baixa em segundo plano
(narrações e imagens), servidos em `https://midia.manhadefe.com.br/` pelo
GitHub Pages. Nenhum dado pessoal passa por aqui: são arquivos iguais para
todo mundo.

## Estrutura

| Pasta | Conteúdo | Nome do arquivo |
|---|---|---|
| `narracao/catolico/` | narração dos cartões e festas, voz do Padre | `<id>.m4a` (ex.: `comum-001.m4a`, `movel-pascoa.m4a`) |
| `narracao/evangelico/` | narração dos cartões e festas, voz do Pastor | `<id>.m4a` |
| `imagens/` | imagem neutra (aquarela) e arte sacra do cartão | `<id>.webp` e `<id>-catolico.webp` |
| `santos/` | narração e retrato do santo do dia | `<MM-DD>.m4a` e `<slug>.webp` |
| `hinos/` | gravação do hino do dia | `<slug>.m4a` |
| `ferramentas/` | scripts de produção (não são publicados pelo app) | |

Formatos: áudio AAC mono ~32 kbps (`.m4a`); imagens WebP 1080 × 1350.

## `manifesto.json`

Lista cada arquivo com `bytes` e `sha256`. O aplicativo só usa arquivo
íntegro e substitui automaticamente quando o hash muda.

**Não editar à mão.** Gerar sempre a partir do repositório do app:

```
dart run tool/midia/gerar_manifesto.dart ../manhadefe-midia
dart run tool/lint_conteudo.dart --manifesto=../manhadefe-midia/manifesto.json
```

Depois: commit (mídia e manifesto no mesmo push), push, e aguardar ~10 min
de propagação do CDN.

## Higiene

- Sem Git LFS (o Pages serviria o ponteiro, não o arquivo).
- Quando `.git` passar de ~700 MB (regravações acumulam blobs), recomeçar o
  histórico com `git checkout --orphan` e force push; o site não usa o
  histórico.
