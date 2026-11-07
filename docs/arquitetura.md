# Arquitetura

Desenho do sistema como ele está hoje. O **porquê** de cada escolha está em [`decisoes.md`](decisoes.md) (as referências `Dxx` abaixo apontam para lá).

Os diagramas são [Mermaid](https://mermaid.js.org/): o GitHub e o VS Code (com a extensão *Markdown Preview Mermaid Support*) desenham direto do texto. Ao mudar a arquitetura, atualize o diagrama no mesmo commit.

---

## 1. Fluxo do grafo

Um **Supervisor** decide quem trabalha; três **workers** executam e sempre devolvem o controle a ele. Só o Supervisor encerra, e todo encerramento (inclusive o hard stop) passa pelo **Consolidador**, que monta o relatório final (D41).

```mermaid
flowchart TD
    U(["Usuário: 'Analise a ação VALE3'"]) --> S

    S{"Supervisor<br/>guards em código + LLM"}

    S -->|"Etapa 1: sem dados"| Y
    S -->|"Etapas 2 e 3: notícias da empresa, depois do setor"| A
    S -->|"Etapa 4: anomalia"| I
    S -->|"FINISH"| C

    subgraph Y["YFinance (coletor)"]
        direction TB
        Y1["yfinance_agent<br/>preço, P/L, ROE, DY<br/>risco, Piotroski"]
        Y2["detectar_sinais_anomalia<br/>(código, sem LLM)"]
        Y1 --> Y2
    end

    subgraph A["Analyzer (analista)"]
        A1["analyzer_agent<br/>busca na web, NewsAPI como reserva"]
    end

    subgraph I["Investigator (condicional)"]
        I1["investigator_agent<br/>fatos relevantes, histórico trimestral, web<br/>máx. 4 buscas"]
    end

    subgraph C["Consolidador (sempre no fim)"]
        C1["consolidar()<br/>LLM com saída estruturada<br/>RelatorioFinal, sem tools"]
    end

    C -->|"aresta fixa: relatório em markdown + relatorio no state"| F(["Fim"])

    Y -->|"dados + sinais_anomalia"| S
    A -->|"análise"| S
    I -->|"diagnóstico: Causa, Natureza, Evidências, Impacto"| S
```

| Etapa | Condição | Vai para | Quem decide |
|---|---|---|---|
| 1 | Ainda não há dados do YFinance | YFinance | LLM |
| 2 | YFinance coletou, Analyzer ainda não rodou | Analyzer (notícias da empresa) | Guard |
| 3 | Uma passagem do Analyzer | Analyzer (contexto do setor) | Guard (D45) |
| 4 | Duas passagens do Analyzer **e** sinais de anomalia | Investigator | Guard (D40) |
| 4 | Duas passagens do Analyzer, **sem** sinais | Investigator ou FINISH | LLM (D25) |
| — | Investigator já respondeu | FINISH | Guard (D28) |
| — | `loop_count >= 6` | FINISH | Hard stop (D21) |
| — | Qualquer FINISH | Consolidador → fim | Router: FINISH sempre vai ao Consolidador (D41) |

---

## 2. Como o Supervisor decide

A ordem importa: as regras em código vêm antes e, quando uma delas resolve, o LLM nem é chamado. No trace do LangSmith essas passagens aparecem com **0 tokens** (D36).

```mermaid
flowchart TD
    E(["Supervisor recebe o state"]) --> H{"loop_count >= 6?"}
    H -->|sim| FIN1(["FINISH: hard stop"])
    H -->|não| G1{"YFinance coletou e<br/>Analyzer não rodou?"}
    G1 -->|sim| AN(["Analyzer + tarefa: notícias da empresa"])
    G1 -->|não| G2{"Investigator já respondeu?"}
    G2 -->|sim| FIN2(["FINISH"])
    G2 -->|não| G4{"Analyzer rodou<br/>só 1x?"}
    G4 -->|sim| SET(["Analyzer + tarefa: contexto do setor"])
    G4 -->|não| G3{"Analyzer rodou 2x e há<br/>sinais_anomalia?"}
    G3 -->|sim| INV(["Investigator + tarefa montada com os números"])
    G3 -->|não| LLM["LLM com saída estruturada<br/>RouteDecision: reasoning, next_agent, task_for_agent"]
    LLM --> D(["Decisão do LLM; task_for_agent vira<br/>mensagem name='Supervisor' no histórico"])

    classDef guard fill:#e8f5e9,stroke:#2e7d32
    classDef llm fill:#e3f2fd,stroke:#1565c0
    class H,G1,G2,G4,G3 guard
    class LLM llm
```

Sinais calculados em código (`tools/anomalias.py`, D40):

| Sinal | Regra |
|---|---|
| `queda_lucro` | Lucro líquido do último trimestre mais de 30% abaixo do **mesmo trimestre do ano anterior** |
| `prejuizo` | Lucro líquido do último trimestre negativo |
| `piotroski_fraco` | Piotroski F-Score ≤ 3 |

Dado faltando no yfinance → a regra é pulada, nunca acusa.

---

## 3. Uma análise com anomalia, passo a passo

Exemplo real (VALE3, 02/11/2026): ~25 s, ~30 mil tokens, ~US$ 0,016 antes do Consolidador, que acrescenta uma chamada ao LLM.

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuário
    participant S as Supervisor
    participant Y as YFinance
    participant D as Detector de anomalias
    participant A as Analyzer
    participant I as Investigator
    participant W as Google Search
    participant C as Consolidador

    U->>S: Analise a ação VALE3
    S->>Y: (LLM) colete os dados
    Y->>D: ticker VALE3
    D-->>Y: queda_lucro: lucro caiu 35% contra o ano anterior
    Y-->>S: dados + SINAIS DE ANOMALIA
    S->>A: (guard) busque notícias da empresa
    A->>W: busca na web (NewsAPI só se falhar)
    A-->>S: notícias
    S->>A: (guard) busque o contexto do setor
    A-->>S: contexto setorial
    S->>I: (guard) investigue a queda de 35%
    I->>W: fatos relevantes
    I->>I: histórico trimestral
    I-->>S: Causa, Natureza, Evidências, Impacto
    S->>C: (guard) FINISH
    C-->>U: relatório: resumo, indicadores, notícias, diagnóstico, riscos
```

---

## 4. Camadas do código

A dependência flui num único sentido (D03): nenhuma camada importa de uma camada acima dela. A seta tracejada é a única exceção, e ela ainda aponta para baixo: o grafo chama o detector de anomalias direto, porque é cálculo e não agente (D40).

```mermaid
flowchart BT
    subgraph C_SHARED["shared/"]
        CFG["config.py<br/>.env, MODEL, chaves"]
        LLMF["llm.py<br/>criar_llm(),<br/>criar_llm_sanitizador()"]
        TYP["types.py<br/>MessagesState, RouteDecision,<br/>SinalAnomalia, RelatorioFinal"]
        UTL["utils.py<br/>logger, extrair_ticker(),<br/>validar_ticker()"]
        PRM["prompts.py<br/>tag conteudo_externo,<br/>regra de segurança"]
    end

    subgraph C_TOOLS["tools/"]
        FD["financial_data.py"]
        NW["news.py"]
        INVT["investigation.py"]
        WS["web_search.py"]
        ANO["anomalias.py"]
        SAN["sanitizacao.py<br/>flag SANITIZACAO_ATIVA"]
    end

    subgraph C_AGENTS["agents/"]
        COL["collectors.py"]
        ANL["analysts.py"]
        INVA["investigators.py"]
        CONS["consolidator.py"]
    end

    subgraph C_GRAPH["graph/"]
        SUP["supervisor.py"]
        GR["graph.py → app"]
    end

    ENTRY["main.py · dashboard/app.py ·<br/>scripts/e2e.py"]

    C_TOOLS --> C_SHARED
    C_AGENTS --> C_TOOLS
    C_AGENTS --> C_SHARED
    C_GRAPH --> C_AGENTS
    C_GRAPH --> C_SHARED
    GR -.->|"exceção D40"| ANO
    ENTRY --> C_GRAPH
    ENTRY -->|"validar_ticker (D49)"| C_SHARED
```

---

## 5. Serviços externos e interfaces

```mermaid
flowchart LR
    subgraph entrada["Como rodar"]
        CLI["main.py<br/>CLI"]
        DASH["dashboard/app.py<br/>Streamlit"]
        E2E["scripts/e2e.py<br/>teste real"]
    end

    APP["fluxo_financeiro.app<br/>(LangGraph)"]

    subgraph externos["Serviços externos"]
        GEM["Gemini 3.5 Flash-Lite<br/>LLM de todos os agentes"]
        GS["Google Search<br/>(via Gemini, exige faturamento)"]
        YF["yfinance<br/>preços, demonstrativos, IBOV"]
        BCB["API do Banco Central<br/>SELIC"]
        NAPI["NewsAPI<br/>notícias"]
        LS["LangSmith<br/>agente pipeline-b3"]
    end

    CLI --> APP
    E2E --> APP
    DASH --> APP

    APP --> GEM
    APP --> GS
    APP --> YF
    APP --> BCB
    APP --> NAPI
    APP -.->|"traces"| LS
```

---

## 6. Estado (`MessagesState`)

| Campo | Como acumula | Para que serve |
|---|---|---|
| `messages` | `add_messages` (concatena) | Histórico inteiro. Mensagens de agentes são `HumanMessage` com `name` = quem falou (`YFinance`, `Analyzer`, `Investigator`, `Supervisor`) |
| `next_agent` | Sobrescreve | Decisão do Supervisor: `YFinance`, `Analyzer`, `Investigator` ou `FINISH` (o router troca FINISH pelo Consolidador) |
| `loop_count` | `operator.add` (soma) | Cada passagem do Supervisor soma 1; hard stop em 6 |
| `supervisor_reasoning` | Sobrescreve | Justificativa da última decisão (vai para o dashboard) |
| `decidido_por` | Sobrescreve | Quem decidiu a última passagem do Supervisor: `guard`, `llm` ou `hard_stop` (o dashboard desenha nas setas, D46) |
| `sinais_anomalia` | Sobrescreve | Sinais calculados em código pelo nó do YFinance; alimentam o guard da Etapa 4 |
| `relatorio` | Sobrescreve | `RelatorioFinal` do Consolidador (resumo, indicadores, contexto, riscos, limitações, diagnóstico copiado do Investigator); `None` se o LLM dele falhou (D42) |

---

## 7. O que ainda não existe

Próximos passos (ver "Próximas decisões em aberto" em [`decisoes.md`](decisoes.md)):

- **Estado estruturado completo**: `sinais_anomalia` e `relatorio` são os campos além das mensagens (D42); dados, notícias e diagnóstico ainda trafegam como texto entre os agentes, e o Supervisor lê o histórico.
- **Human-in-the-loop, checkpointer e cache de dados**: vindos do desenho de evolução no Excalidraw.
