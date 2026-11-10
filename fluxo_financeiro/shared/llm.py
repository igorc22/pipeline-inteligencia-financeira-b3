from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI

from fluxo_financeiro.shared.config import GEMINI_API_KEY, MODEL, SANITIZACAO_MODELO
from fluxo_financeiro.shared.utils import logger

# O ChatGoogleGenerativeAI exige uma chave já na criação. Como os agentes são criados na
# importação do módulo, sem este placeholder os testes e o `make check` quebrariam enquanto
# a chave não estiver no .env. Com ele, o erro só aparece na primeira chamada real à API.
CHAVE_AUSENTE = "GEMINI_API_KEY-nao-configurada"


@lru_cache(maxsize=1)
def criar_llm() -> ChatGoogleGenerativeAI:
    """Único ponto do projeto que instancia o LLM: trocar de modelo ou provedor é mexer só aqui.

    O LLM não guarda estado entre chamadas, então uma instância é compartilhada por todos os agentes.
    """
    if not GEMINI_API_KEY:
        logger.warning("[llm] GEMINI_API_KEY não configurada no .env: as chamadas ao Gemini vão falhar")
    return ChatGoogleGenerativeAI(
        model=MODEL,
        # None = usa o padrão do modelo. O Google recomenda não mexer na temperatura no Gemini 3+
        # (valores baixos podem causar loops), e o gemini-3.5-flash-lite nem aceita o ajuste.
        temperature=None,
        api_key=GEMINI_API_KEY or CHAVE_AUSENTE,
    )


@lru_cache(maxsize=1)
def criar_llm_sanitizador() -> ChatGoogleGenerativeAI:
    """LLM do classificador de injeção (tools/sanitizacao.py), com o modelo de SANITIZACAO_MODELO.

    Instância separada da dos agentes para o modelo poder ser outro (mais leve) sem mexer neles.
    Criá-la não faz chamada nenhuma: com a flag desligada, ela existe mas nunca é usada.
    """
    return ChatGoogleGenerativeAI(
        model=SANITIZACAO_MODELO,
        temperature=None,
        api_key=GEMINI_API_KEY or CHAVE_AUSENTE,
    )
