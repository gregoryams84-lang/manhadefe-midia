# Manhã de Fé — mídia

Arquivos públicos que o aplicativo **Manhã de Fé** baixa em segundo plano
(narrações, imagens, o áudio do Terço e o das orações guiadas), servidos em `https://midia.manhadefe.com.br/` pelo
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
| `terco/` | áudio do Terço, camada católica (os 4 conjuntos de mistérios × 7 trechos; baixável desde 25/09/2026) | `<misterio>-<trecho>.m4a` (ex.: `gozosos-abertura.m4a`, `dolorosos-dezena-3.m4a`, `luminosos-fecho.m4a`) |
| `oracoes/` | áudio das orações guiadas, camada da tradição (as 4 comuns e as de cada tradição; baixável desde 09/10/2026, decisão D3) | `<id>.m4a` (ex.: `salmo-23.m4a`, `ave-maria.m4a`, `pai-nosso-evangelico.m4a`) |
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
de propagação do CDN. Então conferir que o servidor serve o que o manifesto
promete — um HEAD em cada entrada do manifesto publicado (200 e
Content-Length = bytes) e em cada vídeo da novela pela base `videos` do
índice; o manifesto publicado tem de ser o deste repositório (senão o push
não chegou):

```
python ferramentas/conferir_servidor.py --midia .
```

Lista o que falhou e sai com 1; nada falhou, 0. Nunca escreve nada.

## Publicar uma temporada da novela (o dia da publicação)

1. `python ferramentas/publicar_temporada.py "<pasta da entrega>" --motor elevenlabs`
   (confere a entrega, sobe os vídeos ao R2 sem sobrescrever, escreve os
   JSONs, as capas e as legendas, gera só a voz que mudou, confere por STT,
   refaz o manifesto e roda o lint — `--simular` antes, numa pasta
   temporária, para ver o que faria; `--help` para o resto).
   Com o domínio dos vídeos no ar (o DNS do `manhadefe.com.br` na
   Cloudflare), acrescente `--videos-base https://video.manhadefe.com.br/`:
   sem a opção e sem índice anterior, a base `videos` do índice sai da
   Public Development URL do R2 (`*.r2.dev`, que a Cloudflare limita), com
   aviso — e corrigir depois é republicar só o índice e o manifesto.
2. Commit por caminho (`git add -- <novos>`; `git commit -- <caminhos>`), com
   cada `.origem` junto do `.m4a` dele. Push só com o OK do Gregory.
3. ~10 min depois: `python ferramentas/conferir_servidor.py --midia .` (ou
   `--so-novela`; `--paralelo 4` se o Pages limitar os HEADs — o padrão é
   8). Só com "tudo no ar" a temporada está publicada.

## Higiene

- Sem Git LFS (o Pages serviria o ponteiro, não o arquivo).
- Quando `.git` passar de ~700 MB (regravações acumulam blobs), recomeçar o
  histórico com `git checkout --orphan` e force push; o site não usa o
  histórico.
