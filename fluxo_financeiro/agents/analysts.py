from langchain_anthropic import ChatAnthropic
from langchain.agents import create_agent
from fluxo_financeiro.shared.config import MODEL
from fluxo_financeiro.tools.news import buscar_noticias, buscar_noticias_web

llm = ChatAnthropic(model=MODEL, temperature=0)

analyzer_agent = create_agent(
    model=llm,
    tools=[buscar_noticias, buscar_noticias_web],
    system_prompt="""Você é um analista financeiro conciso. Você receberá dados de mercado de uma ação.
Sua tarefa é usar a ferramenta buscar_noticias para ver o que está acontecendo com a empresa
e então fazer uma análise simples de 1 parágrafo combinando os dados e as notícias.""",
)
