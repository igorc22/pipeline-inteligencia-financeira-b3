# Arrumações da v1: notebooks, remoção da API e fechamento da versão

Branch: `feat/arrumacoes-v1` (a partir do `master` com a sanitização mergeada).

## Intenção

Fechar a v1 do projeto. A parte principal são os notebooks: hoje metade não roda (ainda usa a Anthropic, de antes da migração para o Gemini na D33) e as features mais novas não têm notebook nenhum. Para o usuário, cada notebook serve a dois propósitos ao mesmo tempo:

- **caderno de estudo:** o problema que a peça resolve, o porquê da decisão (D-xx) e os conceitos financeiros em linguagem simples;
- **ver ao vivo:** a peça rodando de verdade, com as APIs reais, e o que observar na saída.

Junto, três arrumações que já estavam combinadas para a v1: remover a API (nada a usa), listar as limitações conhecidas no README e marcar a versão 1.0.0.

## Objetivos

1. Todo notebook roda de cima a baixo com as APIs reais (Gemini, Google Search, yfinance, BCB), usando o `.env` do projeto.
2. Todo notebook segue o mesmo roteiro: problema e decisão → conceitos (técnicos e financeiros) → a peça rodando → o que observar.
3. Os notebooks **importam** a peça de `fluxo_financeiro`; não reimplementam código de produção (exceção: os de `estudo/`, que ensinam o padrão com um exemplo próprio).
4. As saídas ficam salvas nos arquivos, para o usuário abrir e já ver uma execução.
5. A API sai do projeto sem deixar referência pendurada (código, Makefile, dependências, testes, docs).
6. README com uma seção de limitações conhecidas; `pyproject.toml` em `1.0.0`.

## Não objetivos

- Notebook do dashboard (decisão do usuário: não precisa).
- Modo "sem custo" com saídas simuladas (decisão do usuário: pode rodar de verdade).
- Versionar os notebooks: `/notebooks` continua no `.gitignore`, como já era.
- `busca_indicador_bcb` (D14): fica pausada, como o usuário pediu. Os notebooks não a apresentam como parte do pipeline.
- Histórico de análises em SQLite: ideia aceita para depois da v1, fora desta branch.
- Os achados pequenos adiados da revisão da sanitização.

## Antiobjetivos (falharia mesmo funcionando)

- Notebook com cópia do código de produção, que desatualiza na primeira mudança do pacote.
- Notebook que roda o pipeline inteiro várias vezes: cada execução completa custa ~US$ 0,016 e ~25 s. No máximo **uma** análise completa por notebook.
- Travessão (—) e os símbolos ✓ ✗ nos notebooks (preferência registrada do usuário).
- Jargão sem explicação: a convenção do projeto exige explicar cada conceito financeiro em linguagem simples (ex: Sharpe, impairment, fato relevante).

## Inventário: o que acontece com cada notebook

Os nomes seguem a ordem em que o pipeline roda. `estudo/` ensina o padrão; `fluxo_financeiro/` mostra o projeto.

| Notebook | Hoje | Destino |
|---|---|---|
| `estudo/01_subagents_and_tools` | Anthropic, quebrado | Reescrever com `criar_llm()` (Gemini). Mantém o exemplo de calendário/e-mail. Explica por que não se passa temperatura no Gemini 3 |
| `estudo/02_supervisor_orchestration` | Anthropic, quebrado | Idem, mantendo o padrão "subagente como tool". Termina apontando a diferença para o projeto: aqui o supervisor é um `create_agent`; no projeto é uma função com guards |
| `fluxo_financeiro/01_yfinance_agent` | curto, desatualizado | Reescrever: as 3 tools com `.invoke`, `YFINANCE_PROMPT`, o agente respondendo, o sumário chegando em `<conteudo_externo>` |
| `fluxo_financeiro/02_analyzer_agent` | curto, desatualizado | Reescrever: web primeiro e NewsAPI de reserva (D44), as duas passagens (empresa e setor, D45) |
| `fluxo_financeiro/03_coordinator` | importa módulo que não existe | Substituir por `03_supervisor_e_grafo`: desenho do grafo, pipeline de 4 etapas, guards × LLM, `decidido_por`, `loop_count`, hard stop; uma análise completa com `app.stream` |
| `04_tools_calcular_piotroski_score`, `05_tools_dados_b3`, `06_new_metrics` | protótipos com yfinance direto (calculam à mão o que hoje está nas tools) | Mantidos como protótipos: são o registro de como cada métrica nasceu. Executar e corrigir só o que quebrar, e acrescentar no fim uma seção "O que virou no projeto" chamando a tool correspondente com `.invoke` |
| `07_web_search_tool` | Anthropic, quebrado | Reescrever: `pesquisar_na_web` (Gemini + Google Search), fontes só com o nome do site (D38), faturamento (D35), `buscar_noticias_web` × `buscar_noticias` |
| `08_investigator_tools` | Anthropic, quebrado | Reescrever: `buscar_historico_trimestral` e `buscar_fatos_relevantes`; pontual × estrutural × cíclico, impairment, fato relevante |
| `09_investigator_agent` | Anthropic, quebrado | Reescrever: o agente real, o limite de 4 buscas em código (`ToolCallLimitMiddleware`, D37), as 4 seções do diagnóstico |
| **novo** `10_sinais_anomalia_e_guards` | não existe | D40 e D45: `detectar_sinais_anomalia` na VALE3 e na WEGE3; `supervisor_node` com estados montados à mão mostrando cada guard e o `decidido_por` |
| **novo** `11_consolidador` | não existe | D41 e D42: `consolidar` sobre o histórico de uma análise real, `RelatorioFinal`, `formatar_relatorio`, limitações escritas em código, fallback de emergência |
| **novo** `12_observabilidade_langsmith` | não existe | D36: o que é um trace, tracing ligado pelo `.env`, `wrap_gemini` na busca. Se as variáveis do LangSmith não estiverem no `.env`, o notebook explica e pula as células que dependem delas, sem erro |
| **novo** `13_sanitizacao` | não existe | D47 a D49: `validar_ticker`, a tag e o escape (inclusive a tentativa de fechar a tag), o classificador com um texto malicioso e um legítimo, a flag ligada só dentro do notebook |

Os arquivos substituídos (`03_coordinator`) são apagados. Os notebooks antigos que serão reescritos são sobrescritos.

## Remoção da API

- Sai: `api/` (com `server.py`), `serve.py`, a receita `serve` do `Makefile` (e a linha dela no `make help`), `tests/api/`, as dependências `fastapi` e `uvicorn` do `pyproject.toml` (conferido: só `api/`, `serve.py` e `tests/api/` as importam; o `uv.lock` acompanha via `uv sync`).
- Docs: README, `docs/arquitetura.md` (diagramas que mostram a API, validados com o mermaid-cli), `CLAUDE.md` e `.claude/docs/`.
- Diário: **D50** registra a remoção e marca como substituída a parte da D46 que mantinha a rota "como base para levar o `relatorio` em JSON". A Fase 4 do roadmap deixa de citar a API.

## README e versão

- Seção "Limitações conhecidas": regras de anomalia calibradas com poucos tickers (limites em `tools/anomalias.py`); yfinance atrasa os trimestrais; a busca na web depende de faturamento ativo na chave do Gemini; o classificador da sanitização também é um LLM e pode errar; `busca_indicador_bcb` existe mas está pausada.
- `pyproject.toml`: `version = "1.0.0"`. A tag `v1.0.0` é criada depois do merge, com o OK do usuário.

## Restrições

- Ambiente: `uv`, Python 3.12, `ipykernel`/`nbconvert`/`nbclient` já instalados. Executar com `uv run jupyter nbconvert --to notebook --execute --inplace <arquivo>`.
- Windows: `PYTHONIOENCODING=utf-8` ao executar.
- Os notebooks rodam a partir de `notebooks/<pasta>/`: a primeira célula põe a raiz do projeto no `sys.path` e carrega o `.env`.
- Commits em pt-BR, `tipo: descrição`, sem `Co-Authored-By`; `git add` com arquivos explícitos (`projeto.md` é do usuário).

## Escolhas minhas (marcadas para o usuário conferir)

- Tickers dos exemplos: **VALE3** (aciona o Investigator) e **WEGE3** (estável), os mesmos do e2e.
- `03_coordinator` vira `03_supervisor_e_grafo` (o nome antigo é de antes do Supervisor).
- O notebook do LangSmith pula as células de trace quando não há chave, em vez de falhar.
- No notebook da sanitização, a flag é ligada trocando o atributo do módulo (`sanitizacao.SANITIZACAO_ATIVA = True`), o que também ensina como a flag é lida.
- Custo estimado de executar todos os notebooks uma vez: abaixo de US$ 0,15.
- Os notebooks 04 a 06 continuam como protótipos que calculam à mão (exceção ao antiobjetivo de não copiar código de produção, porque o valor deles é mostrar a conta passo a passo); a seção final liga cada um à tool real.

## Deixado para quem constrói

O número e a ordem das células dentro de cada notebook, o texto das explicações (seguindo o roteiro dos Objetivos), e a estrutura interna de cada exemplo.
