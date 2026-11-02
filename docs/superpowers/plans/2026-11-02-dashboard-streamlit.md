# Dashboard em Streamlit: plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam checkbox (`- [ ]`).

**Objetivo:** trocar o dashboard HTML por um app Streamlit com o relatório em quadros, o caminho da análise desenhado em linha e a entrada/saída de cada agente sem texto cortado.

**Arquitetura:** `dashboard/visao.py` (funções puras: eventos do `app.stream` e state → passos, DOT do caminho, quadros, JSON) + `dashboard/app.py` (só Streamlit, chama `fluxo_financeiro.app` direto). O Supervisor ganha a chave `decidido_por` no state. Sai o `dashboard/index.html` e a rota `GET /` da API.

**Stack:** Python 3.12, uv, Streamlit (`st.graphviz_chart`, `st.status`, `st.tabs`, `st.metric`, `st.json`), LangGraph `stream_mode=["updates", "values"]`, pytest + `streamlit.testing.v1.AppTest`.

**Spec:** `docs/superpowers/specs/2026-11-02-dashboard-streamlit-design.md` (aprovada pelo usuário em 02/11/2026).

## Restrições globais

- Branch `feat/dashboard-streamlit` (já criado). Commits em português, `tipo: descrição`, **sem** `Co-Authored-By`.
- Testes sem rede (`pytest-socket` + fixture do `conftest.py`). A suíte inteira passa ao fim de cada tarefa.
- O dashboard só reorganiza o que está no state: nunca calcula nem reformata números (`5.0x` continua `5.0x`).
- Nenhum texto de agente ou do relatório truncado sem jeito de abrir inteiro; nenhuma altura fixa com corte.
- Só o botão **Analisar** roda o grafo; o resultado vive em `st.session_state`.
- Camadas: `dashboard/` importa só `fluxo_financeiro` (app e tipos), como `main.py` e `api/`. `fluxo_financeiro` nunca importa `dashboard`.
- Código novo em snake_case (padrão do repo); chaves do state são contrato.
- `CLAUDE.md` e `.claude/docs/` são ignorados pelo git: editar, sem commit. Diagramas Mermaid validados com o mermaid-cli no scratchpad.

## Review Focus

1. **Grafo levanta exceção no meio:** a tela mostra `st.error` e os passos que já chegaram continuam em "Como foi feito". Teste na Tarefa 3 (`test_app_erro_no_grafo_mantem_passos`).
2. **Rerun do Streamlit sem clicar** (trocar de aba, abrir expansor): o grafo não roda de novo. Teste na Tarefa 3 (`test_app_nao_roda_de_novo_sem_clique`).
3. **`relatorio` nulo** (fallback do Consolidador): aviso + markdown da mensagem final. Teste na Tarefa 3 (`test_app_relatorio_nulo_mostra_fallback`).
4. **Ticker vazio ou com espaços/minúsculas** (`" petr4 "`): vazio avisa e não roda; o resto vira `PETR4`. Teste na Tarefa 3 (`test_app_ticker_vazio_nao_roda`, `test_app_normaliza_ticker`).
5. **Hard stop com 3+ passagens do Analyzer:** rótulos "Analyzer (empresa)", "Analyzer (setor)", "Analyzer (3)" e aviso de hard stop. Teste na Tarefa 2 (`test_montar_passos_hard_stop`).

---

### Tarefa 1: `decidido_por` no Supervisor

**Arquivos:**
- Modificar: `fluxo_financeiro/shared/types.py` (`MessagesState`), `fluxo_financeiro/graph/supervisor.py` (todas as saídas de `supervisor_node`), `api/server.py` (payload SSE)
- Testes: `tests/graph/test_supervisor.py`, `tests/graph/test_fluxo.py`

**Interfaces:**
- Produz: chave `decidido_por: str` no `MessagesState` (sobrescreve), com valores `"guard"`, `"llm"` ou `"hard_stop"`, presente em **toda** atualização do nó `Supervisor`.

- [ ] **Passo 1: testes.** Acrescentar `assert result["decidido_por"] == ...` nos testes existentes: `test_supervisor_node_hard_stop` → `"hard_stop"`; os cinco testes de guard (`..._yfinance_para_analyzer`, `..._investigator_retorna_finish`, `..._uma_passagem_do_analyzer_pede_o_setor`, `..._sinais_forca_investigator`, `..._sinais_espera_as_duas_passagens_do_analyzer`) → `"guard"`; os dois `test_supervisor_etapa4_*` → `"llm"`. Em `test_fluxo.py::test_hard_stop_segura_llm_que_nunca_encerra`: `assert resultado["decidido_por"] == "hard_stop"`.
- [ ] **Passo 2:** `uv run pytest tests/graph/ -q`. Esperado: FAIL com `KeyError: 'decidido_por'`.
- [ ] **Passo 3:** `decidido_por: str` no `MessagesState` (com comentário curto) e o campo em cada `return` do `supervisor_node`. No `api/server.py`, `payload["decidido_por"]` quando a chave vier na atualização.
- [ ] **Passo 4:** `uv run pytest tests/ -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit** `feat: supervisor grava no state quem decidiu cada passo (guard, llm, hard_stop)`.

---

### Tarefa 2: `dashboard/visao.py` (funções puras)

**Arquivos:**
- Criar: `dashboard/__init__.py` (vazio), `dashboard/visao.py`, `tests/dashboard/__init__.py`, `tests/dashboard/test_visao.py`
- Modificar: `pyproject.toml` (`include = ["fluxo_financeiro*", "api*", "dashboard*"]`)

**Interfaces:**
- Consome: eventos como `list[tuple[str, dict]]` = `(nome_do_nó, atualização)` vindos do modo `"updates"` do `app.stream`; `decidido_por` da Tarefa 1.
- Produz (em `dashboard/visao.py`):
  - `ROTULO_DECISAO = {"guard": "guard", "llm": "LLM", "hard_stop": "hard stop"}`
  - `@dataclass Passo: numero: int; agente: str; rotulo: str; decidido_por: str | None; raciocinio: str | None; entrada: str | None; saida: str`
  - `separar_indicador(texto: str) -> tuple[str, str | None]`: separa no **primeiro** `": "`; sem `": "` → `(texto, None)`.
  - `montar_passos(eventos) -> list[Passo]`: um `Passo` por evento de `YFinance`/`Analyzer`/`Investigator`, na ordem; `decidido_por`, `raciocinio` (`supervisor_reasoning`) e `entrada` (conteúdo da mensagem `name="Supervisor"`) vêm do evento `Supervisor` imediatamente anterior (ausentes → `None`). Rótulos: `"YFinance"`, `"Analyzer (empresa)"`, `"Analyzer (setor)"`, depois `"Analyzer (3)"`, `"Analyzer (4)"`...; `"Investigator"`. `saida` = conteúdo da última mensagem da atualização.
  - `decisao_do_fim(eventos) -> str | None`: `decidido_por` do último evento `Supervisor` com `next_agent == "FINISH"`.
  - `parou_no_hard_stop(eventos) -> bool`: esse mesmo `decidido_por` é `"hard_stop"`.
  - `dot_do_caminho(passos: list[Passo], decisao_fim: str | None) -> str`: DOT `digraph` com `rankdir=LR`; nó `inicio` ("Pedido"), um nó por passo (rótulo do passo, cor por agente: YFinance `#e0a030`, Analyzer `#3fb37f`, Investigator `#e05555`, Consolidador `#9b7bff`), nó `consolidador`; arestas em sequência com `label` = `ROTULO_DECISAO[...]` do passo de destino (e `decisao_fim` na aresta para o Consolidador), cor da aresta por decisão (guard `#2e7d32`, LLM `#1565c0`, hard stop `#c62828`). Se nenhum passo é Investigator: nó `investigator` com `style=dashed`, cinza, rótulo "Investigator\n(não rodou)", ligado ao último passo por aresta tracejada cinza sem rótulo.
  - `state_para_json(state: dict) -> dict`: `messages` → `[{"tipo": <classe>, "name": ..., "conteudo": ...}]`; `relatorio` e cada `sinais_anomalia` → `model_dump()` (ou `None`); demais chaves como estão.

- [ ] **Passo 1: testes** em `tests/dashboard/test_visao.py`. Montar um helper `_eventos(*sequencia)` com eventos falsos (`HumanMessage` com `name`). Testes, com as asserções:
  - `test_separar_indicador`: `("P/L: 5.0x")` → `("P/L", "5.0x")`; `("Abertura: 10:30")` → `("Abertura", "10:30")`; `("Lucro subiu")` → `("Lucro subiu", None)`.
  - `test_montar_passos_fluxo_normal`: Supervisor(llm, tarefa "Colete") → YFinance → Supervisor(guard, "Busque notícias") → Analyzer → Supervisor(guard, "Busque o setor") → Analyzer → Supervisor(llm, FINISH) → Consolidador. Esperado: 3 passos, rótulos `["YFinance", "Analyzer (empresa)", "Analyzer (setor)"]`, `entrada` do 2º == "Busque notícias", `decidido_por` `["llm", "guard", "guard"]`; `decisao_do_fim == "llm"`; `parou_no_hard_stop is False`.
  - `test_montar_passos_hard_stop`: três Analyzer e o último Supervisor com `decidido_por="hard_stop"` e `next_agent="FINISH"` → terceiro rótulo `"Analyzer (3)"`, `parou_no_hard_stop is True`.
  - `test_montar_passos_sem_supervisor_antes`: worker sem Supervisor anterior → `entrada`, `decidido_por` e `raciocinio` `None`.
  - `test_dot_do_caminho_ordem_e_rotulos`: DOT contém `rankdir=LR`, os rótulos na ordem (índices crescentes), `label="guard"` e `label="LLM"`.
  - `test_dot_do_caminho_investigator_tracejado`: sem Investigator nos passos → contém `"não rodou"` e `style=dashed`; com Investigator → não contém `"não rodou"`.
  - `test_state_para_json`: state com 2 mensagens, `relatorio=RelatorioFinal(...)` e um `SinalAnomalia` → `json.dumps(resultado)` não levanta; `resultado["messages"][1]["name"] == "YFinance"`; `resultado["relatorio"]["resumo"] == ...`.
- [ ] **Passo 2:** `uv run pytest tests/dashboard/ -q`. Esperado: FAIL (`ModuleNotFoundError: dashboard.visao`).
- [ ] **Passo 3:** implementar `dashboard/visao.py` com as interfaces acima; `uv sync` depois de mudar o `packages.find`.
- [ ] **Passo 4:** `uv run pytest tests/ -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit** `feat: funções que transformam o state no que o dashboard mostra`.

---

### Tarefa 3: app Streamlit

**Arquivos:**
- Criar: `dashboard/app.py`, `tests/dashboard/test_app.py`
- Modificar: `pyproject.toml` (`uv add streamlit`), `Makefile` (alvo `streamlit` + `.PHONY` + `help`)
- Modificar o spec: em "Testes", trocar "O app Streamlit em si não ganha teste unitário" por "O app ganha testes de fumaça com `AppTest` e um grafo falso (sem rede)".

**Interfaces:**
- Consome: tudo da Tarefa 2; `from fluxo_financeiro import app as grafo` **dentro** do script (para o teste poder trocar `fluxo_financeiro.app`).
- Produz: `dashboard/app.py` com um `st.text_input` (ticker, `key="ticker"`), um `st.button("Analisar")`, `st.session_state["resultado"] = {"ticker", "eventos", "state", "erro"}`; abas `"Relatório"`, `"Como foi feito"`, `"State (JSON)"`, nessa ordem. Comportamento descrito na spec, seção "Como a tela funciona". O stream usa `grafo.stream({"messages": [HumanMessage(f"Analise a ação {ticker}")]}, stream_mode=["updates", "values"])`: `"updates"` → `eventos`, `"values"` → `state` (o último). O `st.status` escreve uma linha por evento de worker/Consolidador.

- [ ] **Passo 1: testes** em `tests/dashboard/test_app.py` com `AppTest.from_file("dashboard/app.py")` e `patch("fluxo_financeiro.app", grafo_falso)`, onde `grafo_falso.stream` devolve uma lista fixa de `("updates", {...})`/`("values", {...})` de uma análise completa da PETR4 (o state final da conversa de 02/11, com `relatorio` preenchido e `decidido_por` nos Supervisor). Asserções:
  - `test_app_mostra_relatorio`: após `text_input("ticker").input("PETR4")` e clique → sem `at.exception`; `at.metric` contém um com `label == "P/L"` e `value == "5.0x"`; o markdown contém o resumo; existem 3 abas.
  - `test_app_normaliza_ticker`: entrada `" petr4 "` → o `HumanMessage` passado ao `stream` é `"Analise a ação PETR4"`.
  - `test_app_ticker_vazio_nao_roda`: clique com campo vazio → `at.warning` não vazio e `stream` não chamado.
  - `test_app_nao_roda_de_novo_sem_clique`: clique, depois `at.run()` sem clique → `stream` chamado 1 vez e o relatório continua na tela.
  - `test_app_relatorio_nulo_mostra_fallback`: state final com `relatorio=None` e mensagem final `"> Não foi possível consolidar..."` → `at.warning` não vazio e o markdown contém essa frase.
  - `test_app_erro_no_grafo_mantem_passos`: `stream` levanta `Exception("429")` depois do evento do YFinance → `at.error` contém `"429"`; a aba "Como foi feito" contém `"YFinance"`.
- [ ] **Passo 2:** `uv run pytest tests/dashboard/test_app.py -q`. Esperado: FAIL (`ModuleNotFoundError: streamlit` ou arquivo inexistente).
- [ ] **Passo 3:** `uv add streamlit`; implementar `dashboard/app.py`. Saída do YFinance com `st.code(..., language=None)`; outras saídas com `st.markdown` dentro de `st.expander` (sem altura fixa). Grafo com `st.graphviz_chart(dot_do_caminho(...))`. Download com `st.download_button` (`file_name=f"relatorio_{ticker}.md"`). Alvo `streamlit:` no Makefile: `uv run streamlit run dashboard/app.py`.
- [ ] **Passo 4:** `uv run pytest tests/ -q`. Esperado: tudo passa. Se o `AppTest` abrir socket (bloqueado pelo `pytest-socket`), ler o traceback antes de liberar qualquer coisa: só um socket local do próprio Streamlit justifica `@pytest.mark.enable_socket`, com comentário.
- [ ] **Passo 5:** `uv run streamlit run dashboard/app.py --server.headless true` em segundo plano e conferir que responde em `http://localhost:8501` (HTTP 200); encerrar.
- [ ] **Passo 6: commit** `feat: dashboard em Streamlit com relatório, caminho da análise e state`.

---

### Tarefa 4: tirar o HTML e atualizar docs

**Arquivos:**
- Apagar: `dashboard/index.html`
- Modificar: `api/server.py` (sai `serve_dashboard`, `DASHBOARD`, `HTMLResponse`, `pathlib`), `Makefile` (texto do `serve`: "sobe a API (SSE) em http://127.0.0.1:8000/analyze"), `.gitignore` (`.superpowers/`), `README.md`, `docs/arquitetura.md`, `docs/decisoes.md`
- Local (sem commit): `CLAUDE.md`, `.claude/docs/architecture.md`, `.claude/docs/tests.md`

- [ ] **Passo 1:** apagar o HTML e a rota; `uv run python -c "import api.server"` sem erro e `uv run pytest tests/ -q` passando.
- [ ] **Passo 2:** `docs/decisoes.md`: D46 na "Parte 6 — Visualizar o que está acontecendo", depois da D23: "Dashboard em Streamlit no lugar do HTML". Por quê: texto cortado nos cards e desenho do fluxo ilegível; o state já tem o relatório estruturado; quadros, abas e expansores vêm prontos no Streamlit; o caminho percorrido em linha (graphviz) se lê melhor que o grafo animado. O que fica: `/analyze` sem tela consumindo, base para o relatório em JSON pela API. Custo: perde a animação e o PDF. Título da D23 ganha "(substituída por D46)". A pergunta "levar o `relatorio` como JSON para o SSE e para o dashboard (cards por seção)" das próximas decisões: marcar a parte do dashboard como feita (D46).
- [ ] **Passo 3:** `docs/arquitetura.md`, diagrama de camadas: `DASH["dashboard/app.py<br/>Streamlit"]` ligado direto a `APP` (`DASH --> APP`), sem a seta para a API; validar o bloco com o mermaid-cli. README: seção de como rodar (`make streamlit`, http://localhost:8501), a lista da API sem o `GET /`, a árvore de pastas.
- [ ] **Passo 4: commit** `feat: streamlit substitui o dashboard html; api fica só com /analyze`.
- [ ] **Passo 5 (local):** `CLAUDE.md` (comandos, estrutura, estado), `.claude/docs/architecture.md` (seção api/dashboard), `.claude/docs/tests.md` (pasta `tests/dashboard/` e contagem).

---

### Tarefa 5: verificação final

- [ ] **Passo 1:** `uv run pytest tests/ -q` e `make check`. Esperado: tudo passa; nós do grafo iguais.
- [ ] **Passo 2 (gasta ~US$ 0,02, pedir ok ao usuário):** `make streamlit`, rodar PETR4 ou VALE3 no navegador e conferir as três abas.
