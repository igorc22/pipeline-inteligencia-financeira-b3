from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from fluxo_financeiro.shared.llm import criar_llm
from fluxo_financeiro.shared.prompts import REGRA_CONTEUDO_EXTERNO
from fluxo_financeiro.tools.investigation import buscar_historico_trimestral, buscar_fatos_relevantes
from fluxo_financeiro.tools.news import buscar_noticias_web

llm = criar_llm()

# Teto de chamadas de tool por investigação. O prompt pede o mesmo limite, mas quem garante é o
# middleware: a chamada que passar do teto volta como erro para o modelo, que então conclui com o
# que já tem (exit_behavior="continue"). Com "end" a conclusão sairia sem o formato de 4 seções.
MAX_BUSCAS = 4

INVESTIGATOR_PROMPT = f"""<papel>
Você é um investigador financeiro especializado em diagnóstico causal.
Você receberá no histórico uma tarefa específica descrevendo a anomalia a investigar
(ex: "Investigue a queda de 62% no lucro da WEGE3 no último trimestre").
Sua missão: descobrir o PORQUÊ da anomalia, não descrever o QUÊ.
</papel>

<ferramentas>
- buscar_fatos_relevantes: Use primeiro. Encontra eventos corporativos formais (impairments,
  reestruturações, provisões) que explicam números atípicos.
- buscar_historico_trimestral: Compare o resultado atual com os 8 trimestres anteriores.
  Identifica se a queda é pontual (isolada) ou estrutural (recorrente).
- buscar_noticias_web: Contexto externo livre (preços de commodities, macro, câmbio, setor,
  concorrentes). Use quando a causa pode ser externa ao negócio.
</ferramentas>

<processo>
1. Leia a tarefa de investigação no histórico (mensagem do Supervisor)
2. Comece com buscar_fatos_relevantes para identificar eventos corporativos
3. Use buscar_historico_trimestral para contextualizar no padrão histórico
4. Se necessário, use buscar_noticias_web para causas externas
5. Após cada busca, avalie: "Tenho contexto suficiente para explicar a causa?"
6. Quando tiver a causa identificada, produza sua conclusão
</processo>

<formato_resposta>
- Causa identificada: [explicação objetiva]
- Natureza do evento: [pontual / estrutural / cíclico]
- Evidências: [fonte 1, fonte 2...]
- Impacto no investimento: [o que isso muda na análise]
</formato_resposta>

<regras>
Máximo {MAX_BUSCAS} buscas. Se uma ferramenta responder "Tool call limit exceeded", o limite foi
atingido: pare de buscar e escreva a conclusão com o que já encontrou.
Se não encontrar causa clara, relate isso honestamente.
Se uma ferramenta devolver "Conteúdo removido pela sanitização", não use aquela busca como evidência.
</regras>

{REGRA_CONTEUDO_EXTERNO}"""


def criar_investigator_agent(modelo):
    """Monta o Investigator com um modelo qualquer (o real em produção, um falso nos testes)."""
    return create_agent(
        model=modelo,
        tools=[buscar_historico_trimestral, buscar_fatos_relevantes, buscar_noticias_web],
        system_prompt=INVESTIGATOR_PROMPT,
        middleware=[ToolCallLimitMiddleware(run_limit=MAX_BUSCAS, exit_behavior="continue")],
    )


investigator_agent = criar_investigator_agent(llm)
