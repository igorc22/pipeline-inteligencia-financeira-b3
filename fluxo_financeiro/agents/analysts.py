from langchain.agents import create_agent
from fluxo_financeiro.shared.llm import criar_llm
from fluxo_financeiro.tools.news import buscar_noticias, buscar_noticias_web

llm = criar_llm()

analyzer_agent = create_agent(
    model=llm,
    tools=[buscar_noticias, buscar_noticias_web],
    system_prompt="""Você é um analista financeiro conciso. O histórico traz os dados de mercado de uma ação
(mensagem do YFinance) e uma tarefa específica para você (a última mensagem do Supervisor).
Siga a tarefa do Supervisor: ela pode pedir notícias da empresa ou contexto do setor.

QUANDO USAR CADA FERRAMENTA:
- buscar_noticias: use primeiro. É mais barata e traz artigos com fonte e data.
- buscar_noticias_web: use se buscar_noticias trouxer menos de 2 notícias relevantes, der erro,
  ou se a tarefa pedir algo muito recente ou específico do setor.

RESPOSTA:
Escreva 1 a 2 parágrafos combinando os números do YFinance com o que encontrou.
Cite fatos concretos (datas, valores, eventos) e não invente o que não estiver nas fontes.""",
)
