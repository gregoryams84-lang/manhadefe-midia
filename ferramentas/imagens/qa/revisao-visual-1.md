# Revisão visual — 392 imagens neutras (Manhã de Fé)

Revisão feita miniatura por miniatura nas 33 folhas de contato (`folha-01.png` a `folha-33.png`), com abertura da imagem grande (`imagens/<id>.webp`) sempre que houve dúvida, e conferência de coerência contra `cenas.json`.

## 1. Reprovadas (4)

| id | Motivo |
|---|---|
| **advento-021** | O vilarejo no alto da colina tem um prédio com torre/campanário nitidamente mais alto e afilado que as casas ao redor — lê como igreja/capela (símbolo de uma tradição). Sugestão: regenerar removendo a torre, ou trocar a frase por algo como "com um vilarejo pequeno de casas simples no alto, sob luz dourada" sem menção implícita a marco religioso. |
| **comum-109** | No vilarejo ao fundo (visto da varanda) há uma construção clara com torre/campanário de igreja, incluindo o formato de agulha típico. Sugestão: ajustar a frase para "as primeiras luzes de um vilarejo simples ao longe" e regenerar sem edificação de culto. |
| **natal-012** | A "cidade antiga" vista da janela mostra cúpulas verdes e torres inconfundíveis de catedral (composição muito próxima de um skyline tipo Florença/Duomo) — o caso mais evidente de símbolo religioso do lote. Sugestão: trocar para um horizonte de telhados comuns, sem cúpulas, ou usar uma vila menor sem monumento central. |
| **quaresma-037** | Não é problema de conteúdo (cena de porta de cela com correntes partidas está correta e sem figuras), mas de acabamento: a borda **não dissolve em creme** — a imagem inteira fecha num azul-marinho quase preto até a quina, diferente do padrão do resto do baralho. Comparei com outras cenas noturnas (`01-06`, `quaresma-030`) que dissolvem normalmente nos cantos; aqui não dissolve, é moldura dura. Sugestão: regenerar mantendo a cena, mas com a vinheta padrão em creme #FBF6EC. |

## 2. Atenção (aceitáveis, mas podem valer revisão) — 6

| id | Observação |
|---|---|
| **comum-003** | Cena pede "duas árvores lado a lado"; a arte entrega uma árvore de tronco duplo fundido na base (lê mais como uma árvore bifurcada do que duas árvores distintas). O texto "sombras juntas" sustenta a leitura, mas vale seu olhar. |
| **comum-026** | Cena pede "um vaso de flores" (singular) no parapeito; a imagem mostra dois vasos. Diferença pequena, não compromete a leitura. |
| **comum-080** | Corredor de pedra com arco em ogiva (gótico) e nicho — sem cruz nem símbolo explícito, mas a arquitetura lembra fortemente claustro/capela. Pode incomodar por associação, mesmo sem violar a regra ao pé da letra. |
| **comum-088** | Cena pede vidro de janela embaçado pela chuva; a arte mostra chuva caindo direto sobre o quintal, sem moldura/vidro de janela visível — interpretação livre do prompt, não um erro de estilo. |
| **quaresma-014** | A vinheta superior estoura quase para branco puro (mais lavada que o creme padrão das outras folhas) — pequena inconsistência de acabamento, não de conteúdo. |
| **quaresma-041** | Skyline da "cidade antiga" tem 2-3 torres estreitas com topo pontudo; ambíguo — podem ser torres civis (estilo San Gimignano) e não campanários de igreja. Menos evidente que os 3 casos reprovados, mas fica registrado para sua decisão. |

Conferi com atenção redobrada os pontos citados pelo autor das cenas:
- **natal-003** (estábulo): interior vazio, sem figuras inventadas — ok.
- **natal-009** (mesa de Natal): grinalda de pinheiro decorativa na janela, sem viés religioso — ok.
- **"cela"** (`quaresma-037`): grades e correntes partidas corretas, problema é só de moldura (ver reprovadas).
- **curral** (`quaresma-004`): curral vazio e lamacento, sem animais — ok.
- **cavalo/cervo longe e sem rosto**: conferidos `comum-199`, `pascoa-041` (cavalo) e `quaresma-002` (cervo) — todos pequenos, de costas/cabeça baixa, sem rosto em destaque — ok.
- **peixe como comida** (`pascoa-008`/`009`): tratamento de natureza-morta/churrasco de acampamento, não bicho de estimação — ok.
- **quaresma mais escuras (003, 008, 014, 026, 043)**: abertas em tamanho grande; nenhuma ficou pesada ou ilegível — tons acinzentados mas ainda dentro da paleta aquarela clara. Única ressalva de acabamento é a vinheta de `quaresma-014` (ver tabela acima), não o nível de escuridão.

## 3. Impressão geral de consistência

Estilo muito consistente ao longo das 33 folhas: fundo creme quente, granulado de papel visível, paleta dourado/verde/azul suave repetida sem desvio perceptível de folha para folha, e bordas superior/inferior dissolvendo em creme na esmagadora maioria das imagens — inclusive em cenas noturnas escuras (testei lado a lado `01-06` e `quaresma-030`, ambas dissolvem bem nos quatro cantos). Não achei nenhuma folha inteira destoante da paleta ou do granulado; os desvios encontrados são pontuais (`quaresma-037` com moldura dura; `quaresma-014` com vinheta lavada demais), não sistêmicos. Não há texto/letras inventadas, pessoas, mãos ou silhuetas humanas em nenhuma das 392 imagens revisadas, e os símbolos de tradição religiosa (cruz, terço, altar, cálice, bíblia, imagem de santo) não aparecem — o único ponto recorrente de risco foi o campanário/torre de igreja aparecendo sem querer em silhuetas de vilarejo/cidade ao fundo (3 casos reprovados + 1 em atenção), o que sugere vale um cuidado extra nesse tipo de cena específica ("vilarejo", "cidade antiga") em rodadas futuras de geração.

## 4. Contagem final

- **Aprovadas:** 382
- **Reprovadas:** 4
- **Atenção:** 6
- **Total revisado:** 392
