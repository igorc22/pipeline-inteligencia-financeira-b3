# Arrumações rápidas: plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam checkbox (`- [ ]`).

**Objetivo:** cinco ajustes pequenos e independentes: rede bloqueada nos testes, busca na web antes da NewsAPI no Analyzer, logs de falha da busca em uma linha, os pontos menores da revisão do Consolidador e uma nota de revisão pendente sobre o `busca_indicador_bcb`.

**Arquitetura:** nenhuma mudança no grafo. Mudam o prompt do Analyzer, o pós-processamento do `consolidar()`, o log das duas tools de busca, a checagem do e2e, um diagrama e a configuração do pytest.

**Stack:** Python 3.12, uv, pytest + `pytest-socket` (novo, só no grupo dev), LangChain/LangGraph, Mermaid.

**Spec (aprovada em chat em 02/11/2026):**
1. `pytest-socket` no grupo dev com `--disable-socket` no `pyproject.toml`; um teste prova que a rede está bloqueada. Se alguma biblioteca abrir socket na importação (Windows), liberar só esse caso.
2. Analyzer: `buscar_noticias_web` primeiro; `buscar_noticias` (NewsAPI) só se a web falhar ou voltar vazia. Atualizar docstrings das duas tools, o rótulo do diagrama, o `.claude/docs/agents.md` e registrar decisão nova no `decisoes.md`.
3. Nas duas tools de busca na web (`buscar_noticias_web`, `buscar_fatos_relevantes`), a falha vira uma linha só de `ERROR`; o traceback só aparece com `LOG_LEVEL=DEBUG`. As tools do yfinance continuam com `logger.exception` (escolha do Claude).
4. Pontos do revisor: (a) limitações sem repetição, mantendo a ordem; (b) limitação "O contexto do setor não foi pesquisado." quando o Analyzer rodou uma vez só; (c) no diagrama de fluxo, "aresta fixa" sai da seta Supervisor→Consolidador e vai para Consolidador→Fim; (d) o e2e exige o texto inteiro do Investigator no relatório final.
5. D14 ganha a nota "preciso revisar: registrar no YFinance ou apagar", com data 02/11/2026. A tool não muda.
6. No fim: pendências do `CLAUDE.md` e contagem de testes do `.claude/docs/tests.md` atualizadas.

## Restrições globais

- Branch `feat/arrumacoes-rapidas` a partir do `master`; merge com `--no-ff` só depois que o usuário aprovar.
- Commits em português, `tipo: descrição`, **sem** linha `Co-Authored-By` (regra do usuário).
- Testes sem rede; LLM e busca sempre mockados. A suíte inteira (`uv run pytest tests/ -q`) passa ao fim de cada tarefa.
- Código novo segue o snake_case do código existente (nomes de tools e chaves do state são contratos).
- Sem travessão (—) em textos novos de docs e mensagens.
- `CLAUDE.md` e `.claude/docs/` são ignorados pelo git: editar, mas não entram em commit.
- Diagramas Mermaid validados com `npx -y @mermaid-js/mermaid-cli -i bloco.mmd -o bloco.png` (no scratchpad, não no repo).

## Review Focus

1. **Exceção do SDK do Google com mensagem longa e de várias linhas** (o `ClientError` traz o JSON do erro): o log precisa continuar sendo uma linha curta. Teste na Tarefa 2 (`test_falha_da_busca_loga_uma_linha_curta`).
2. **Diagnóstico com espaço ou quebra de linha no fim:** `formatar_relatorio` faz `strip()` no diagnóstico; o e2e não pode acusar falha por isso. Teste na Tarefa 5 (`test_conferir_diagnostico_ignora_espacos_nas_pontas`).
3. **Limitação do LLM igual à do código a menos de espaços nas pontas:** a deduplicação compara com `strip()`. Teste na Tarefa 4 (`test_consolidar_nao_repete_limitacoes`).
4. **Histórico sem nenhum Analyzer:** só entra `LIMITACAO_SEM_NOTICIAS`, sem a de setor junto (a primeira já cobre). Teste na Tarefa 4 (`test_consolidar_aponta_setor_que_faltou`).
5. **`LOG_LEVEL=DEBUG`:** o traceback continua disponível para depurar. Teste na Tarefa 2 (`test_falha_da_busca_tem_traceback_em_debug`).

---

### Tarefa 0: Branch

- [ ] **Passo 1:** `git checkout master && git checkout -b feat/arrumacoes-rapidas`. Esperado: `Switched to a new branch`. O `projeto.md` não rastreado fica como está (não entra em commit).
- [ ] **Passo 2:** `git add docs/superpowers/plans/2026-11-02-arrumacoes-rapidas.md && git commit -m "docs: plano das arrumações rápidas"`.

---

### Tarefa 1: Rede bloqueada nos testes

**Arquivos:**
- Modificar: `pyproject.toml` (grupo dev + seção `[tool.pytest.ini_options]`)
- Criar: `tests/test_rede_bloqueada.py`
- Modificar: `docs/decisoes.md` (D43, na seção "Jeito de trabalhar")

- [ ] **Passo 1: teste**

```python
import socket

import pytest
from pytest_socket import SocketBlockedError


def test_rede_bloqueada_nos_testes():
    """Test que qualquer socket é barrado: um mock esquecido falha em vez de chamar a API real."""
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
```

- [ ] **Passo 2:** `uv run pytest tests/test_rede_bloqueada.py -v`. Esperado: FAIL (`ModuleNotFoundError: pytest_socket`).
- [ ] **Passo 3:** `uv add --dev pytest-socket` e, no `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "--disable-socket"
```

- [ ] **Passo 4:** `uv run pytest tests/ -q`. Esperado: 92 passed. Se algum teste quebrar com `SocketBlockedError`, ler o traceback: com `socketpair` ou `_make_self_pipe`, é o asyncio abrindo um event loop no Windows, e se libera só aquele teste com `@pytest.mark.enable_socket` e um comentário dizendo por quê; com `connect` para um host externo, é mock esquecido, e se corrige o mock.
- [ ] **Passo 5:** D43 no `docs/decisoes.md`, na seção "Jeito de trabalhar", logo depois da D32 (o arquivo é por tema, não por número): "Rede bloqueada nos testes com `pytest-socket`". Por quê: duas vezes um mock esquecido virou chamada real à API; a D30 (testes 100% mockados) era só convenção, agora é garantida. Custo: um teste que precise de rede de propósito tem de pedir com `@pytest.mark.enable_socket`.
- [ ] **Passo 6: commit**

```bash
git add pyproject.toml uv.lock tests/test_rede_bloqueada.py docs/decisoes.md
git commit -m "test: bloquear rede nos testes com pytest-socket"
```

---

### Tarefa 2: Falha da busca na web em uma linha de log

**Arquivos:**
- Modificar: `fluxo_financeiro/tools/web_search.py` (helper novo)
- Modificar: `fluxo_financeiro/tools/news.py:94-96` (`except` de `buscar_noticias_web`)
- Modificar: `fluxo_financeiro/tools/investigation.py:89-91` (`except` de `buscar_fatos_relevantes`)
- Testes: `tests/tools/test_web_search.py`, `tests/tools/test_investigation.py`

**Interfaces:**
- Produz: `registrar_falha_busca(contexto: str, erro: Exception) -> None` em `tools/web_search.py`. Emite um `logger.error` com `f"{contexto}: {type(erro).__name__}: {resumo}"`, onde `resumo` é a primeira linha de `str(erro)` cortada em `MAX_ERRO_LOG = 300` caracteres; depois um `logger.debug(..., exc_info=erro)` com o traceback.

- [ ] **Passo 1: testes** (em `test_web_search.py`; `caplog.set_level(logging.INFO, logger="fluxo_financeiro")` nos dois primeiros, `logging.DEBUG` no terceiro)

```python
ERRO_GOOGLE = Exception("429 RESOURCE_EXHAUSTED.\n{'error': {'code': 429, 'details': [" + "x" * 2000 + "]}}")

@patch('fluxo_financeiro.tools.news.pesquisar_na_web')
def test_falha_da_busca_loga_uma_linha_curta(mock_pesquisa, caplog):
    """Test que a falha da busca vira uma linha de ERROR, sem traceback e sem o JSON do SDK."""
    mock_pesquisa.side_effect = ERRO_GOOGLE
    buscar_noticias_web.invoke("WEGE3")
    erros = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(erros) == 1
    msg = erros[0].getMessage()
    assert "buscar_noticias_web" in msg and "Exception: 429 RESOURCE_EXHAUSTED." in msg
    assert "\n" not in msg and len(msg) < 400
    assert all(r.exc_info is None for r in caplog.records)

@patch('fluxo_financeiro.tools.news.pesquisar_na_web')
def test_falha_da_busca_tem_traceback_em_debug(mock_pesquisa, caplog):
    """Test que, com LOG_LEVEL=DEBUG, o traceback completo continua no log."""
    # set_level(DEBUG); mesma chamada
    assert any(r.exc_info for r in caplog.records if r.levelname == "DEBUG")
```

E em `test_investigation.py`: `test_buscar_fatos_relevantes_erro_loga_uma_linha` com o mesmo `ERRO_GOOGLE` (copiado no arquivo) e as mesmas três asserções do primeiro teste, trocando o nome por `buscar_fatos_relevantes`.

- [ ] **Passo 2:** `uv run pytest tests/tools/test_web_search.py tests/tools/test_investigation.py -v -k "loga or debug"`. Esperado: FAIL (hoje há `exc_info` no registro de ERROR).
- [ ] **Passo 3:** implementar `registrar_falha_busca` e trocar os dois `logger.exception(...)` por `registrar_falha_busca("[tool] buscar_noticias_web falhou para '<query>'", e)` e `registrar_falha_busca("[tool] buscar_fatos_relevantes falhou para <ticker_base>", e)`. O texto devolvido ao agente (`"Erro ao ..."`) não muda. `web_search.py` passa a importar `logger` de `shared/utils`.
- [ ] **Passo 4:** `uv run pytest tests/ -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit**

```bash
git add fluxo_financeiro/tools tests/tools
git commit -m "fix: falha da busca na web vira uma linha de log, traceback só em DEBUG"
```

---

### Tarefa 3: Busca na web antes da NewsAPI no Analyzer

**Arquivos:**
- Modificar: `fluxo_financeiro/agents/analysts.py` (prompt vira a constante `ANALYZER_PROMPT`)
- Modificar: `fluxo_financeiro/tools/news.py` (docstrings de `buscar_noticias` e `buscar_noticias_web`)
- Modificar: `tests/agents/test_analysts.py`
- Modificar: `docs/arquitetura.md` (nó `A1`: `"analyzer_agent<br/>busca na web, NewsAPI como reserva"`), `docs/decisoes.md` (D44 no fim da "Parte 4 — Notícias", depois da D16; na D16, a frase "A regra 'NewsAPI primeiro, web como fallback' continua valendo." vira "A ordem foi invertida pela D44 (web primeiro)."; o item "NewsAPI quase não acha nada" das próximas decisões fica no estilo `~~...~~: feito (D44)`), `README.md:10` e `:41` (a ordem nova; sem a web, a NewsAPI continua como reserva)
- Local (sem commit): `.claude/docs/agents.md`, `.claude/docs/tools.md`

- [ ] **Passo 1: teste**

```python
from fluxo_financeiro.agents.analysts import ANALYZER_PROMPT

def test_analyzer_usa_web_antes_da_newsapi():
    """Test que o prompt manda a busca na web primeiro e deixa a NewsAPI como reserva."""
    assert ANALYZER_PROMPT.index("- buscar_noticias_web:") < ANALYZER_PROMPT.index("- buscar_noticias:")
```

Atualizar também a docstring de `test_analyzer_agent_tem_tools_de_noticias` para "Web Search (padrão) e NewsAPI (reserva)".

- [ ] **Passo 2:** `uv run pytest tests/agents/test_analysts.py -v`. Esperado: FAIL (`ImportError: ANALYZER_PROMPT`).
- [ ] **Passo 3:** extrair o prompt para `ANALYZER_PROMPT` e reescrever o bloco de ferramentas:
  - `buscar_noticias_web`: use primeiro. Traz o mais recente (empresa e setor) com as fontes.
  - `buscar_noticias`: use só se `buscar_noticias_web` der erro ou não trouxer nada relevante.

  Docstrings: `buscar_noticias_web` diz que é a busca padrão de notícias; `buscar_noticias` diz que é a alternativa quando a busca na web falha. O resto do prompt (tarefa do Supervisor, formato da resposta) fica igual.
- [ ] **Passo 4:** `uv run pytest tests/ -q`. Esperado: tudo passa.
- [ ] **Passo 5:** D44 em `decisoes.md`: "Analyzer busca na web primeiro, NewsAPI vira reserva". Por quê: no e2e a NewsAPI voltou vazia nas duas passagens e tudo caía no fallback, então a primeira busca de cada análise era desperdiçada. Custo: a web já rodava em quase toda análise; o consumo das 5.000 buscas grátis do mês quase não muda. Atualizar o diagrama, validar o bloco com o mermaid-cli e editar os dois arquivos locais de `.claude/docs/`.
- [ ] **Passo 6: commit**

```bash
git add fluxo_financeiro/agents/analysts.py fluxo_financeiro/tools/news.py tests/agents/test_analysts.py docs/ README.md
git commit -m "feat: analyzer busca na web primeiro e usa a NewsAPI como reserva"
```

---

### Tarefa 4: Limitações do Consolidador sem repetição e com o setor

**Arquivos:**
- Modificar: `fluxo_financeiro/agents/consolidator.py:22-23` (constante nova) e `:63-72` (ajuste das limitações)
- Testes: `tests/agents/test_consolidator.py`

**Interfaces:**
- Produz: `LIMITACAO_SEM_SETOR = "O contexto do setor não foi pesquisado."` em `agents/consolidator.py`.

- [ ] **Passo 1: testes** (usam a fixture `mock_llm`, o `HIST` e o `REL` que já existem)

```python
def test_consolidar_nao_repete_limitacoes(mock_llm):
    """Test que limitações iguais (a menos de espaços nas pontas) aparecem uma vez, na ordem."""
    mock_llm.with_structured_output.return_value.invoke.side_effect = lambda _m: REL.model_copy(
        update={"limitacoes": [LIMITACAO_SEM_DADOS + " ", "Sem fatos relevantes", "Sem fatos relevantes"]})
    lim = consolidar([HumanMessage("Analise VALE3")]).limitacoes
    assert lim == [LIMITACAO_SEM_DADOS, "Sem fatos relevantes", LIMITACAO_SEM_NOTICIAS]

def test_consolidar_aponta_setor_que_faltou(mock_llm):
    """Test que uma passagem só do Analyzer vira limitação de setor; zero ou duas, não."""
    uma = HIST[:4]  # pedido, YFinance, tarefa, 1 Analyzer
    assert LIMITACAO_SEM_SETOR in consolidar(uma).limitacoes
    assert consolidar(uma).contexto == REL.contexto  # o que o Analyzer trouxe continua
    assert LIMITACAO_SEM_SETOR not in consolidar(HIST).limitacoes
    sem_analyzer = consolidar([HumanMessage("Analise VALE3")]).limitacoes
    assert LIMITACAO_SEM_SETOR not in sem_analyzer and LIMITACAO_SEM_NOTICIAS in sem_analyzer
```

- [ ] **Passo 2:** `uv run pytest tests/agents/test_consolidator.py -v`. Esperado: os dois novos falham (`ImportError: LIMITACAO_SEM_SETOR`).
- [ ] **Passo 3:** em `consolidar()`, contar as mensagens com `name == "Analyzer"`; exatamente 1 acrescenta `LIMITACAO_SEM_SETOR`. Antes de gravar, `strip()` em cada limitação e remover repetidas mantendo a primeira ocorrência (`dict.fromkeys`). Limitações vazias depois do `strip()` saem.
- [ ] **Passo 4:** `uv run pytest tests/ -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit**

```bash
git add fluxo_financeiro/agents/consolidator.py tests/agents/test_consolidator.py
git commit -m "fix: consolidador não repete limitações e aponta a falta do setor"
```

---

### Tarefa 5: e2e confere o diagnóstico inteiro

**Arquivos:**
- Modificar: `scripts/e2e.py:79-87`
- Criar: `tests/scripts/test_e2e.py`

**Interfaces:**
- Produz: `conferir_diagnostico(diag: str, final: str) -> list[str]` em `scripts/e2e.py`, devolvendo as falhas (lista vazia = ok). Mensagens: `"diagnóstico sem as seções: <lista>"` (mantém a checagem de `SECOES_DIAGNOSTICO` no texto do Investigator) e `"o relatório final não traz o diagnóstico do Investigator na íntegra"` (quando `diag.strip()` não está em `final`).

- [ ] **Passo 1: testes.** `scripts/` não é pacote: carregar com `importlib.util.spec_from_file_location("e2e", <raiz>/scripts/e2e.py)`.

```python
DIAG = "- Causa: impairment\n- Natureza: pontual\n- Evidências: 3T26\n- Impacto: baixo"

def test_conferir_diagnostico_ok():
    """Test que diagnóstico completo e copiado na íntegra não gera falha."""
    assert e2e.conferir_diagnostico(DIAG, f"# Relatório\n## Diagnóstico da anomalia\n{DIAG}\n## Riscos") == []

def test_conferir_diagnostico_ignora_espacos_nas_pontas():
    """Test que o strip() do formatar_relatorio não vira falha."""
    assert e2e.conferir_diagnostico(DIAG + "\n\n", f"## Diagnóstico\n{DIAG}\n") == []

def test_conferir_diagnostico_resumido_falha():
    """Test que um relatório com as quatro palavras, mas sem o texto do Investigator, falha."""
    falhas = e2e.conferir_diagnostico(DIAG, "Causa, Natureza, Evidências e Impacto resumidos.")
    assert falhas == ["o relatório final não traz o diagnóstico do Investigator na íntegra"]

def test_conferir_diagnostico_sem_secao():
    """Test que diagnóstico sem uma seção ainda é acusado."""
    diag = DIAG.replace("- Impacto: baixo", "")
    assert "diagnóstico sem as seções: Impacto" in e2e.conferir_diagnostico(diag, diag)
```

- [ ] **Passo 2:** `uv run pytest tests/scripts/ -v`. Esperado: FAIL (`AttributeError: conferir_diagnostico`).
- [ ] **Passo 3:** implementar `conferir_diagnostico` e usá-la em `main()` no lugar das duas checagens por palavra; o `print` de "Diagnóstico:" continua mostrando "formato completo" ou as seções faltando.
- [ ] **Passo 4:** `uv run pytest tests/ -q`. Esperado: tudo passa.
- [ ] **Passo 5: commit**

```bash
git add scripts/e2e.py tests/scripts/test_e2e.py
git commit -m "test: e2e exige o diagnóstico do Investigator inteiro no relatório"
```

---

### Tarefa 6: Diagrama, nota do BCB e docs locais

**Arquivos:**
- Modificar: `docs/arquitetura.md:22`, `:43` e a última linha da tabela (`:59`)
- Modificar: `docs/decisoes.md` (D14)
- Local (sem commit): `CLAUDE.md`, `.claude/docs/tests.md`, `.claude/docs/architecture.md`, `.claude/docs/agents.md`

- [ ] **Passo 1:** diagrama: `S -->|"FINISH"| C` e `C -->|"aresta fixa: relatório em markdown + relatorio no state"| F(["Fim"])`. Tabela: `| — | Qualquer FINISH | Consolidador → fim | Router: FINISH sempre vai ao Consolidador (D41) |`. Rodar `grep -rn -i "aresta fixa" docs/arquitetura.md CLAUDE.md .claude/docs/` e alinhar todas as menções: a aresta fixa é Consolidador→END; Supervisor→Consolidador é condicional (o router troca FINISH por Consolidador). A D41 (`decisoes.md:306`) e o `.claude/docs/graph.md:91` já estão certos. Copiar o bloco para o scratchpad e validar: `npx -y @mermaid-js/mermaid-cli -i bloco.mmd -o bloco.png`. Esperado: PNG gerado, sem erro; conferir na imagem que o rótulo ficou na seta certa.
- [ ] **Passo 2:** D14: trocar a linha "**Estado:**" por "**Estado:** a tool existe e tem teste, mas nenhum agente a usa. A SELIC que o projeto usa vem de dentro do `calcular_metricas_risco` (D11). **Preciso revisar (02/11/2026):** registrar no YFinance, para a SELIC e o IPCA aparecerem no relatório, ou apagar a tool."
- [ ] **Passo 3: commit**

```bash
git add docs/arquitetura.md docs/decisoes.md
git commit -m "docs: rótulo da aresta fixa no diagrama e revisão pendente do indicador do BCB"
```

- [ ] **Passo 4 (local):** no `CLAUDE.md`, tirar das pendências "Os testes não bloqueiam rede", "A NewsAPI raramente acha artigos..." e "Quando a busca falha, `logger.exception`..."; trocar a linha do `busca_indicador_bcb` para apontar a revisão pendente da D14; atualizar a contagem de testes e citar o `pytest-socket` em "Testes". No `.claude/docs/tests.md`: contagem real (de `uv run pytest tests/ -q`), `tests/scripts/` e `test_rede_bloqueada.py` na árvore, e a nota de que a rede é bloqueada (`@pytest.mark.enable_socket` para liberar). No `architecture.md`/`agents.md`: ordem web → NewsAPI.

---

### Tarefa 7: Verificação final

- [ ] **Passo 1:** `uv run pytest tests/ -q`. Esperado: tudo passa, contagem igual à registrada no `tests.md`.
- [ ] **Passo 2:** `uv run python -c "from fluxo_financeiro import app; print(sorted(app.get_graph().nodes))"`. Esperado: os mesmos nós de antes.
- [ ] **Passo 3 (gasta ~US$ 0,035 no total, pedir ok ao usuário antes):**
  - `PYTHONIOENCODING=utf-8 uv run python scripts/e2e.py WEGE3 --espera-sem-investigator`. Esperado: código 0, e no log a primeira tool do Analyzer é `buscar_noticias_web`.
  - `PYTHONIOENCODING=utf-8 uv run python scripts/e2e.py VALE3 --espera-investigator`. Esperado: código 0. É o único teste real do `conferir_diagnostico`: o Consolidador copia `m.text`, o e2e lê `.content` e o `formatar_relatorio` faz `strip()`; se isso divergir, a checagem nova acusaria falha falsa em toda análise com anomalia.
- [ ] **Passo 4:** perguntar ao usuário se faz o merge no `master` com `--no-ff`.
