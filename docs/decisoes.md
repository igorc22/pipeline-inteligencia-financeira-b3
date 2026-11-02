# Diário de Decisões

Aqui eu registro **por que** o projeto é do jeito que é. O código mostra o "o quê"; este arquivo guarda o raciocínio por trás, para eu conseguir enxergar como a arquitetura foi evoluindo e não repetir discussões que já tive.

Cada decisão tem um número (`D01`, `D02`...) para eu poder citar depois. Quando uma decisão for substituída, não apago: marco como **Substituída por Dxx** e escrevo a nova.

Legenda:
- *(motivo a confirmar)*: o motivo foi reconstruído olhando o código depois; preciso revisar se foi isso mesmo.

---

## Parte 1 — Antes do domínio financeiro: aprender o padrão

### D01 — Estudar o padrão num domínio simples antes de aplicar em finanças
Antes de tocar em ações, fiz dois notebooks de estudo com um "assistente pessoal" (calendário e e-mail mockados): `notebooks/estudo/01_subagents_and_tools` e `02_supervisor_orchestration`.

**Por quê:** queria entender tools, subagentes e supervisor sem misturar com a complexidade do mercado. Se algo desse errado, eu saberia que era o padrão, não os dados.

### D02 — Supervisor como StateGraph explícito, e não como "agente que chama agentes-tool"
No estudo 02, o Supervisor era um agente e os subagentes viravam `@tool`. No projeto real, eu montei um `StateGraph` com um nó por agente e um Supervisor que só roteia.

**Por quê:** com nós explícitos, eu controlo o fluxo (ordem, limite de loops, quem fala quando) e consigo ver cada passo separado. No padrão de agentes-como-tool, o Supervisor decide tudo dentro de uma chamada opaca. *(motivo a confirmar)*

**Custo:** mais código de orquestração (router, edges, state) do que simplesmente passar tools para um agente.

---

## Parte 2 — Fundação (MVP)

### D03 — Camadas com dependência num único sentido
`shared/ ← tools/ ← agents/ ← graph/ ← main.py / api/`. Nenhuma camada importa de uma camada acima.

**Por quê:** cada camada pode ser testada sozinha, não existe import circular, e adicionar um agente novo nas próximas fases não mexe nas tools.

### D04 — Claude Haiku com temperatura 0 para tudo
**Por quê:** é o modelo mais barato e rápido, e para coletar dados e rotear não preciso de um modelo grande. Temperatura 0 deixa o roteamento o mais previsível possível.

**Custo:** a qualidade da síntese e do julgamento ("isso é uma anomalia?") fica limitada. Pode valer usar um modelo maior só nos pontos de decisão no futuro.

### D05 — Estado = histórico de mensagens, com `name=` identificando quem falou
Cada worker devolve só a última mensagem dele como `HumanMessage(name="YFinance" | "Analyzer" | ...)`, e o histórico acumula via `add_messages`.

**Por quê:** todo agente enxerga a conversa inteira (o Analyzer vê os dados do YFinance sem eu passar nada manualmente), e o `name` deixa o Supervisor contar quem já falou.

**Custo:** tudo vira texto livre. Quem vem depois precisa reinterpretar texto em vez de ler campos estruturados. Esse custo já está aparecendo (ver Parte 7).

### D06 — Tools sempre retornam string e nunca levantam exceção
Erro vira `"Erro ao buscar ..."` na resposta da tool.

**Por quê:** o LLM lê a string direto, sem parsing, e um erro de rede não derruba o agente. Ele simplesmente "lê" que deu erro e segue.

**Custo:** o Supervisor não consegue diferenciar "falhou" de "não tem dado" sem ler o texto.

### D07 — Ticker sem `.SA` é aceito
As tools adicionam o sufixo `.SA` sozinhas.

**Por quê:** o usuário e o LLM falam "WEGE3", não "WEGE3.SA". Tirar essa fricção evita erro bobo de ticker não encontrado.

### D08 — O agente de dados só coleta, nunca interpreta
O prompt do `yfinance_agent` manda repassar os dados "exatamente como encontrados", sem análise.

**Por quê:** separação de responsabilidades. Se o coletor já opinasse, o Analyzer receberia uma opinião misturada com dados, e eu não saberia de onde veio cada conclusão.

---

## Parte 3 — Enriquecendo os dados

### D09 — P/L, ROE e DY além do preço
Explorei no notebook `05_tools_dados_b3` e levei para `buscar_dados_acao_b3`.

**Por quê:** só o preço não diz se a ação está cara ou barata. P/L (quantos anos de lucro o mercado paga), ROE (eficiência sobre o patrimônio) e DY (renda em dividendos) são a primeira camada de valuation.

**Detalhe:** o yfinance às vezes devolve o DY já em percentual, por isso existe a correção `dy > 0.20 → dy / 100`.

### D10 — Seis métricas de risco, usando SELIC como taxa livre de risco e IBOV como benchmark
Sharpe, Sortino, Max Drawdown, VaR 95% (Monte Carlo), Beta e Alpha (CAPM), com 1 ano de dados (notebook `06_new_metrics`).

**Por quê:**
- **SELIC** porque no Brasil é o retorno "garantido" da renda fixa. Se a ação não bate a SELIC ajustada ao risco, não compensa o risco.
- **IBOV** porque é o mercado de referência para medir se a ação é agressiva ou defensiva (Beta) e se gerou retorno acima do esperado (Alpha).
- **Sortino** junto com o Sharpe porque o Sharpe pune subida e queda igualmente; o Sortino só pune a queda.
- **VaR por Monte Carlo** (10.000 simulações) para não depender só dos dias que de fato aconteceram no histórico.

**O que ficou de fora:** correlação com índices globais. Explorei no notebook, mas não entrou na tool. *(motivo a confirmar)*

### D11 — SELIC buscada no Banco Central, com fallback
`calcular_metricas_risco` busca a SELIC na série 432 do BCB; se a API falhar, usa 10.75%.

**Por quê:** uma SELIC fixa no código fica errada assim que o Copom muda a taxa. O fallback garante que a métrica sai mesmo com o BCB fora do ar.

### D12 — Piotroski F-Score adaptado aos dados do yfinance, com demonstrativos anuais
Notebook `04_tools_calcular_piotroski_score` → `calcular_piotroski_score`.

**Por quê:** o Piotroski resume a saúde financeira em uma nota de 0 a 9 que o LLM entende fácil. Alguns critérios foram adaptados (crescimento de ativos e passivo circulante no lugar de ROA e dívida de longo prazo) porque são os campos que o yfinance entrega de forma confiável. *(motivo a confirmar)*

A versão do notebook comparava trimestre contra trimestre; a tool usa dados anuais, o que evita confundir sazonalidade com piora. *(motivo a confirmar)*

### D13 — Faixas do Piotroski mudaram de 8-9 / 6-7 / 0-5 para 7-9 / 4-6 / 0-3
Commit `5fafc26`. *(motivo a confirmar: provavelmente as faixas antigas classificavam como "fraca" muita empresa razoável)*

**Pendência:** o prompt do `yfinance_agent` ainda cita as faixas antigas.

### D14 — Indicadores do BCB só via `IndicadorEconomico` (IntEnum)
`busca_indicador_bcb` aceita apenas SELIC (432), IPCA (433) e CDI (12).

**Por quê:** se aceitasse qualquer inteiro, o LLM poderia inventar um código de série que não existe. O enum restringe às séries que eu sei que fazem sentido.

**Estado:** a tool existe e tem teste, mas ainda não está registrada em nenhum agente.

---

## Parte 4 — Notícias

### D15 — NewsAPI em português com fallback para inglês
Busca em `pt`; se vierem menos de 2 artigos válidos, tenta em `en`. Artigos `[Removed]` são descartados.

**Por quê:** a cobertura em português de ações brasileiras na NewsAPI é pequena. O inglês preenche o buraco, principalmente para empresas grandes como Vale e Petrobras.

### D16 — Anthropic Web Search como complemento, não como substituto
Testei no notebook `07_web_search_tool` e comparei com a NewsAPI.

**Decisão:** NewsAPI como padrão e `buscar_noticias_web` como fallback, quando vier pouca coisa ou eu precisar de algo das últimas horas.

**Por quê:** é um trade-off entre **custo, atualidade e controle**:
- NewsAPI é barata, rápida e com fontes conhecidas, mas só cobre até 30 dias (plano grátis) e demora para indexar.
- Web Search é em tempo real e o Claude já filtra e sintetiza, mas custa tokens a mais, tem mais latência e eu não controlo as queries.

---

## Parte 5 — O Supervisor amadurece

### D17 — Primeira versão do Supervisor (MVP)
Dois agentes, Analyzer rodando uma vez só, regras simples ("faltam dados → YFinance; tem dados → Analyzer; acabou → FINISH") e **hard stop em 3 loops**.

**Substituída por D18–D21.**

### D18 — Saída estruturada com `reasoning` e `task_for_agent`
O `RouteDecision` passou a ter, além de `next_agent`:
- `reasoning`: 1-2 frases explicando a decisão
- `task_for_agent`: a instrução específica para o próximo agente, que entra no histórico como `HumanMessage(name="Supervisor")`

**Por quê:**
- Com o `reasoning` eu consigo entender por que o fluxo foi para um lado (e mostrar isso no dashboard).
- Com o `task_for_agent` o worker recebe uma ordem clara em vez de adivinhar o que fazer olhando o histórico. É isso que permite o mesmo Analyzer fazer coisas diferentes em cada passagem.

### D19 — Pipeline de 4 etapas, com o Analyzer rodando duas vezes
1. Dados → 2. Notícias da empresa → 3. Contexto do setor → 4. Conclusão

**Por quê:** notícia só da empresa não diz se o movimento é dela ou do setor inteiro. A segunda passagem coloca a empresa no contexto (tendências, concorrentes, macro). *(motivo a confirmar)*

Deixei a ordem "rígida" no prompt porque, com o LLM decidindo livre, o fluxo ficava imprevisível. *(motivo a confirmar)*

### D20 — Guards determinísticos antes de chamar o LLM
O primeiro guard: se o YFinance já coletou e o Analyzer ainda não rodou, vai para o Analyzer **sem chamar o Claude**.

**Por quê:** quando a regra é objetiva, não faz sentido pagar uma chamada de LLM e correr o risco de ele errar. Código decide o óbvio; o LLM decide o que exige julgamento.

### D21 — Hard stop de 3 para 6
**Por quê:** com o Analyzer rodando duas vezes (D19), o fluxo normal usa exatamente 3 decisões (YFinance, Analyzer, Analyzer setor) e o FINISH só saía porque batia no hard stop. Não sobrava espaço para nenhuma nova tentativa (por exemplo, voltar ao YFinance depois de uma falha). Com 6, o fluxo completo cabe com folga; com o Investigator (D25), o fluxo passou a usar 5 passagens. *(motivo a confirmar)*

O prompt também pede FINISH em `loop_count >= 5` como camada "suave", mas a garantia de verdade é a do código.

---

## Parte 6 — Visualizar o que está acontecendo

### D22 — API FastAPI com streaming SSE
`GET /analyze?ticker=X` roda `app.stream()` e manda cada passo do grafo como evento.

**Por quê:** com `invoke` eu só via o resultado final. Com o stream por nó eu vejo cada decisão do Supervisor e cada resposta de agente chegando em tempo real.

**Detalhe técnico:** o grafo é síncrono, então ele roda numa thread (`ThreadPoolExecutor`) e os eventos passam para o endpoint async por uma `asyncio.Queue`.

### D23 — Dashboard em HTML puro no lugar do Streamlit planejado
O roadmap original previa Streamlit na Fase 4. Fiz um `dashboard/index.html` único, servido pela própria API, com o grafo animado, os "pills" de roteamento com o reasoning e um card por agente (com markdown renderizado).

**Por quê:** queria ver o **grafo** se movendo (qual nó está ativo, para onde o Supervisor mandou), e isso é muito mais natural com SVG/JS do que com Streamlit. *(motivo a confirmar)*

---

## Parte 7 — Investigator condicional (em andamento)

Plano completo: `docs/superpowers/plans/2026-05-11-investigator-condicional.md`.

### D24 — Um agente que explica o **porquê**, não o **quê**
**Problema:** o pipeline reportava números ("lucro caiu 60%") mas não explicava a causa. Um investidor lendo isso fica com a pergunta mais importante sem resposta.

**Decisão:** criar o `investigator_agent`, focado em diagnóstico causal: causa, natureza (pontual / estrutural / cíclica), evidências e impacto no investimento.

### D25 — Condicional: só roda quando há anomalia
Na Etapa 4, o Supervisor se pergunta: *"Um investidor ficaria com dúvida de POR QUE esse número aconteceu?"* Se sim, manda para o Investigator com a anomalia descrita na `task_for_agent`; se não, FINISH.

**Por quê:** investigar toda ação seria caro (várias buscas na web) e inútil para empresa estável. A decisão é **semântica** (LLM), porque "anomalia" depende de contexto e não cabe numa regra fixa tipo "queda > X%".

**Risco:** depende do julgamento do Haiku; ainda preciso validar com um ticker com anomalia e outro estável.

### D26 — Três tools com papéis bem separados
- `buscar_fatos_relevantes`: eventos corporativos formais (fato relevante na CVM, impairment, reestruturação). É a primeira busca porque é a "confissão oficial" da empresa.
- `buscar_historico_trimestral`: 8 trimestres de lucro, receita e lucro bruto, para ver se a queda é pontual ou uma tendência.
- `buscar_noticias_web` (reaproveitada): causas externas como commodities, câmbio e setor.

### D27 — Multi-hop com limite de 4 buscas e formato de saída fixo
**Por quê:** a investigação precisa encadear buscas (o resultado de uma orienta a próxima), mas sem limite pode ficar buscando para sempre. O formato fixo (Causa / Natureza / Evidências / Impacto) torna a resposta comparável entre empresas e mais fácil de consolidar depois. Se não achar a causa, o prompt manda admitir.

### D28 — Depois do Investigator, sempre FINISH (guard)
**Por quê:** o diagnóstico é o ponto final do pipeline. Um guard em código garante que o Supervisor não reabra o ciclo.

---

## Jeito de trabalhar

### D29 — Notebook primeiro, pacote depois
Toda feature nasce num notebook em `notebooks/fluxo_financeiro/` (com os conceitos financeiros explicados), e só depois vira código em `fluxo_financeiro/` com testes.

**Por quê:** estou aprendendo finanças em paralelo. O notebook é onde eu entendo o conceito e vejo dados reais; o pacote é onde o código precisa ser limpo e testado.

### D30 — Testes 100% mockados
yfinance, BCB, NewsAPI e Anthropic são sempre mockados nos testes unitários.

**Por quê:** os testes rodam em segundos, não gastam API e não quebram porque o mercado mudou ou a internet caiu.

**Lição:** se um teste fica desatualizado e o estado não ativa mais o guard esperado, ele escapa do mock e chama a API real (aconteceu com o teste de hard stop quando o limite mudou de 3 para 6).

### D31 — Testes do supervisor com o LLM sempre mockado e checando que os guards não o chamam
Uma fixture mocka o LLM em todos os testes de `test_supervisor.py`, e os testes de guard e hard stop verificam `assert_not_called()`.

**Por quê:** quando o hard stop mudou de 3 para 6, o teste antigo (com `loop_count=3`) deixou de ativar o hard stop, seguiu para o LLM e chamou a API de verdade sem ninguém perceber. Agora um teste desatualizado falha, em vez de gastar créditos em silêncio.

### D32 — Makefile + script de end-to-end separado do pytest
`make test`, `make serve`, `make e2e TICKER=X`, `make e2e-anomalia`, `make e2e-estavel`. O e2e fica em `scripts/e2e.py`, fora do `pytest`.

**Por quê:** quero um jeito curto e sempre igual de rodar as coisas, sem lembrar comando. O e2e usa APIs reais e gasta créditos, então não pode rodar junto com os testes unitários por acidente. Ele sai com código 1 quando o comportamento não é o esperado (Investigator ativado ou não), o que serve para validar a D25 com casos reais.

**Detalhe:** as receitas são comandos simples para funcionar tanto no Git Bash quanto no PowerShell; no Windows o `make` vem do pacote `ezwinports.make`.

---

## Tensões que já estão aparecendo

Ainda não são decisões, mas são sinais de que algumas escolhas antigas estão chegando no limite:

- **A resposta final é só a última mensagem.** Dependendo do caminho, quem "responde" ao usuário é o Analyzer de setor ou o Investigator. Falta alguém que junte tudo (consolidador).
- **Estado só com mensagens (D05).** Para paralelizar agentes ou consolidar, campos estruturados (`dados`, `noticias`, `diagnostico`, `erros`) seriam melhores que texto livre.
- **Erros como string (D06).** O Supervisor não sabe que algo falhou, então não consegue reagir.
- **Analyzer e Investigator se sobrepõem.** Os dois fazem pesquisa na web com focos diferentes.
- **Custo invisível.** Não sei quanto custa cada análise, e as chamadas de web search pelo SDK direto nem aparecem no tracing do LangChain.
- **Documentação desatualiza rápido.** Os docs ainda falavam do MVP (hard stop 3, dois agentes) quando o código já estava em outra fase.

## Próximas decisões em aberto

Vindas do desenho de evolução no Excalidraw (coordenador, agente de dados, analista, subgrafo de pesquisa, consolidador e human-in-the-loop). **Nada disso está decidido ainda:**

- Criar um **Consolidador** (com `defer=True`) e passar para **estado estruturado**?
- Transformar o Analyzer de setor + Investigator num **subgrafo de pesquisa** (geração de perguntas → web → síntese → crítico)?
- **Checkpointer** para sessão (`thread_id`) × **cache de dados frescos** por ticker (são problemas diferentes)?
- **Human-in-the-loop** com `interrupt()`, o que exige um endpoint de `resume` na API?
- **Logging de custo**: LangSmith + `wrap_anthropic`, ou somar `usage_metadata` no state?
- **Sanitização**: extrair `{ticker, intenção}` com regex + saída estruturada na entrada, e proteger contra prompt injection vinda do conteúdo da web?
- **Paralelismo** com `Send` (dados primeiro, depois analista e pesquisa ao mesmo tempo)?
