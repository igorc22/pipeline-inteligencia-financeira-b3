# Investigator Condicional — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar um agente Investigator condicional que o Supervisor ativa após detectar anomalias nos dados financeiros, produzindo diagnóstico causal em vez de apenas reportar números.

**Architecture:** Pipeline de 5 etapas onde Etapa 4 é condicional: após 2 passagens do Analyzer, o Supervisor avalia semanticamente se há anomalia que justifica investigação; se sim, roteia para `investigator_agent` com task específica; o Investigator faz multi-hop com 3 tools especializadas e retorna diagnóstico causal estruturado.

**Tech Stack:** LangChain `create_agent`, LangGraph `StateGraph`, yfinance `quarterly_financials`, NewsAPI, Anthropic Web Search (buscar_noticias_web existente).

---

## Mapa de Arquivos

| Ação | Arquivo | Responsabilidade |
|------|---------|-----------------|
| Modificar | `fluxo_financeiro/shared/types.py` | Adicionar "Investigator" ao Literal de RouteDecision |
| **Criar** | `notebooks/fluxo_financeiro/08_investigator_tools.ipynb` | Protótipo e validação das tools de investigação |
| **Criar** | `fluxo_financeiro/tools/investigation.py` | buscar_historico_trimestral + buscar_fatos_relevantes |
| **Criar** | `tests/tools/test_investigation.py` | Testes unitários das tools com mock |
| **Criar** | `notebooks/fluxo_financeiro/09_investigator_agent.ipynb` | Protótipo do agent com multi-hop real |
| **Criar** | `fluxo_financeiro/agents/investigators.py` | investigator_agent com 3 tools |
| **Criar** | `tests/agents/test_investigators.py` | Testes do agente com mock |
| Modificar | `fluxo_financeiro/graph/supervisor.py` | Guard Investigator + Etapa 4 no prompt |
| Modificar | `fluxo_financeiro/graph/graph.py` | investigator_node + edge + router |
| Modificar | `tests/graph/test_supervisor.py` | Testes para guard Investigator e router |

---

## Task 1: Atualizar tipos — adicionar "Investigator" ao RouteDecision

**Files:**
- Modify: `fluxo_financeiro/shared/types.py:21`

- [X] **Step 1: Abrir o arquivo e localizar RouteDecision**

  Em `fluxo_financeiro/shared/types.py`, linha 21, está:
  ```python
  next_agent: Literal["YFinance", "Analyzer", "FINISH"] = Field(
  ```

- [X] **Step 2: Adicionar "Investigator" ao Literal**

  Substituir a linha 21 por:
  ```python
  next_agent: Literal["YFinance", "Analyzer", "Investigator", "FINISH"] = Field(
  ```

  O Field description na linha seguinte também precisa mencionar "Investigator":
  ```python
      description="""
      Decida o próximo passo do fluxo:
      - 'YFinance': Se faltam dados financeiros ou se o Analyzer pedir mais informações para concluir a tarefa.
      - 'Analyzer': Se os dados foram coletados com sucesso e estão prontos para serem analisados.
      - 'Investigator': Se há anomalia financeira clara que precisa de diagnóstico causal (queda abrupta de lucro, impairment suspeito, dívida inexplicável).
      - 'FINISH': Se o usuário já tem a resposta final e completa, ou se os agentes não conseguem encontrar o dado após tentarem.
      """
  ```

- [X] **Step 3: Verificar que import funciona**

  ```bash
  python -c "from fluxo_financeiro.shared.types import RouteDecision; r = RouteDecision(reasoning='test', next_agent='Investigator'); print(r)"
  ```

  Esperado: objeto RouteDecision impresso sem erro de validação.

---

## Task 2: Criar notebook 08 — Prototipagem das Tools de Investigação

**Files:**
- Create: `notebooks/fluxo_financeiro/08_investigator_tools.ipynb`

Este notebook prototipa as duas novas tools antes de movê-las para o pacote.
Crie o arquivo com as células abaixo (use Jupyter ou crie o JSON diretamente).

- [x] **Step 1: Criar o notebook com as células de protótipo**

  Estrutura do notebook (cada item é uma célula markdown + código):

  **Célula 1 (Markdown)**:
  ```markdown
  # 08 — Investigator Tools: Prototipagem
  
  Este notebook explora as ferramentas de investigação causal que serão usadas pelo `investigator_agent`.
  
  ## Contexto Financeiro: Por que investigar anomalias?
  
  **Fato Relevante**: Comunicado formal obrigatório pela CVM quando empresa tem evento material
  (impairments, fusões, reestruturações). É a "confissão oficial" de um evento extraordinário.
  
  **Impairment**: Redução contábil do valor de um ativo quando ele vale menos do que está registrado
  nos livros. Ex: Vale comprou ativos de níquel a R$10B mas preço caiu — precisa "escrever off" a diferença.
  
  **Histórico Trimestral**: Comparar Q atual com últimos 8 trimestres revela se queda é:
  - **Pontual**: só este trimestre, padrão restante é normal → evento one-off
  - **Estrutural**: queda progressiva → deterioração real do negócio
  - **Cíclico**: sazonalidade recorrente → esperado pelo mercado
  ```

  **Célula 2 (Código)** — Setup:
  ```python
  import sys
  sys.path.insert(0, '../..')
  import yfinance as yf
  import pandas as pd
  from datetime import datetime, timedelta
  ```

  **Célula 3 (Markdown)**:
  ```markdown
  ## Tool 1: buscar_historico_trimestral
  Usa `yfinance.quarterly_financials` para retornar Net Income, Receita e Lucro Bruto por trimestre.
  ```

  **Célula 4 (Código)** — Protótipo da tool 1:
  ```python
  def buscar_historico_trimestral_proto(ticker: str, n_trimestres: int = 8) -> str:
      if not ticker.endswith('.SA'):
          ticker += '.SA'
      
      acao = yf.Ticker(ticker)
      df = acao.quarterly_financials
      
      if df is None or df.empty:
          return f"Dados trimestrais não encontrados para {ticker}."
      
      df = df.sort_index(axis=1, ascending=False)
      colunas = df.columns[:n_trimestres]
      
      linhas_interesse = ['Net Income', 'Total Revenue', 'Gross Profit']
      df_filtrado = df.loc[df.index.isin(linhas_interesse), colunas]
      
      resultado = f"Histórico Trimestral de {ticker} (últimos {len(colunas)} trimestres):\n\n"
      resultado += f"{'Métrica':<20}"
      for col in colunas:
          resultado += f"{str(col.date()):<14}"
      resultado += "\n" + "-" * (20 + 14 * len(colunas)) + "\n"
      
      for linha in linhas_interesse:
          if linha in df_filtrado.index:
              resultado += f"{linha:<20}"
              for col in colunas:
                  val = df_filtrado.loc[linha, col]
                  resultado += f"{val/1e9:>10.2f}B  " if not pd.isna(val) else f"{'N/A':>10}   "
              resultado += "\n"
      
      return resultado
  
  # Testar com VALE3 — empresa com histórico rico
  print(buscar_historico_trimestral_proto("VALE3"))
  ```

  **Célula 5 (Markdown)**:
  ```markdown
  ## Tool 2: buscar_fatos_relevantes
  Usa Anthropic Web Search para buscar fatos relevantes e eventos corporativos em tempo real.
  Mais eficaz que NewsAPI para queries específicas em português sobre o mercado brasileiro.
  ```

  **Célula 6 (Código)** — Protótipo da tool 2:
  ```python
  import anthropic
  from fluxo_financeiro.shared.config import MODEL
  
  def buscar_fatos_relevantes_proto(ticker: str) -> str:
      ticker_base = ticker.replace('.SA', '')
      
      client = anthropic.Anthropic()
      response = client.messages.create(
          model=MODEL,
          max_tokens=1024,
          messages=[{
              'role': 'user',
              'content': (
                  f'Busque fatos relevantes, impairments, reestruturações e eventos '
                  f'corporativos extraordinários de {ticker_base} nos últimos 6 meses. '
                  f'Foque em eventos que expliquem variações atípicas nos resultados '
                  f'financeiros. Seja conciso (max 3 parágrafos).'
              )
          }],
          tools=[{'type': 'web_search_20250305', 'name': 'web_search'}]
      )
      textos = [block.text for block in response.content if block.type == 'text']
      if not textos:
          return f'Nenhum fato relevante encontrado para: {ticker_base}'
      return f'Fatos relevantes e eventos corporativos de {ticker_base}:\n\n' + '\n'.join(textos)
  
  # Testar com ticker conhecido
  print(buscar_fatos_relevantes_proto("VALE3"))
  ```

  **Célula 7 (Markdown)**:
  ```markdown
  ## Validação: buscar_noticias_web (existente) para contexto externo
  Esta tool já existe no pacote e será reutilizada pelo Investigator.
  ```

  **Célula 8 (Código)**:
  ```python
  from fluxo_financeiro.tools.news import buscar_noticias_web
  
  # Testar busca de contexto externo — commodity, macro
  resultado = buscar_noticias_web.invoke("preço níquel 2025 China demanda")
  print(resultado[:500])
  ```

- [ ] **Step 2: Executar o notebook e verificar outputs**

  Abrir o notebook no Jupyter e executar todas as células. Verificar:
  - `buscar_historico_trimestral_proto("VALE3")` retorna tabela com trimestres
  - `buscar_fatos_relevantes_proto("VALE3")` retorna artigos (ou mensagem de nenhum resultado)
  - `buscar_noticias_web.invoke(...)` retorna texto de contexto

  Ajustar queries se necessário antes de prosseguir para a implementação.

---

## Task 3: Implementar `tools/investigation.py` (TDD)

**Files:**
- Create: `tests/tools/test_investigation.py`
- Create: `fluxo_financeiro/tools/investigation.py`

- [x] **Step 1: Escrever os testes primeiro**

  Criar `tests/tools/test_investigation.py`:

  ```python
  from unittest.mock import patch, MagicMock
  import pandas as pd
  from fluxo_financeiro.tools.investigation import buscar_historico_trimestral, buscar_fatos_relevantes


  # ---------------------------------------------------------------------------
  # buscar_historico_trimestral
  # ---------------------------------------------------------------------------

  def _df_trimestral_fake(n=4):
      dates = pd.date_range('2024-01-01', periods=n, freq='QE')
      return pd.DataFrame(
          [[1e9] * n, [10e9] * n, [3e9] * n],
          index=['Net Income', 'Total Revenue', 'Gross Profit'],
          columns=dates
      )


  @patch('fluxo_financeiro.tools.investigation.yf.Ticker')
  def test_buscar_historico_trimestral_retorna_string(mock_ticker):
      """Test que retorna string formatada com métricas trimestrais."""
      mock_instance = MagicMock()
      mock_ticker.return_value = mock_instance
      mock_instance.quarterly_financials = _df_trimestral_fake()

      result = buscar_historico_trimestral.invoke("VALE3")

      assert isinstance(result, str)
      assert "VALE3.SA" in result
      assert "Net Income" in result
      assert "Total Revenue" in result


  @patch('fluxo_financeiro.tools.investigation.yf.Ticker')
  def test_buscar_historico_trimestral_adiciona_sa(mock_ticker):
      """Test que .SA é adicionado automaticamente ao ticker."""
      mock_instance = MagicMock()
      mock_ticker.return_value = mock_instance
      mock_instance.quarterly_financials = _df_trimestral_fake()

      buscar_historico_trimestral.invoke("VALE3")

      mock_ticker.assert_called_once_with("VALE3.SA")


  @patch('fluxo_financeiro.tools.investigation.yf.Ticker')
  def test_buscar_historico_trimestral_sem_dados(mock_ticker):
      """Test que retorna mensagem amigável quando yfinance não tem dados."""
      mock_instance = MagicMock()
      mock_ticker.return_value = mock_instance
      mock_instance.quarterly_financials = pd.DataFrame()

      result = buscar_historico_trimestral.invoke("FAKE99")

      assert "não encontrados" in result.lower() or "não encontrado" in result.lower()


  @patch('fluxo_financeiro.tools.investigation.yf.Ticker')
  def test_buscar_historico_trimestral_erro_yfinance(mock_ticker):
      """Test que captura exceção do yfinance e retorna string de erro."""
      mock_ticker.side_effect = Exception("network error")

      result = buscar_historico_trimestral.invoke("VALE3")

      assert "Erro" in result


  # ---------------------------------------------------------------------------
  # buscar_fatos_relevantes
  # ---------------------------------------------------------------------------

  @patch('fluxo_financeiro.tools.investigation.anthropic.Anthropic')
  def test_buscar_fatos_relevantes_retorna_conteudo(mock_anthropic_class):
      """Test que retorna conteúdo quando web search encontra resultados."""
      mock_client = MagicMock()
      mock_anthropic_class.return_value = mock_client

      mock_block = MagicMock()
      mock_block.type = 'text'
      mock_block.text = 'Vale registra impairment de R$4B em ativos de níquel.'
      mock_client.messages.create.return_value.content = [mock_block]

      result = buscar_fatos_relevantes.invoke("VALE3")

      assert isinstance(result, str)
      assert "Vale registra impairment" in result


  @patch('fluxo_financeiro.tools.investigation.anthropic.Anthropic')
  def test_buscar_fatos_relevantes_sem_resultados(mock_anthropic_class):
      """Test que retorna mensagem amigável quando web search não retorna texto."""
      mock_client = MagicMock()
      mock_anthropic_class.return_value = mock_client
      mock_client.messages.create.return_value.content = []

      result = buscar_fatos_relevantes.invoke("DESCONHECIDO")

      assert "Nenhum" in result or "nenhum" in result


  @patch('fluxo_financeiro.tools.investigation.anthropic.Anthropic')
  def test_buscar_fatos_relevantes_erro_api(mock_anthropic_class):
      """Test que captura exceção e retorna string de erro."""
      mock_anthropic_class.side_effect = Exception("API timeout")

      result = buscar_fatos_relevantes.invoke("VALE3")

      assert "Erro" in result
  ```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

  ```bash
  cd "C:\Users\User\Documents\Projeto - Agentes Investimento\estudo-arquitetura-coordenador-langchain"
  pytest tests/tools/test_investigation.py -v
  ```

  Esperado: `ImportError` porque o módulo ainda não existe.

- [x] **Step 3: Criar `fluxo_financeiro/tools/investigation.py`**

  ```python
  import anthropic
  import pandas as pd
  import yfinance as yf
  from langchain_core.tools import tool

  from fluxo_financeiro.shared.config import MODEL
  from fluxo_financeiro.shared.utils import logger


  @tool
  def buscar_historico_trimestral(ticker: str) -> str:
      """
      Retorna histórico de resultados trimestrais de uma ação da B3 (últimos 8 trimestres).
      Inclui Net Income, Receita Total e Lucro Bruto por trimestre via yfinance.
      Use para detectar se queda de lucro é pontual (evento isolado) ou estrutural
      (padrão recorrente de vários trimestres consecutivos).
      Compare Q atual com Qs anteriores para identificar a anomalia no histórico.
      Ticker sem sufixo é aceito (ex: VALE3) — o .SA é adicionado automaticamente.
      """
      if not ticker.endswith('.SA'):
          ticker += '.SA'

      logger.info(f"[tool] buscar_historico_trimestral: ticker={ticker}")
      try:
          acao = yf.Ticker(ticker)
          df = acao.quarterly_financials

          if df is None or df.empty:
              logger.warning(f"[tool] buscar_historico_trimestral: sem dados para {ticker}")
              return f"Dados trimestrais não encontrados para {ticker}."

          df = df.sort_index(axis=1, ascending=False)
          n_trimestres = 8
          colunas = df.columns[:n_trimestres]

          linhas_interesse = ['Net Income', 'Total Revenue', 'Gross Profit']
          df_filtrado = df.loc[df.index.isin(linhas_interesse), colunas]

          resultado = f"Histórico Trimestral de {ticker} (últimos {len(colunas)} trimestres):\n\n"
          resultado += f"{'Métrica':<20}"
          for col in colunas:
              resultado += f"{str(col.date()):<14}"
          resultado += "\n" + "-" * (20 + 14 * len(colunas)) + "\n"

          for linha in linhas_interesse:
              if linha in df_filtrado.index:
                  resultado += f"{linha:<20}"
                  for col in colunas:
                      val = df_filtrado.loc[linha, col]
                      resultado += f"{val/1e9:>10.2f}B  " if not pd.isna(val) else f"{'N/A':>10}   "
                  resultado += "\n"

          logger.info(f"[tool] buscar_historico_trimestral: ok — {len(colunas)} trimestres")
          return resultado

      except Exception as e:
          logger.exception(f"[tool] buscar_historico_trimestral falhou para {ticker}")
          return f"Erro ao buscar histórico trimestral de {ticker}: {e}"


  @tool
  def buscar_fatos_relevantes(ticker: str) -> str:
      """
      Busca fatos relevantes e eventos corporativos formais de uma empresa da B3 via web search.
      Inclui: impairments, reestruturações, provisões, eventos extraordinários.
      Use quando um número financeiro parece atípico e você precisa identificar
      se houve evento corporativo específico que justifique o resultado fora do padrão.
      Usa Anthropic Web Search para resultados em tempo real.
      Ticker sem sufixo é aceito (ex: VALE3) — o .SA é adicionado automaticamente.
      """
      if not ticker.endswith('.SA'):
          ticker += '.SA'

      ticker_base = ticker.replace('.SA', '')
      logger.info(f"[tool] buscar_fatos_relevantes: ticker={ticker_base}")

      try:
          client = anthropic.Anthropic()
          response = client.messages.create(
              model=MODEL,
              max_tokens=1024,
              messages=[{
                  'role': 'user',
                  'content': (
                      f'Busque fatos relevantes, impairments, reestruturações e eventos '
                      f'corporativos extraordinários de {ticker_base} nos últimos 6 meses. '
                      f'Foque em eventos que expliquem variações atípicas nos resultados '
                      f'financeiros. Seja conciso (max 3 parágrafos).'
                  )
              }],
              tools=[{'type': 'web_search_20250305', 'name': 'web_search'}]
          )
          textos = [block.text for block in response.content if block.type == 'text']
          if not textos:
              logger.warning(f"[tool] buscar_fatos_relevantes: nenhum resultado para {ticker_base}")
              return f'Nenhum fato relevante encontrado para: {ticker_base}'
          logger.info(f"[tool] buscar_fatos_relevantes: ok ({len(textos)} blocos de texto)")
          return f'Fatos relevantes e eventos corporativos de {ticker_base}:\n\n' + '\n'.join(textos)

      except Exception as e:
          logger.exception(f"[tool] buscar_fatos_relevantes falhou para {ticker_base}")
          return f"Erro ao buscar fatos relevantes para {ticker_base}: {e}"
  ```

- [x] **Step 4: Rodar os testes e confirmar que passam**

  ```bash
  pytest tests/tools/test_investigation.py -v
  ```

  Esperado: todos os 7 testes PASS.

---

## Task 4: Criar notebook 09 — Prototipagem do Investigator Agent

**Files:**
- Create: `notebooks/fluxo_financeiro/09_investigator_agent.ipynb`

- [x] **Step 1: Criar o notebook**

  Estrutura (células):

  **Célula 1 (Markdown)**:
  ```markdown
  # 09 — Investigator Agent: Prototipagem
  
  Testa o `investigator_agent` com as tools implementadas.
  Valida: multi-hop de investigação, stopping condition e formato de conclusão.
  
  ## Conceito: Multi-Hop Investigation
  
  O Investigator não faz uma busca e para — ele encadeia buscas conforme o que encontra.
  Isso é chamado de "multi-hop" porque cada "salto" (hop) usa o resultado anterior como
  contexto para formular a próxima query. Similar a como um analista real investigaria.
  
  Hop 1: "O que aconteceu com VALE3 no Q3 2025?" → encontra impairment de níquel
  Hop 2: "Preço do níquel 2025" → confirma queda de 30% na commodity
  Hop 3: histórico trimestral → confirma Q3 é o único trimestre afetado
  ```

  **Célula 2 (Código)** — Setup:
  ```python
  import sys
  sys.path.insert(0, '../..')
  from langchain_core.messages import HumanMessage
  from langchain_anthropic import ChatAnthropic
  from langchain.agents import create_agent
  from fluxo_financeiro.shared.config import MODEL
  from fluxo_financeiro.tools.investigation import buscar_historico_trimestral, buscar_fatos_relevantes
  from fluxo_financeiro.tools.news import buscar_noticias_web
  ```

  **Célula 3 (Código)** — Criar o agente:
  ```python
  llm = ChatAnthropic(model=MODEL, temperature=0)
  
  INVESTIGATOR_PROMPT = """Você é um investigador financeiro especializado em diagnóstico causal.
  
  Você receberá no histórico uma tarefa específica descrevendo a anomalia a investigar.
  Sua missão: descobrir o PORQUÊ da anomalia, não descrever o QUÊ.
  
  QUANDO USAR CADA FERRAMENTA:
  - buscar_fatos_relevantes: Use primeiro. Encontra eventos corporativos formais (impairments, provisões).
  - buscar_historico_trimestral: Compare o resultado atual com os 8 trimestres anteriores.
  - buscar_noticias_web: Contexto externo livre (commodities, macro, câmbio, setor).
  
  PROCESSO:
  1. Leia a tarefa de investigação
  2. Comece com buscar_fatos_relevantes
  3. Use buscar_historico_trimestral para contextualizar no histórico
  4. Se necessário, use buscar_noticias_web para causas externas
  5. Após cada busca: "Tenho contexto suficiente para explicar a causa?"
  6. Quando tiver a causa, produza a conclusão
  
  FORMATO DA CONCLUSÃO:
  - Causa identificada: [explicação objetiva]
  - Natureza do evento: [pontual / estrutural / cíclico]
  - Evidências: [fonte 1, fonte 2...]
  - Impacto no investimento: [o que isso muda na análise]
  
  Máximo 4 buscas. Se não encontrar causa clara, relate honestamente."""
  
  investigator_agent_proto = create_agent(
      model=llm,
      tools=[buscar_historico_trimestral, buscar_fatos_relevantes, buscar_noticias_web],
      system_prompt=INVESTIGATOR_PROMPT,
  )
  ```

  **Célula 4 (Markdown)**:
  ```markdown
  ## Teste: Investigar anomalia de VALE3
  Simula o contexto que o Supervisor passaria ao Investigator via task_for_agent.
  ```

  **Célula 5 (Código)** — Testar com caso real:
  ```python
  # Simula o task_for_agent que o Supervisor passaria
  task_anomalia = HumanMessage(
      content="""Investigue a seguinte anomalia identificada na análise de VALE3:
      
  - Lucro líquido caiu significativamente em relação ao trimestre anterior
  - Piotroski F-Score caiu vs período anterior
  
  Determine se é evento pontual (impairment, one-off) ou deterioração estrutural do negócio.
  Foque no que causou essa queda específica.""",
      name="Supervisor"
  )
  
  mensagens_contexto = [
      HumanMessage(content="Analise VALE3"),
      HumanMessage(content="[dados do YFinance aqui — piotroski 5/9, lucro caiu]", name="YFinance"),
      task_anomalia
  ]
  
  response = investigator_agent_proto.invoke({"messages": mensagens_contexto})
  print(response["messages"][-1].content)
  ```

  **Célula 6 (Markdown)**:
  ```markdown
  ## Verificações
  Antes de mover para o pacote, confirme:
  - [ ] O agente faz pelo menos 2 buscas (multi-hop)
  - [ ] A conclusão tem a estrutura: Causa, Natureza, Evidências, Impacto
  - [ ] O agente para antes de 4 buscas se encontrou contexto suficiente
  - [ ] Não entra em loop
  ```

- [ ] **Step 2: Executar o notebook e validar o output do agent**

  O agente deve produzir resposta com: causa identificada, natureza (pontual/estrutural/cíclico), evidências e impacto. Se o formato estiver errado, ajuste o system prompt antes de continuar.

---

## Task 5: Implementar `agents/investigators.py` (TDD)

**Files:**
- Create: `tests/agents/test_investigators.py`
- Create: `fluxo_financeiro/agents/investigators.py`

- [x] **Step 1: Escrever os testes primeiro**

  Criar `tests/agents/test_investigators.py`:

  ```python
  from fluxo_financeiro.agents.investigators import investigator_agent


  def test_investigator_agent_existe():
      """Test que o investigator_agent foi inicializado corretamente."""
      assert investigator_agent is not None


  def test_investigator_agent_tem_tools():
      """Test que o agente tem as 3 tools esperadas."""
      tool_names = [t.name for t in investigator_agent.tools]
      assert "buscar_historico_trimestral" in tool_names
      assert "buscar_fatos_relevantes" in tool_names
      assert "buscar_noticias_web" in tool_names
  ```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

  ```bash
  pytest tests/agents/test_investigators.py -v
  ```

  Esperado: `ImportError` porque o módulo ainda não existe.

- [x] **Step 3: Criar `fluxo_financeiro/agents/investigators.py`**

  ```python
  from langchain_anthropic import ChatAnthropic
  from langchain.agents import create_agent
  from fluxo_financeiro.shared.config import MODEL
  from fluxo_financeiro.tools.investigation import buscar_historico_trimestral, buscar_fatos_relevantes
  from fluxo_financeiro.tools.news import buscar_noticias_web

  llm = ChatAnthropic(model=MODEL, temperature=0)

  INVESTIGATOR_PROMPT = """Você é um investigador financeiro especializado em diagnóstico causal.

  Você receberá no histórico uma tarefa específica descrevendo a anomalia a investigar
  (ex: "Investigue a queda de 62% no lucro da WEGE3 no último trimestre").

  Sua missão: descobrir o PORQUÊ da anomalia, não descrever o QUÊ.

  QUANDO USAR CADA FERRAMENTA:
  - buscar_fatos_relevantes: Use primeiro. Encontra eventos corporativos formais (impairments,
    reestruturações, provisões) que explicam números atípicos.
  - buscar_historico_trimestral: Compare o resultado atual com os 8 trimestres anteriores.
    Identifica se a queda é pontual (isolada) ou estrutural (recorrente).
  - buscar_noticias_web: Contexto externo livre — preços de commodities, macro, câmbio, setor,
    concorrentes. Use quando a causa pode ser externa ao negócio.

  PROCESSO:
  1. Leia a tarefa de investigação no histórico (mensagem do Supervisor)
  2. Comece com buscar_fatos_relevantes para identificar eventos corporativos
  3. Use buscar_historico_trimestral para contextualizar no padrão histórico
  4. Se necessário, use buscar_noticias_web para causas externas
  5. Após cada busca, avalie: "Tenho contexto suficiente para explicar a causa?"
  6. Quando tiver a causa identificada, produza sua conclusão

  FORMATO DA CONCLUSÃO:
  - Causa identificada: [explicação objetiva]
  - Natureza do evento: [pontual / estrutural / cíclico]
  - Evidências: [fonte 1, fonte 2...]
  - Impacto no investimento: [o que isso muda na análise]

  Máximo 4 buscas. Se não encontrar causa clara, relate isso honestamente."""

  investigator_agent = create_agent(
      model=llm,
      tools=[buscar_historico_trimestral, buscar_fatos_relevantes, buscar_noticias_web],
      system_prompt=INVESTIGATOR_PROMPT,
  )
  ```

- [x] **Step 4: Rodar os testes e confirmar que passam**

  ```bash
  pytest tests/agents/test_investigators.py -v
  ```

  Esperado: 2 testes PASS.

---

## Task 6: Atualizar `graph/supervisor.py` — Etapa 4 condicional

**Files:**
- Modify: `fluxo_financeiro/graph/supervisor.py`
- Modify: `tests/graph/test_supervisor.py`

- [x] **Step 1: Adicionar testes para os novos comportamentos**

  Adicionar ao final de `tests/graph/test_supervisor.py`:

  ```python
  def test_supervisor_guard_investigator_retorna_finish():
      """Test que se Investigator já existe no histórico, supervisor retorna FINISH."""
      state: MessagesState = {
          "messages": [
              HumanMessage(content="Analise VALE3"),
              HumanMessage(content="dados...", name="YFinance"),
              HumanMessage(content="analise 1...", name="Analyzer"),
              HumanMessage(content="analise 2...", name="Analyzer"),
              HumanMessage(content="causa identificada...", name="Investigator"),
          ],
          "next_agent": "Analyzer",
          "loop_count": 4,
          "supervisor_reasoning": ""
      }
      result = supervisor_node(state)
      assert result["next_agent"] == "FINISH"


  def test_router_investigator():
      """Test que router retorna 'Investigator' quando next_agent é Investigator."""
      state: MessagesState = {
          "messages": [HumanMessage(content="test")],
          "next_agent": "Investigator",
          "loop_count": 3,
          "supervisor_reasoning": ""
      }
      assert router(state) == "Investigator"
  ```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

  ```bash
  pytest tests/graph/test_supervisor.py::test_supervisor_guard_investigator_retorna_finish -v
  pytest tests/graph/test_supervisor.py::test_router_investigator -v
  ```

  Esperado: `test_supervisor_guard_investigator_retorna_finish` FAIL (guard não existe ainda), `test_router_investigator` PASS (router já retorna qualquer string que não seja FINISH).

- [x] **Step 3: Atualizar `fluxo_financeiro/graph/supervisor.py`**

  Adicionar o guard do Investigator logo após o guard do YFinance (linha 28, após o return do guard YFinance→Analyzer). Também atualizar o system prompt.

  **Novo guard** (inserir entre a linha 28 e a linha 30 do arquivo atual):
  ```python
      # Guard determinístico: se Investigator já concluiu → FINISH
      has_investigator = any(
          isinstance(m, HumanMessage) and getattr(m, 'name', '') == 'Investigator'
          for m in state.get("messages", [])
      )
      if has_investigator:
          logger.info("[supervisor] guard: Investigator concluiu → FINISH")
          return {"next_agent": "FINISH", "loop_count": 1}
  ```

  **System prompt atualizado** — substituir a Etapa 4 atual pelo bloco abaixo (trocar a string `system_prompt` completa):

  ```python
  system_prompt = """Você é um coordenador de pesquisa financeira. Você orquestra agentes em múltiplas passagens, cada uma com uma tarefa específica.

      COMO LER O HISTÓRICO:
      - Mensagens com name='YFinance': dados financeiros coletados (preço, histórico, métricas)
      - Mensagens com name='Analyzer': pesquisas já realizadas pelo analista
      - Mensagens com name='Supervisor': tarefas que você mesmo já atribuiu em turnos anteriores
      - Mensagens com name='Investigator': diagnóstico causal já produzido (se presente, pipeline encerrou)

      PIPELINE DE PESQUISA — siga esta ordem rigorosamente:
      Etapa 1 — Dados financeiros: Se não há mensagem do YFinance → rotear para 'YFinance'.
      Etapa 2 — Notícias da empresa: Se há YFinance mas nenhuma mensagem do Analyzer → rotear para 'Analyzer' (já tratado automaticamente pelo guard).
      Etapa 3 — Contexto do setor: Se há exatamente 1 mensagem do Analyzer E nenhuma mensagem do Supervisor menciona "setor" → rotear para 'Analyzer' com task_for_agent focado no setor da empresa identificada nos dados.
      Etapa 4 — Investigação condicional: Se já há 2 ou mais mensagens do Analyzer:
          Leia o contexto completo e pergunte: "Um investidor ficaria com dúvida de POR QUE esse número aconteceu?"
          Se SIM → next_agent: 'Investigator', task_for_agent: descrição precisa da anomalia e o que investigar
          Se NÃO → next_agent: 'FINISH'

      COMO CONTAR MENSAGENS DO ANALYZER:
      Conte quantas mensagens têm name='Analyzer' no histórico. Se for 1, a etapa 3 (contexto setorial) ainda não foi feita.

      COMO FORMULAR task_for_agent NA ETAPA 3:
      - Identifique o setor da empresa pelo ticker (ex: VALE3 → mineração/commodities, WEGE3 → automação industrial, PETR4 → petróleo e gás, ITUB4 → bancário)
      - Formule: 'Busque informações sobre o setor de [SETOR] e o posicionamento da [EMPRESA] ([TICKER]) nesse setor. Foque em tendências, concorrentes principais e fatores macroeconômicos relevantes.'

      COMO FORMULAR task_for_agent NA ETAPA 4 (Investigator):
      - Identifique a anomalia mais grave nos dados (maior queda de lucro, maior aumento de dívida, score baixo)
      - Formule: 'Investigue a seguinte anomalia identificada na análise de [TICKER]: [descreva a anomalia com números]. Determine se é evento pontual (impairment, one-off) ou deterioração estrutural.'

      PREVENÇÃO DE LOOP (CRÍTICO):
      - Se o Analyzer não consegue dados após 2 tentativas, escolha 'FINISH'.
      - Nunca volte para YFinance se ele já reportou que não encontrou dados.
      - Se loop_count >= 5, sempre escolha 'FINISH'."""
  ```

- [x] **Step 4: Rodar os testes e confirmar que passam**

  ```bash
  pytest tests/graph/test_supervisor.py -v
  ```

  Esperado: todos os testes PASS (incluindo os novos).

---

## Task 7: Atualizar `graph/graph.py` — nó e edge do Investigator

**Files:**
- Modify: `fluxo_financeiro/graph/graph.py`

- [x] **Step 1: Adicionar import do investigator_agent**

  No topo de `fluxo_financeiro/graph/graph.py`, após a linha de import do `analyzer_agent`:
  ```python
  from fluxo_financeiro.agents.investigators import investigator_agent
  ```

- [x] **Step 2: Adicionar a função `investigator_node`**

  Após a função `analyzer_node` (linha 24), adicionar:
  ```python
  def investigator_node(state: MessagesState):
      logger.info(f"[node] Investigator: invocando agente ({len(state['messages'])} msgs)")
      response = investigator_agent.invoke({"messages": state["messages"]})
      last_message = response["messages"][-1]
      logger.info(f"[node] Investigator: resposta recebida ({len(last_message.content)} chars)")
      return {"messages": [HumanMessage(content=last_message.content, name="Investigator")]}
  ```

- [x] **Step 3: Registrar nó e edge no workflow**

  Após `workflow.add_node("Analyzer", analyzer_node)` (linha 31), adicionar:
  ```python
  workflow.add_node("Investigator", investigator_node)
  ```

  Após `workflow.add_edge("Analyzer", "Supervisor")` (linha 37), adicionar:
  ```python
  workflow.add_edge("Investigator", "Supervisor")
  ```

- [x] **Step 4: Verificar que o grafo compila corretamente**

  ```bash
  python -c "from fluxo_financeiro import app; print('grafo compilado ok')"
  ```

  Esperado: `grafo compilado ok` sem erros.

---

## Task 8: Verificação End-to-End

**Files:** nenhum novo

- [x] **Step 1: Rodar toda a suite de testes**

  ```bash
  cd "C:\Users\User\Documents\Projeto - Agentes Investimento\estudo-arquitetura-coordenador-langchain"
  pytest tests/ -v
  ```

  Esperado: todos os testes PASS.

- [ ] **Step 2: Testar com ticker que deve ativar o Investigator (anomalia presente)**

  ```bash
  python -c "
  from langchain_core.messages import HumanMessage
  from fluxo_financeiro import app
  result = app.invoke({'messages': [HumanMessage('Analise VALE3')]})
  msgs = result['messages']
  print('=== MENSAGENS NO HISTÓRICO ===')
  for m in msgs:
      name = getattr(m, 'name', 'User')
      print(f'[{name}]: {m.content[:100]}...')
  print()
  print('=== RESPOSTA FINAL ===')
  print(msgs[-1].content)
  print()
  print('Loops:', result['loop_count'])
  names = [getattr(m, 'name', '') for m in msgs]
  print('Investigator ativado:', 'Investigator' in names)
  "
  ```

  Verificar: o histórico contém uma mensagem com `name='Investigator'` e a resposta final inclui a seção de diagnóstico causal.

- [ ] **Step 3: Testar com ticker de empresa estável (sem anomalia esperada)**

  ```bash
  python -c "
  from langchain_core.messages import HumanMessage
  from fluxo_financeiro import app
  result = app.invoke({'messages': [HumanMessage('Analise WEGE3')]})
  msgs = result['messages']
  names = [getattr(m, 'name', '') for m in msgs]
  print('Investigator ativado:', 'Investigator' in names)
  print('Loops:', result['loop_count'])
  "
  ```

  Verificar: `Investigator ativado: False` (Supervisor decide que não há anomalia grave o suficiente).

---

## Critérios de Sucesso

- [ ] `pytest tests/ -v` — todos os testes passam
- [ ] Ticker com anomalia → `Investigator` presente no histórico de mensagens
- [ ] Ticker estável → `Investigator` não ativado, pipeline com 4 loops ou menos
- [ ] Hard stop funciona (loop_count <= 6 sempre)
- [ ] Output com Investigator inclui: Causa, Natureza, Evidências, Impacto
