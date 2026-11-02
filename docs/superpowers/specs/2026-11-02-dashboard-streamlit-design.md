# Dashboard em Streamlit: design

Data: 02/11/2026. Branch: `feat/dashboard-streamlit`.

## Por quê

O dashboard HTML (`dashboard/index.html`) tem dois problemas de leitura:

1. **Texto cortado.** Os cards intermediários começam recolhidos com `max-height: 110px` e um degradê; o YFinance, por exemplo, some a partir do ROE/DY. Respostas longas do Analyzer também ficam escondidas.
2. **Desenho do fluxo confuso.** O Supervisor fica no centro com setas curvas que se cruzam, uma linha tracejada atravessa o Investigator, os rótulos quebram no meio ("YFIN ANCE") e o contraste é baixo. Não dá para ver de relance qual caminho a análise fez.

Além disso, o state final já tem dados estruturados (`relatorio` com `indicadores`, `riscos`, `limitacoes`...), mas a tela mostra tudo como texto corrido.

O usuário escolheu, entre dois mockups, a opção **"relatório primeiro, fluxo numa aba"**, feita em **Streamlit** (o roadmap original já previa Streamlit; a D23 trocou por HTML).

## Objetivos

- Abrir uma análise e entender o resultado de relance: números em quadros, riscos e limitações em lista.
- Nenhum texto cortado: o que é longo vai para um expansor que abre inteiro.
- Desenho do fluxo legível: só o caminho percorrido, em linha, com quem decidiu cada passo.
- Para cada agente, ver a **entrada** (tarefa recebida) e a **saída** (resposta) lado a lado.

## Não objetivos

- Exportar PDF (o HTML exportava; aqui só `.md`, escolha do Claude).
- Animação do grafo em tempo real como a do HTML.
- Mudar o que os agentes escrevem (a repetição de números entre as duas passagens do Analyzer fica como está).
- Consumir a API: o Streamlit chama o grafo direto.

## Anti-objetivos (seria fracasso mesmo funcionando)

- Algum texto de agente ou do relatório truncado sem jeito de abrir inteiro.
- Rodar a análise de novo (e gastar crédito) só porque o usuário trocou de aba ou abriu um expansor.
- Um número no quadro que não está no `relatorio` (o dashboard só reorganiza, nunca calcula nem inventa).

## Decisões tomadas com o usuário

- **Opção A:** abas **Relatório** (padrão), **Como foi feito** e **State (JSON)**.
- **O Streamlit substitui o HTML:** sai `dashboard/index.html` e a rota `GET /` da API. **Fica** a rota `GET /analyze` (SSE) e o `serve.py`, sem tela consumindo, como base para o item do roadmap "levar o `relatorio` em JSON pela API". Nova decisão no `docs/decisoes.md` (D46), com a D23 marcada "substituída por D46".

## Decisões do Claude (o usuário pode trocar)

- O app chama `fluxo_financeiro.app` direto (camada de entrada, igual a `main.py` e `api/`).
- Código em `dashboard/`: `dashboard/app.py` (só Streamlit) e `dashboard/visao.py` (funções puras que transformam o state/eventos no que a tela mostra, testadas). `dashboard` vira pacote e entra no `[tool.setuptools.packages.find]`.
- Comando: `uv run streamlit run dashboard/app.py` e `make streamlit`.
- Para saber **quem decidiu** cada passo, o Supervisor passa a devolver um campo novo no state, `decidido_por: "guard" | "llm" | "hard_stop"`, em todas as saídas do `supervisor_node`. Inferir pelo texto do `supervisor_reasoning` seria frágil (o guard do Investigator e o hard stop nem devolvem reasoning). É uma chave nova do state: entra em `MessagesState` com tipo `str` e sobrescreve, como `supervisor_reasoning`.
- Indicadores: cada item de `relatorio.indicadores` vem como `"Nome: valor"`; vira quadro (`st.metric` ou equivalente) separando no **primeiro** `": "`. Item sem `": "` vira linha de texto abaixo dos quadros. Valores exibidos exatamente como vieram (sem reformatar `5.0x` para `5,0x`).

## Como a tela funciona

**Topo:** campo do ticker e botão **Analisar**. Ticker vazio: aviso, nada roda. Enquanto o grafo roda, um `st.status` lista cada passo ao terminar ("YFinance coletou os dados", "Analyzer: notícias da empresa", "Analyzer: setor", "Investigator", "Consolidador montou o relatório"). O resultado fica em `st.session_state`: trocar de aba ou abrir expansor **não** roda o grafo de novo. Só o botão roda.

**Aba Relatório** (a partir do `relatorio` do state final):
- Título com o ticker e o resumo.
- Indicadores em quadros (grade de colunas).
- Riscos e limitações em listas. Limitações com destaque de aviso, se houver.
- Notícias e setor (`contexto`) em texto.
- Diagnóstico da anomalia, quando o Investigator rodou (texto literal, markdown).
- Sinais de anomalia calculados em código (`sinais_anomalia`), quando houver, como aviso.
- Botão para baixar o relatório em `.md` (o conteúdo da mensagem final do Consolidador).
- `relatorio` nulo (o LLM do Consolidador falhou): aviso explicando e a mensagem final (relatório de emergência) em markdown.

**Aba Como foi feito:**
- **Desenho do caminho** com `st.graphviz_chart` (DOT, renderizado no navegador, sem instalar graphviz), da esquerda para a direita: um nó por execução de worker na ordem em que rodou (Analyzer aparece duas vezes: "empresa" e "setor"), terminando no Consolidador. Cada seta leva o rótulo de quem decidiu (`guard`, `LLM`, `hard stop`), com cores diferentes. Se o Investigator **não** rodou, ele aparece tracejado e apagado, fora do caminho principal. Cores por agente iguais às do HTML atual (YFinance âmbar, Analyzer verde, Investigator vermelho, Consolidador roxo).
- **Um bloco por passo**, na ordem: título com número e agente, selo de quem decidiu, raciocínio do Supervisor (quando houver), **Entrada** (a tarefa do Supervisor que precedeu o worker) e **Saída** (a resposta inteira, num expansor). A saída do YFinance é texto alinhado por espaços: exibir em bloco monoespaçado para não perder o alinhamento. As outras saídas são markdown.
- Hard stop: o caminho mostra o que rodou, e um aviso diz que o fluxo parou pelo limite de 6 passagens.

**Aba State (JSON):** o state final com `st.json`, mensagens serializadas (conteúdo, `name`, tipo) e `relatorio`/`sinais_anomalia` como dicts.

**Erro no grafo** (exceção no meio): `st.error` com a mensagem, e o que já tinha chegado continua visível em "Como foi feito".

## O que muda fora do dashboard

- `fluxo_financeiro/graph/supervisor.py`: `decidido_por` em todas as saídas. `shared/types.py`: a chave nova no `MessagesState`. Testes do supervisor e do grafo conferem o valor.
- `api/server.py`: sai a rota `/` e o `DASHBOARD`; o payload SSE passa a incluir `decidido_por` quando existir (custo zero, mantém a API em dia com o state).
- `pyproject.toml`: `streamlit` nas dependências; `dashboard*` no `packages.find`.
- `Makefile`: alvo `streamlit`; texto do `serve` passa a dizer "API (SSE) em http://127.0.0.1:8000/analyze".
- `.gitignore`: `.superpowers/`.
- Docs: README (como rodar, estrutura), `docs/arquitetura.md` (diagrama de camadas: `dashboard/app.py` Streamlit → `fluxo_financeiro.app`, sem passar pela API; validar com o mermaid-cli), `docs/decisoes.md` (D46; D23 substituída), e os locais `CLAUDE.md` e `.claude/docs/architecture.md`.

## Testes

- `dashboard/visao.py` com testes em `tests/dashboard/`: separação dos indicadores (com e sem `": "`, valor com `:` dentro, como horário), montagem dos passos a partir dos eventos (entrada certa para cada worker, duas passagens do Analyzer rotuladas empresa/setor, Investigator presente ou ausente, hard stop), DOT do caminho (nós na ordem, rótulos de decisão, Investigator tracejado quando não rodou), serialização do state para o JSON.
- Supervisor: cada guard, o hard stop e o caminho do LLM devolvem o `decidido_por` certo.
- Sem rede (o `pytest-socket` já bloqueia). O app ganha testes de fumaça com `AppTest` e um grafo falso (sem rede); validação final rodando `make streamlit` com uma análise real (gasta ~US$ 0,02, pedir antes).

## O que fica para quem implementa

- Layout exato da grade de quadros (quantas colunas), textos dos rótulos do `st.status`, ícones.
- Como capturar ao mesmo tempo as atualizações por nó e o state final do `app.stream` (por exemplo `stream_mode=["updates", "values"]`).
- Nomes e assinaturas das funções de `visao.py`, desde que fiquem puras e testadas.
