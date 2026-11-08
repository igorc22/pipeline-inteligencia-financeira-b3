# Arquitetura

Desenho do sistema como ele está hoje. A história de por que ele ficou assim está em [`decisoes.md`](decisoes.md).

Os diagramas são [Mermaid](https://mermaid.js.org/): o GitHub e o VS Code (com a extensão *Markdown Preview Mermaid Support*) desenham direto do texto. Ao mudar a arquitetura, atualize o diagrama no mesmo commit.

---

## 1. Fluxo do grafo

Um **Supervisor** decide quem trabalha; três **workers** executam e sempre devolvem o controle a ele. Só o Supervisor encerra, e todo encerramento (inclusive o hard stop) passa pelo **Consolidador**, que monta o relatório final.

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
        Y1["yfinance_agent<br/>cotação e perfil (Brapi), P/L, ROE, DY<br/>risco, Piotroski"]
        Y2["detectar_sinais_anomalia<br/>(código, sem LLM)"]
        Y3["indicadores_economicos_em_texto<br/>SELIC, CDI, IPCA 12 meses<br/>(Banco Central, código)"]
        Y1 --> Y2 --> Y3
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

    Y -->|"dados + sinais_anomalia + indicadores do BCB"| S
    A -->|"análise"| S
    I -->|"diagnóstico: Causa, Natureza, Evidências, Impacto"| S
```

| Etapa | Condição | Vai para | Quem decide |
|---|---|---|---|
| 1 | Ainda não há `dados_mercado` | YFinance | LLM |
| 2 | `dados_mercado` gravado, `noticias` não, Analyzer não desistiu | Analyzer (notícias da empresa) | Guard |
| 3 | `noticias` gravado, `contexto_setor` não, Analyzer não desistiu | Analyzer (contexto do setor) | Guard |
| 4 | Analyzer resolvido (os dois campos gravados, ou desistiu) **e** sinais de anomalia | Investigator | Guard |
| 4 | Analyzer resolvido, **sem** sinais | Investigator ou FINISH (agente que desistiu escolhido pelo LLM vira FINISH) | LLM |
| retry | Agente com erro temporário abaixo do limite (seção 7) | O mesmo agente, sem tarefa nova e sem contar volta | Guard |
| fim | YFinance desistiu | FINISH | Guard |
| fim | `diagnostico` gravado ou Investigator desistiu | FINISH | Guard |
| fim | `loop_count >= 6` | FINISH | Hard stop |
| fim | Qualquer FINISH | Consolidador → fim | Router: FINISH sempre vai ao Consolidador |

---

## 2. Como o Supervisor decide

A ordem importa: as regras em código vêm antes e, quando uma delas resolve, o LLM nem é chamado. No trace do LangSmith essas passagens aparecem com **0 tokens**.

Os guards leem os campos que cada agente grava no state (seção 6), não contam mensagens pelo `name`. "Gravado" quer dizer que o campo existe, mesmo vazio ou com uma resposta de erro: a etapa rodou e o fluxo avança como antes.

```mermaid
flowchart TD
    E(["Supervisor recebe o state"]) --> H{"loop_count >= 6?"}
    H -->|sim| FIN1(["FINISH: hard stop"])
    H -->|não| GE{"agente com erro temporário<br/>abaixo de MAX_TENTATIVAS?"}
    GE -->|sim| RE(["O mesmo agente de novo<br/>sem tarefa nova, loop_count + 0"])
    GE -->|não| GY{"YFinance desistiu?"}
    GY -->|sim| FIN3(["FINISH"])
    GY -->|não| G1{"dados_mercado gravado, noticias ausente<br/>e Analyzer não desistiu?"}
    G1 -->|sim| AN(["Analyzer + tarefa: notícias da empresa"])
    G1 -->|não| G2{"diagnostico gravado<br/>ou Investigator desistiu?"}
    G2 -->|sim| FIN2(["FINISH"])
    G2 -->|não| G4{"noticias gravado, contexto_setor ausente<br/>e Analyzer não desistiu?"}
    G4 -->|sim| SET(["Analyzer + tarefa: contexto do setor"])
    G4 -->|não| G3{"Analyzer resolvido (ou desistiu)<br/>e há sinais_anomalia?"}
    G3 -->|sim| INV(["Investigator + tarefa montada com os números"])
    G3 -->|não| LLM["LLM com saída estruturada<br/>RouteDecision: reasoning, next_agent, task_for_agent"]
    LLM --> GD{"o LLM escolheu um<br/>agente que desistiu?"}
    GD -->|sim| FIN4(["FINISH"])
    GD -->|não| D(["Decisão do LLM; task_for_agent vira<br/>mensagem name='Supervisor' no histórico"])

    classDef guard fill:#e8f5e9,stroke:#2e7d32
    classDef llm fill:#e3f2fd,stroke:#1565c0
    class H,GE,GY,G1,G2,G4,G3,GD guard
    class LLM llm
```

"Desistiu" quer dizer que o agente tem erro permanente ou já falhou `MAX_TENTATIVAS` (2) rodadas na etapa: o coordenador não manda de novo, e a etapa dele conta como resolvida. A regra é `desistiu()`, em `shared/retry.py`, a mesma que o Consolidador lê para as limitações (seção 7).

Sinais calculados em código (`tools/anomalias.py`):

| Sinal | Regra |
|---|---|
| `queda_lucro` | Lucro líquido do último trimestre mais de 30% abaixo do **mesmo trimestre do ano anterior** |
| `prejuizo` | Lucro líquido do último trimestre negativo |
| `piotroski_fraco` | Piotroski F-Score ≤ 3 |

Dado faltando no yfinance → a regra é pulada, nunca acusa.

---

## 3. Uma análise com anomalia, passo a passo

Exemplo real (VALE3, 02/11/2026): ~25 s, ~30 mil tokens, ~US\$ 0,016 antes do Consolidador, que acrescenta uma chamada ao LLM.

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuário
    participant B as Brapi
    participant S as Supervisor
    participant Y as YFinance
    participant D as Detector de anomalias
    participant BC as Banco Central
    participant A as Analyzer
    participant I as Investigator
    participant W as Google Search
    participant C as Consolidador

    U->>B: (entrada) VALE3 existe?
    B-->>U: sim (só um 404 recusa)
    U->>S: Analise a ação VALE3
    S->>Y: (LLM) colete os dados
    Y->>B: cotação, perfil e maiores do setor
    B-->>Y: nome, preço, setor da B3, sumário
    Y->>D: ticker VALE3
    D-->>Y: queda_lucro: lucro caiu 35% contra o ano anterior
    Y->>BC: (código) SELIC, CDI e IPCA de 12 meses
    BC-->>Y: cada série com a data do BCB (a que falha some)
    Y-->>S: dados + SINAIS DE ANOMALIA + INDICADORES ECONÔMICOS
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

A dependência flui num único sentido: nenhuma camada importa de uma camada acima dela. As setas tracejadas são as exceções, e todas ainda apontam para baixo: o grafo chama o detector de anomalias e os indicadores do Banco Central direto, porque é cálculo e não agente, e as entradas (CLI, dashboard, e2e e o gerador de fixture) chamam `tools/brapi.py` para recusar um ticker que não existe antes de rodar o grafo.

```mermaid
flowchart BT
    subgraph C_SHARED["shared/"]
        CFG["config.py<br/>.env, MODEL, chaves"]
        LLMF["llm.py<br/>criar_llm(),<br/>criar_llm_sanitizador()"]
        TYP["types.py<br/>MessagesState, RouteDecision,<br/>SinalAnomalia, RelatorioFinal"]
        UTL["utils.py<br/>logger, extrair_ticker(),<br/>validar_ticker()"]
        PRM["prompts.py<br/>tag conteudo_externo,<br/>regra de segurança"]
        RTY["retry.py<br/>com_retentativas(), classificar_erro(),<br/>desistiu(), MAX_TENTATIVAS"]
    end

    subgraph C_TOOLS["tools/"]
        FD["financial_data.py"]
        NW["news.py"]
        INVT["investigation.py"]
        WS["web_search.py"]
        ANO["anomalias.py"]
        SAN["sanitizacao.py<br/>flag SANITIZACAO_ATIVA"]
        BRP["brapi.py<br/>ticker_existe(), buscar_perfil()"]
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

    ENTRY["main.py · dashboard/app.py ·<br/>scripts/e2e.py · scripts/gerar_fixture_eval.py"]

    C_TOOLS --> C_SHARED
    C_AGENTS --> C_TOOLS
    C_AGENTS --> C_SHARED
    C_GRAPH --> C_AGENTS
    C_GRAPH --> C_SHARED
    GR -.->|"exceção: cálculo sem agente"| ANO
    GR -.->|"mesma exceção: cálculo sem agente"| FD
    ENTRY --> C_GRAPH
    ENTRY -->|"validar_ticker"| C_SHARED
    ENTRY -.->|"exceção: ticker_existe"| BRP
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
        BRAPI["Brapi (plano gratuito)<br/>conferência do ticker, cotação,<br/>perfil, maiores do setor"]
        YF["yfinance<br/>P/L, ROE, DY, histórico,<br/>demonstrativos, IBOV"]
        BCB["API do Banco Central<br/>SELIC, CDI, IPCA 12 meses"]
        NAPI["NewsAPI<br/>notícias"]
        LS["LangSmith<br/>agente pipeline-b3"]
    end

    CLI --> APP
    E2E --> APP
    DASH --> APP
    entrada -.->|"o ticker existe?<br/>(CLI, dashboard e e2e)"| BRAPI

    APP --> GEM
    APP --> GS
    APP --> BRAPI
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
| `decidido_por` | Sobrescreve | Quem decidiu a última passagem do Supervisor: `guard`, `llm` ou `hard_stop` (o dashboard desenha nas setas) |
| `sinais_anomalia` | Sobrescreve | Sinais calculados em código pelo nó do YFinance; alimentam o guard da Etapa 4 |
| `relatorio` | Sobrescreve | `RelatorioFinal` do Consolidador (resumo, indicadores, contexto, riscos, limitações, diagnóstico copiado do Investigator); `None` se o LLM dele falhou |
| `dados_mercado` | Sobrescreve | Texto final do YFinance, o mesmo da mensagem (com o aviso da reserva, os sinais e o bloco do Banco Central) |
| `noticias` | Sobrescreve | Primeira passagem do Analyzer (notícias da empresa); gravado uma vez só |
| `contexto_setor` | Sobrescreve | Passagens seguintes do Analyzer (setor); uma terceira passagem cai aqui e não apaga `noticias` |
| `diagnostico` | Sobrescreve | Resposta do Investigator, que o Consolidador copia literalmente |
| `erros` | `operator.or_` (junta dicionários) | Por agente, o último erro que o nó não resolveu localmente: `ErroAgente` com `tipo` (`transitorio`/`permanente`), `mensagem` (até 300 caracteres) e `tentativas`. `None` = a última rodada deu certo |
| `tentativas` | `operator.or_` (junta dicionários) | Por agente, quantas rodadas do nó falharam seguidas. Volta a 0 quando o agente acerta, para a etapa seguinte do mesmo agente (o setor, no Analyzer) ter o limite inteiro |

Os quatro campos de texto (`dados_mercado` a `diagnostico`) são texto livre, um campo por saída de agente. Servem para decidir sem contar mensagens: os guards do Supervisor e as limitações do Consolidador (sem `noticias` → "sem notícias", sem `contexto_setor` → "sem setor") leem só se o campo existe, e um campo ausente é uma etapa que não rodou. Um agente que falhou de vez não grava o campo dele. As `messages` continuam com as mesmas mensagens: os agentes recebem o histórico, e o texto que vai ao LLM do Consolidador ainda sai de `montar_insumos(messages)`, a função que os evals medem.

`erros` e `tentativas` juntam dicionários: cada nó escreve só a própria chave, e limpar é escrever `{agente: None}` e `{agente: 0}` (um dicionário vazio não muda nada).

---

## 7. Retry em camadas

Uma exceção num agente não derruba mais a análise. O princípio: **cada agente/parte resolve o retry localmente antes de escalar pro coordenador**. Quem está mais perto da falha tenta de novo primeiro, e só o que não se resolve ali sobe.

```mermaid
flowchart TD
    F(["Falha numa chamada"]) --> L1["Camada 1: biblioteca do Gemini<br/>repete sozinha cada chamada ao LLM<br/>(não configurada pelo projeto)"]
    L1 -->|"ainda falhou"| L2["Camada 2: local<br/>o nó roda o agente até 2 vezes (TENTATIVAS_LOCAIS)<br/>espera de 2 s, crescente; só erro temporário repete"]
    L2 -->|"acertou"| OK(["Campo do agente gravado<br/>erros: None, tentativas: 0"])
    L2 -->|"esgotou ou erro permanente"| ERR["Erro estruturado no state<br/>erros[agente], tentativas[agente]<br/>+ mensagem 'Erro: ...' no histórico"]
    ERR --> L3{"Camada 3: coordenador<br/>temporário e abaixo de MAX_TENTATIVAS (2)?"}
    L3 -->|sim| RE["Supervisor manda o mesmo agente<br/>mais 1 vez, sem contar volta"]
    RE --> L2
    L3 -->|não: desistiu| SEG(["Segue sem o agente<br/>o Consolidador registra a limitação"])
    SEG -.->|"futuro"| HUM(["Revisão humana<br/>(human-in-the-loop)"])

    classDef futuro stroke-dasharray: 5 5
    class HUM futuro
```

| Onde | O que repete | O que faz quando não resolve |
|---|---|---|
| Nós dos workers (`graph/graph.py`, `_rodar_com_retry`) | O agente inteiro, até 2 vezes com 2 s de espera | Devolve `erros`/`tentativas` e uma mensagem `Erro: <agente> falhou depois de ...`, sem levantar |
| Chamadas que o **código** faz (`com_retentativas`): Banco Central, Brapi, leitura do yfinance no detector de anomalias | A própria chamada, até 2 vezes | Levanta para quem chamou, que já tratava a falha (linha do BCB omitida, yfinance como reserva da Brapi, detector sem sinais) |
| Tools que o **LLM** chama | Nada | Devolvem `"Erro ao ..."` como texto, e o agente decide |

**Temporário ou permanente** (`classificar_erro`, em `shared/retry.py`): timeout, conexão caída, resposta que não é JSON (o Banco Central já devolveu isso numa execução real) e os códigos 429, 500, 503 e 504 repetem. O resto sobe na primeira falha: chave errada, modelo ou ticker que não existe, e o 429 de cota zerada, que tem o mesmo código de uma sobrecarga e se distingue pelo texto (`limit: 0`, `billing is not enabled`, `credits`, `prepay`). O 429 de limite por minuto (`limit: 15`) é temporário.

**Por que o reenvio não conta volta:** a análise com Investigator usa 5 passagens pelo Supervisor e o hard stop é 6. O reenvio devolve `loop_count: 0`, e quem garante que ele termina é o limite por agente. No pior caso, o agente roda 4 vezes (2 locais em cada uma das 2 rodadas).

**Por que não a `RetryPolicy` do LangGraph:** ela só vê a exceção que escapa do nó. Se o nó pega a exceção para devolver um erro estruturado, a política não vê nada, e se não pega, esgotadas as tentativas a exceção derruba o grafo.

Na rodada mandada pelo coordenador, o agente recebe o histórico sem os `Erro: ...` dele, para a última mensagem voltar a ser a tarefa do Supervisor. O Consolidador também deixa de fora o erro que uma rodada seguinte superou, e acrescenta às limitações uma linha por agente que desistiu (`O Analyzer falhou depois de 2 tentativas (erro temporário): a etapa ficou de fora.`).

---

## 8. Como a análise é medida

Os testes unitários conferem o código com tudo mockado. Os evals conferem o texto: uma análise real é gravada uma vez e um LLM-juiz, diferente do modelo dos agentes, lê a resposta de cada agente contra o que aquele agente tinha em mãos. Ficam fora do `pytest` comum (marcador `eval`, rede liberada só neles).

```mermaid
flowchart LR
    ANALISE["Análise real<br/>(grafo com subgraphs=True)"] --> SCRIPT["scripts/gerar_fixture_eval.py"]
    SCRIPT --> FIX["Fixture JSON<br/>state final + saídas das tools<br/>de cada passagem"]
    FIX --> PYT["pytest -m eval<br/>(make eval)"]
    PYT -->|"texto do agente + contexto dele"| JUIZ["Juiz Gemini<br/>gemini-3.8-flash"]
    JUIZ --> NOTAS["notas.csv<br/>toda nota, com custo"]
    JUIZ -->|"reprovou"| FALHAS["_falhas/<br/>vereditos e contexto"]
```

| Agente | O que o juiz mede | Contexto que ele recebe |
|---|---|---|
| Analyzer (2 passagens) | Fidelidade | Saídas das tools da passagem, pedido, resposta do YFinance, tarefas do Supervisor |
| Investigator | Fidelidade e diagnóstico (GEval) | O mesmo, com as tools dele |
| Consolidador | Fidelidade, cobertura (não reprova) e relevância | `montar_insumos(messages)`, a mesma entrada que o nó usa; na cobertura, sem o sumário do negócio (`sem_sumario`) |
| Relatório final | Neutralidade (GEval: sem recomendação de compra ou venda) | Só o pedido |

As respostas anteriores de outros agentes ficam fora do contexto: um número inventado numa passagem contaria como confirmado na seguinte. Na Faithfulness da `deepeval`, só a afirmação que a fonte contradiz derruba a nota (a que a fonte não menciona conta como aprovada), então os vereditos dizem mais do que a nota. Por isso cada fidelidade grava no `notas.csv` uma segunda linha, `(rígida)`, que conta só os vereditos "sim": sai dos vereditos que o juiz já devolveu, custa 0 e nunca reprova.

---

## 9. O que ainda não existe

Limites do desenho atual:

- **Estado estruturado só pela metade**: cada agente já grava a saída num campo (`dados_mercado`, `noticias`, `contexto_setor`, `diagnostico`) e o Supervisor decide por eles, mas o conteúdo continua texto livre, e os agentes ainda leem uns aos outros pelo histórico de mensagens. O Analyzer ainda roda duas vezes em sequência: a troca completa (analista e pesquisa em paralelo) fica para a fase do `Send`.
- **Erros de tool como texto**: o agente que quebra chega ao Supervisor como erro estruturado (seção 7), mas uma tool chamada pelo LLM que falha ainda devolve `"Erro ao ..."`, e o Supervisor não distingue falha de "sem dados" sem ler a mensagem.
- **Desistência sem revisão**: quando o coordenador desiste de um agente, a análise segue sem ele e o relatório avisa. A revisão humana nesse ponto depende do human-in-the-loop.
- **Sem segunda chance para a saída estruturada**: uma `RouteDecision` ou um `RelatorioFinal` inválido do LLM não é pedido de novo além do que a biblioteca do Gemini já repete. O Consolidador cai no relatório de emergência, e no Supervisor a exceção ainda derruba a análise.
- **Pesquisas sobrepostas**: o Analyzer (duas passagens) e o Investigator pesquisam na web com focos diferentes.

Próximos passos:

- **Infraestrutura**: Docker e docker-compose, e deploy na AWS em cima do container.
- **Persistência**: um banco de dados para registrar as chamadas (entrada e saída de cada análise, com data e hora).
- **Checkpointer e cache de dados frescos**: o checkpointer guarda o estado de uma análise para ela poder ser retomada, e o cache evita buscar de novo no yfinance um dado que acabou de chegar.
- **Human-in-the-loop**: a análise pausa (`interrupt()`) para esperar uma resposta e continua de onde parou, o que depende do checkpointer.
- **Provedor genérico**: um LiteLLM na frente do modelo.
- **Busca desacoplada do modelo**: uma API de busca dedicada (Tavily, Brave, Serper), para a troca de LLM não quebrar a busca.
- **Grafo mais enxuto**: menos nós e etapas, talvez juntando as pesquisas que hoje se sobrepõem.
- **Paralelismo com `Send`**: dados primeiro, depois analista e pesquisa ao mesmo tempo.
- **A2A**: no fim, expor o fluxo como um agente A2A, que um futuro fluxo de análise de carteira consiga descobrir e chamar, com o `relatorio` em JSON como resposta.
