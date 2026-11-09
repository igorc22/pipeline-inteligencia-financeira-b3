"""LLM falso para os testes do subgrafo de pesquisa (agents/pesquisa.py): saídas estruturadas em fila."""


class LlmFalso:
    """Responde `with_structured_output(Schema).invoke(...)` com a próxima resposta da fila daquele Schema.

    Uma fila por Schema, porque perguntas, síntese e crítico são chamadas diferentes. Fila vazia
    levanta erro: um roteamento errado que chame o LLM a mais falha alto, em vez de repetir resposta.
    Uma resposta que é exceção é levantada (o LLM fora do ar). Cada chamada fica em `chamadas[Schema]`.
    """

    def __init__(self, respostas: dict):
        self.filas = {schema: list(itens) for schema, itens in respostas.items()}
        self.chamadas: dict = {schema: [] for schema in respostas}

    def with_structured_output(self, schema):
        return _Estruturado(self, schema)


class _Estruturado:
    def __init__(self, llm: LlmFalso, schema):
        self.llm = llm
        self.schema = schema

    def invoke(self, mensagens):
        self.llm.chamadas.setdefault(self.schema, []).append(mensagens)
        fila = self.llm.filas.get(self.schema)
        if not fila:
            raise AssertionError(f"LLM falso sem resposta para {self.schema.__name__}")
        resposta = fila.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta
