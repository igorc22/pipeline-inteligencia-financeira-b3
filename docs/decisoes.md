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
**Substituída por D33 e D34.**

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
**A parte do provedor foi substituída por D35** (a busca agora é o Google Search do Gemini). A regra "NewsAPI primeiro, web como fallback" continua valendo.

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
**Complementada por D40** (sinais calculados em código acionam o Investigator por guard; o LLM decide quando não há sinal).

Na Etapa 4, o Supervisor se pergunta: *"Um investidor ficaria com dúvida de POR QUE esse número aconteceu?"* Se sim, manda para o Investigator com a anomalia descrita na `task_for_agent`; se não, FINISH.

**Por quê:** investigar toda ação seria caro (várias buscas na web) e inútil para empresa estável. A decisão é **semântica** (LLM), porque "anomalia" depende de contexto e não cabe numa regra fixa tipo "queda > X%".

**Risco:** depende do julgamento do LLM.

**Validado em 01/11/2026 (já com o Gemini, D33):** VALE3 ativou o Investigator (P/L de 74,7x com ROE de 0,3% e lucro caindo de 6,17 bi para 2,35 bi) e o diagnóstico saiu com as 4 seções em 5 loops; WEGE3 terminou na Etapa 4 sem investigação, em 4 loops.

### D26 — Três tools com papéis bem separados
- `buscar_fatos_relevantes`: eventos corporativos formais (fato relevante na CVM, impairment, reestruturação). É a primeira busca porque é a "confissão oficial" da empresa.
- `buscar_historico_trimestral`: 8 trimestres de lucro, receita e lucro bruto, para ver se a queda é pontual ou uma tendência.
- `buscar_noticias_web` (reaproveitada): causas externas como commodities, câmbio e setor.

### D27 — Multi-hop com limite de 4 buscas e formato de saída fixo
**Por quê:** a investigação precisa encadear buscas (o resultado de uma orienta a próxima), mas sem limite pode ficar buscando para sempre. O formato fixo (Causa / Natureza / Evidências / Impacto) torna a resposta comparável entre empresas e mais fácil de consolidar depois. Se não achar a causa, o prompt manda admitir.

**Atualização (D37):** o limite deixou de depender só do prompt e passou a ser garantido em código.

### D28 — Depois do Investigator, sempre FINISH (guard)
**Por quê:** o diagnóstico é o ponto final do pipeline. Um guard em código garante que o Supervisor não reabra o ciclo.

---

## Parte 8 — Troca de provedor: Gemini

### D33 — Gemini 3.5 Flash-Lite no lugar do Claude Haiku
O LLM de todos os agentes e do Supervisor passou a ser o `gemini-3.5-flash-lite`, via `langchain-google-genai`. Substitui a escolha de modelo da D04.

**Por quê:** eu tenho créditos no Gemini, então é mais fácil de usar. O Flash-Lite é o equivalente do Haiku no Google: o modelo barato e rápido da família ($0.30 / $2.50 por milhão de tokens).

**Como ficou:** o modelo é criado num lugar só, `criar_llm()` em `shared/llm.py`, e o nome vem do `.env` (`LLM_MODEL`, padrão `gemini-3.5-flash-lite`). Trocar de modelo é mudar uma variável; trocar de provedor é mexer em um arquivo. A chave é `GEMINI_API_KEY` (aceita `GOOGLE_API_KEY` também).

**Detalhe:** o `ChatGoogleGenerativeAI` exige a chave já na criação, e os agentes são criados na importação. Sem chave, os testes quebrariam; por isso a fábrica usa um placeholder e só avisa no log. O erro de verdade aparece na primeira chamada.

**Validação:** os dois e2e passaram (ver D25), então os prompts escritos para o Haiku funcionaram no Gemini sem ajuste.

### D34 — Não enviar temperatura
Substitui a "temperatura 0" da D04.

**Por quê:** o Google recomenda manter a temperatura padrão nos modelos Gemini 3+, porque valores baixos podem causar loops e piorar o raciocínio. E o `gemini-3.5-flash-lite` tem amostragem fixa: ignora o parâmetro e ainda emite um aviso a cada chamada. Mandar `temperature=None` deixa o modelo no padrão dele.

**Custo:** perdi o "determinismo" da temperatura 0. Na prática, o que segura a previsibilidade do fluxo são os guards em código (D20) e o hard stop (D21), não a temperatura.

### D35 — Busca na web via Google Search do Gemini, com fontes
`buscar_noticias_web` e `buscar_fatos_relevantes` usavam a ferramenta de Web Search da Anthropic, que só existe no Claude. Agora as duas chamam um helper comum, `pesquisar_na_web()` em `tools/web_search.py`, que usa o Gemini com Google Search (grounding).

**Por quê:** com a troca de provedor (D33) a busca da Anthropic deixou de ser uma opção. Juntar as duas tools num helper evita duplicar a chamada, e de quebra a resposta agora traz as **fontes** (título e link) que o Google usou, que viram evidência para o Investigator.

**Cota:** a busca com Google Search nos modelos Gemini 3+ só funciona com faturamento ativo no projeto da chave (5.000 buscas grátis por mês, depois $14 a cada 1.000). No free tier ela retornava 429 (cota zero), e o `gemini-2.5-flash-lite`, que tinha busca grátis, já foi desativado. Enquanto isso, as tools devolviam o erro e o fluxo seguia com NewsAPI + histórico trimestral (foi assim que o Investigator acertou a causa no primeiro e2e da VALE3).

**Resolvido em 02/11/2026:** ativei o faturamento com R$ 20 pré-pagos no AI Studio. Atenção: o crédito de boas-vindas e o Free Trial do Google Cloud não pagam a API do Gemini; só crédito comprado no AI Studio Billing. Com a busca ligada, o e2e da VALE3 usou as 3 tools do Investigator (fatos relevantes, depois histórico trimestral) e o Analyzer caiu no fallback da web nas duas passagens, porque a NewsAPI não achou artigos para as queries. Os dois e2e continuam passando.

### D36 — Tracing no LangSmith, inclusive das buscas no Google
Liguei o LangSmith pelo `.env` (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_AGENT_ID=pipeline-b3`, `LANGSMITH_AGENT_ENVIRONMENT=local`). O LangChain e o LangGraph mandam os traces sozinhos; o único código novo foi envolver o cliente do Google com `wrap_gemini` em `tools/web_search.py`.

**Por quê:** era o "logging de custo por etapa" do meu desenho. Agora cada análise mostra o caminho do grafo, o tempo e os tokens de cada agente e tool. A busca precisa do `wrap_gemini` porque chama o SDK do Google direto, fora do LangChain; sem ele, os tokens dessa chamada sumiriam do trace.

**O que o primeiro trace mostrou (VALE3, 02/11/2026):** 25 s, ~29,5 mil tokens, ~US$ 0,016 por análise. O Investigator é a etapa mais cara (~10 mil tokens, um terço do total). As passagens do Supervisor resolvidas por guard aparecem com 0 tokens, ou seja, a D20 economiza chamadas de verdade. O custo do LangSmith não inclui a taxa por busca do Google Search.

**Agente, não projeto:** comecei com `LANGSMITH_PROJECT`, e os traces chegaram, mas não apareciam na interface. O LangSmith Cloud agora organiza tudo por **agente + ambiente** (`local`, `development`, `staging`, `production`), e a forma antiga manda para um projeto que a navegação por agentes não mostra. Troquei pelas variáveis de agente. Não dá para usar as duas formas juntas: com `LANGSMITH_PROJECT` e `LANGSMITH_AGENT_*` ao mesmo tempo, o SDK não envia nada. Por enquanto uso `local`; `production` fica para quando o projeto rodar de verdade.

**Cuidado:** com o tracing ligado no `.env`, os testes também mandariam traces. O `tests/conftest.py` desliga o tracing antes de qualquer import, e conferi que o `pytest` não cria nada no LangSmith.

## Parte 9 — Fechando o Investigator

### D37 — Limite de buscas do Investigator garantido em código
O Investigator ganhou um `ToolCallLimitMiddleware(run_limit=4, exit_behavior="continue")`. O "máximo 4 buscas" da D27 era só uma instrução no prompt; um modelo teimoso podia ignorar.

**Por quê `continue` e não `end`:** com `continue`, a 5ª chamada volta para o modelo como erro ("Tool call limit exceeded") e ele escreve a conclusão com o que já tem, no formato de 4 seções. Com `end`, a execução pararia na hora e o diagnóstico podia sair sem formato. O prompt avisa o modelo dessa mensagem.

**Como testei:** um modelo falso que insiste em buscar até 20 vezes. A busca real rodou exatamente 4 vezes e o agente ainda fechou com a conclusão. Para isso, a criação do agente virou uma função (`criar_investigator_agent(modelo)`), que o teste chama com o modelo falso.

### D38 — Fontes da busca só com o nome do site
As fontes saíam como `- site: <link>`, e o link é um redirecionamento do Google com ~200 caracteres. Agora saem como `Fontes: seudinheiro.com, kinvo.com.br`.

**Por quê:** o link não ajuda o agente a analisar nada, mas vai para o contexto e é reenviado em cada chamada seguinte do modelo. Medido no LangSmith: o bloco de fontes caiu de ~1.300–1.500 para ~200 caracteres por busca (~85%, uns 300 tokens a menos por busca). Como o Investigator faz várias buscas e reenvia o histórico a cada passo, é ali que a economia mais aparece.

**Lição de medição:** comparar o total de tokens de duas execuções não serve, porque o agente nem sempre faz o mesmo número de buscas (uma execução fez 2, a outra 3, e o total subiu mesmo com a economia). Tem que comparar a mesma peça (a resposta de cada busca).

### D39 — Teste do grafo inteiro com tudo mockado
`tests/graph/test_fluxo.py` roda o app compilado do START ao END com os 3 agentes e o LLM do Supervisor mockados, em três cenários: com anomalia (Investigator roda, 5 loops, 3 decisões pelo LLM), sem anomalia (Investigator não é chamado, 4 loops) e LLM que nunca escolhe FINISH (o hard stop encerra).

**Por quê:** os testes do supervisor olhavam uma decisão por vez. Este pega o que só aparece com as peças juntas: o router, as arestas, os guards em sequência e a tarefa do Supervisor chegando ao Investigator. É a versão sem custo do `scripts/e2e.py`.

### D40 — Guard de anomalia calculado em código
Antes, a Etapa 4 dependia só do Gemini julgar se P/L, ROE e Piotroski eram "anômalos". Agora o nó do YFinance chama `detectar_sinais_anomalia()` (`tools/anomalias.py`), que calcula três sinais com números, sem LLM:
- **queda_lucro**: lucro líquido do último trimestre mais de 30% abaixo do **mesmo trimestre do ano anterior**. Comparar com o mesmo trimestre, e não com o anterior, evita confundir sazonalidade com problema.
- **prejuizo**: último trimestre com lucro líquido negativo.
- **piotroski_fraco**: Piotroski ≤ 3.

Se houver sinal, o Supervisor manda para o Investigator na Etapa 4 **por guard**, com a tarefa montada a partir dos números. Sem sinal, o LLM continua decidindo, e pode investigar mesmo assim.

**Por quê:** prefiro uma regra que eu entendo e consigo testar a um julgamento que muda de uma execução para outra. O LLM continua útil para o que a regra não pega.

**Calibração (02/11/2026):** VALE3 −35% (acusa queda), MGLU3 com prejuízo (acusa), BBAS3 −14%, WEGE3 +5%, ITUB4 +8% e PETR4 +120% (não acusam). Quando o yfinance não traz o dado (ABEV3 com NaN no ano anterior, AZUL4 sem trimestrais), a regra é pulada, nunca acusa. O e2e confirmou: na VALE3 o Investigator entrou pelo guard ("Sinais de anomalia calculados em código (queda_lucro)"), e na WEGE3 o LLM fechou em FINISH.

**Exceção à regra de camadas (D03):** o `graph/` passou a importar direto de `tools/` (o detector). A dependência continua num sentido só, mas pula a camada `agents`. Faz sentido porque o detector é cálculo, não agente; criar um "agente" só para repassar a chamada seria cerimônia.

**Detalhes:** o ticker vem do pedido do usuário por regex (`extrair_ticker` em `shared/utils.py`: 4 letras + 1 ou 2 dígitos). Os sinais também entram no texto da mensagem do YFinance ("SINAIS DE ANOMALIA"), então o Analyzer e o dashboard os veem. Custo: o detector consulta o yfinance de novo (trimestrais + anuais), ~1 s a mais por análise.

**Lição:** o primeiro teste do grafo depois da mudança foi ao yfinance de verdade, porque o nó do YFinance passou a chamar o detector real. O teste falhou (bom), e o detector entrou no mock da fixture. É a pendência "testes não bloqueiam rede" se mostrando na prática.

---

## Parte 10 — Resposta final

### D41 — Consolidador fixo depois do FINISH
Toda análise agora termina num **Consolidador**, que junta dados, notícias, setor e diagnóstico num relatório só. Antes, a resposta era a última mensagem do grafo: o contexto do setor (quando não havia anomalia) ou só o diagnóstico (quando havia).

**Por que fixo e não escolhido pelo Supervisor:** o router troca todo FINISH, inclusive o do hard stop, pelo nó `Consolidador`, que segue para o fim por uma aresta fixa. Ele não entrou no `RouteDecision`. Se o LLM do Supervisor pudesse escolhê-lo, poderia chamá-lo cedo demais ou esquecer dele. É a mesma linha das D20 e D40: o que é objetivo fica em código.

**Como ele funciona:** é uma função com saída estruturada (`RelatorioFinal`), sem tools, então não usa `create_agent`. Recebe só as respostas do YFinance, do Analyzer e do Investigator. As tarefas do Supervisor ficam de fora: são menos tokens, e o texto da web, que pode trazer instruções, chega como dado delimitado. O markdown é montado em código.

**Três cuidados em código:**
- O diagnóstico é **copiado literalmente** do Investigator, e o LLM não o reescreve. Assim Causa, Natureza, Evidências e Impacto chegam inteiros.
- Se faltou uma etapa (hard stop), a limitação é escrita pelo código, e o que o LLM escreveu sobre essa etapa (indicadores, notícias) é descartado: o relatório não finge ter dados que não coletou.
- Se o LLM do Consolidador falhar, a resposta vira as respostas dos agentes juntadas. A análise inteira não se perde no último passo.

**Sem `defer=True`:** o `defer` serve para esperar ramos paralelos convergirem. Meu grafo é sequencial, então ele não faria nada. Volta à mesa junto com o paralelismo via `Send`.

**Custo medido (02/11/2026, LangSmith):** ~2 mil tokens, ~US$ 0,0015 a 0,0023 e ~2 s por análise, cerca de 10% do total. Resultados:
- VALE3: 5 loops, com o diagnóstico completo no relatório.
- WEGE3: 4 loops, sem a seção de diagnóstico.
- ABCD3 (ticker inexistente): 0 indicadores e 2 limitações, sem número inventado.

### D42 — Estado estruturado incremental e relatório sem veredito
O state ganhou só o campo `relatorio` (`RelatorioFinal`: resumo, indicadores, contexto, riscos, limitações, diagnóstico). As `messages` com `name=` continuam sendo o que os guards e o prompt do Supervisor leem.

**Por quê:** a migração completa (`dados`, `noticias`, `diagnostico`, `erros`, com o Supervisor lendo campos) mexe em guards, prompt, testes, API e dashboard. É um projeto próprio. Começar pelo relatório entrega a resposta final agora, sem quebrar o que funciona.

**Sem recomendação de compra ou venda:** o relatório descreve o que os dados mostram e não dá veredito nem preço-alvo. O projeto é de estudo, e um "compre" gerado por LLM a partir de poucas fontes passaria uma confiança que os dados não sustentam.

---

## Jeito de trabalhar

### D29 — Notebook primeiro, pacote depois
Toda feature nasce num notebook em `notebooks/fluxo_financeiro/` (com os conceitos financeiros explicados), e só depois vira código em `fluxo_financeiro/` com testes.

**Por quê:** estou aprendendo finanças em paralelo. O notebook é onde eu entendo o conceito e vejo dados reais; o pacote é onde o código precisa ser limpo e testado.

### D30 — Testes 100% mockados
yfinance, BCB, NewsAPI e o LLM/busca (antes Anthropic, hoje Gemini) são sempre mockados nos testes unitários.

**Por quê:** os testes rodam em segundos, não gastam API e não quebram porque o mercado mudou ou a internet caiu.

**Lição:** se um teste fica desatualizado e o estado não ativa mais o guard esperado, ele escapa do mock e chama a API real (aconteceu com o teste de hard stop quando o limite mudou de 3 para 6).

### D31 — Testes do supervisor com o LLM sempre mockado e checando que os guards não o chamam
Uma fixture mocka o LLM em todos os testes de `test_supervisor.py`, e os testes de guard e hard stop verificam `assert_not_called()`.

**Por quê:** quando o hard stop mudou de 3 para 6, o teste antigo (com `loop_count=3`) deixou de ativar o hard stop, seguiu para o LLM e chamou a API de verdade sem ninguém perceber. Agora um teste desatualizado falha, em vez de gastar créditos em silêncio.

### D32 — Makefile + script de end-to-end separado do pytest
`make test`, `make serve`, `make e2e TICKER=X`, `make e2e-anomalia`, `make e2e-estavel`. O e2e fica em `scripts/e2e.py`, fora do `pytest`.

**Por quê:** quero um jeito curto e sempre igual de rodar as coisas, sem lembrar comando. O e2e usa APIs reais e gasta créditos, então não pode rodar junto com os testes unitários por acidente. Ele sai com código 1 quando o comportamento não é o esperado (Investigator ativado ou não), o que serve para validar a D25 com casos reais.

**Detalhe:** as receitas são comandos simples para funcionar tanto no Git Bash quanto no PowerShell; no Windows o `make` vem do pacote `ezwinports.make`.

### D43 — Rede bloqueada nos testes com `pytest-socket`
O `pyproject.toml` liga `--disable-socket` em todo `pytest`: qualquer tentativa de abrir conexão durante um teste levanta `SocketBlockedError`. O `tests/test_rede_bloqueada.py` garante que o bloqueio continua ligado.

**Por quê:** a D30 (testes 100% mockados) era só convenção. Duas vezes um mock esquecido virou chamada real à API, gastando crédito sem ninguém perceber. Agora um mock esquecido derruba o teste.

**Custo:** um teste que precise de rede de propósito tem de pedir com `@pytest.mark.enable_socket`.

---

## Tensões que já estão aparecendo

Ainda não são decisões, mas são sinais de que algumas escolhas antigas estão chegando no limite:

- ~~**A resposta final é só a última mensagem.**~~ Resolvido com o Consolidador (D41).
- **Estado só com mensagens (D05).** Parcial (D42): `sinais_anomalia` e `relatorio` já são campos; dados, notícias e diagnóstico ainda trafegam como texto entre os agentes. Para paralelizar, campos estruturados (`dados`, `noticias`, `diagnostico`, `erros`) seriam melhores.
- **Erros como string (D06).** O Supervisor não sabe que algo falhou, então não consegue reagir.
- **Analyzer e Investigator se sobrepõem.** Os dois fazem pesquisa na web com focos diferentes.
- ~~**Custo invisível.**~~ Resolvido com o LangSmith (D36): cada análise mostra tokens e custo por etapa.
- **Documentação desatualiza rápido.** Os docs ainda falavam do MVP (hard stop 3, dois agentes) quando o código já estava em outra fase.

## Próximas decisões em aberto

Vindas do desenho de evolução no Excalidraw (coordenador, agente de dados, analista, subgrafo de pesquisa, consolidador e human-in-the-loop). **Nada disso está decidido ainda:**

- ~~Criar um **Consolidador**~~: feito (D41). Em aberto: migrar o resto do **estado estruturado**, e levar o `relatorio` como JSON para o SSE e para o dashboard (cards por seção)?
- Transformar o Analyzer de setor + Investigator num **subgrafo de pesquisa** (geração de perguntas → web → síntese → crítico)?
- **Checkpointer** para sessão (`thread_id`) × **cache de dados frescos** por ticker (são problemas diferentes)?
- **Human-in-the-loop** com `interrupt()`, o que exige um endpoint de `resume` na API?
- ~~**Logging de custo**~~: resolvido com o LangSmith (D36). Em aberto: levar o custo por etapa também para o dashboard?
- **Busca na web independente do provedor do LLM**: hoje a busca está presa ao Gemini (D35), como antes estava presa à Anthropic (D16). Vale trocar por uma API de busca dedicada (Tavily, Brave, Serper) para que trocar de LLM não quebre a busca de novo?
- **NewsAPI quase não acha nada**: no e2e as duas buscas do Analyzer na NewsAPI voltaram vazias e tudo caiu no fallback da web. Ajustar as queries, ou inverter a ordem (web primeiro)?
- **Sanitização**: extrair `{ticker, intenção}` com regex + saída estruturada na entrada, e proteger contra prompt injection vinda do conteúdo da web?
- **Paralelismo** com `Send` (dados primeiro, depois analista e pesquisa ao mesmo tempo)?
