"""Retry local: cada parte resolve a falha temporária antes de escalar para o coordenador.

Três camadas, de baixo para cima:
1. A biblioteca do Gemini já repete sozinha cada chamada ao LLM (não configurada por nós).
2. Local: as chamadas externas que o código faz sozinho (Banco Central, Brapi, detector de anomalias,
   buscas do subgrafo de pesquisa no Google ou na Tavily) passam por `com_retentativas`, que repete só o erro temporário, com espera crescente. Os nós dos
   workers (graph/graph.py) repetem o agente inteiro do mesmo jeito e, se não conseguem, devolvem um
   erro estruturado no state em vez de levantar. As tools que o LLM chama continuam devolvendo
   "Erro ao ..." para o agente decidir.
3. Coordenador: recebe o erro que sobrou e decide se manda o agente de novo ou segue sem ele
   (`desistiu`, com o limite `MAX_TENTATIVAS`; o Consolidador lê a mesma regra para as limitações).

`classificar_erro` separa o erro temporário (repetir pode dar certo) do permanente (repetir só gasta):
timeout, conexão caída, resposta que não é JSON e 429/500/502/503/504 são temporários. A cota zerada
por falta de faturamento volta do Gemini como 429, igual a uma instabilidade, mas é permanente:
por isso o 429 com texto de cota ou faturamento conta como permanente.

Sem dependência interna além do logger: o módulo fica em shared/ e importa só bibliotecas.
"""
import json
import time
from typing import Callable, Mapping, Optional, TypeVar

import brapi
import httpx
import requests
from curl_cffi.requests import exceptions as curl_exceptions
from google.genai import errors as genai_errors
from langchain_core.exceptions import ModelConnectionError, ModelRateLimitError, ModelTimeoutError

from fluxo_financeiro.shared.utils import logger

TRANSITORIO = "transitorio"
PERMANENTE = "permanente"

T = TypeVar("T")

# Timeout e conexão caída: repetir pode dar certo. O yfinance usa o curl_cffi, que tem as próprias classes.
ERROS_DE_REDE = (
    requests.Timeout,
    requests.ConnectionError,
    httpx.TimeoutException,
    httpx.ConnectError,
    curl_exceptions.Timeout,
    curl_exceptions.ConnectionError,
    TimeoutError,
    ConnectionError,
    ModelTimeoutError,
    ModelConnectionError,
)
# A Brapi tem as próprias classes para timeout, conexão, 429 e 5xx (o APITimeoutError herda do APIConnectionError).
ERROS_BRAPI_TEMPORARIOS = (
    brapi.APIConnectionError,
    brapi.RateLimitError,
    brapi.InternalServerError,
)
CODIGOS_TEMPORARIOS = {429, 500, 502, 503, 504}
# Textos do 429 que repetir não resolve: cota zero, faturamento desligado, crédito pré-pago no fim.
# "quota" sozinho não serve: o limite por minuto ("You exceeded your current quota ... limit: 15")
# também traz a palavra, e esse passa sozinho em segundos.
MARCAS_DE_COTA = ("limit: 0", "billing is not enabled", "credits", "prepay")


class RespostaVazia(Exception):
    """O agente terminou sem resposta final (nem a saída das tools serviu). Temporária: repetir pode dar certo."""


class ErroTavily(Exception):
    """Erro HTTP da busca da Tavily, com o código (None quando a resposta não trouxe um).

    O langchain-tavily não levanta no erro HTTP: devolve {"error": ValueError("Error 429: ...")} e o
    código só existe no texto. tools/web_search.py lê o código e levanta esta exceção, que fica aqui
    para `classificar_erro` reconhecer sem importar de tools/. 429 e 5xx são temporários; 401, 403 e
    os de limite do plano (432, 433) são permanentes.
    """

    def __init__(self, codigo: Optional[int], mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo


def _cadeia(e: BaseException) -> list[BaseException]:
    """A exceção e as que vieram antes dela (__cause__ e __context__), sem repetir."""
    vistas: list[BaseException] = []
    atual: Optional[BaseException] = e
    while atual is not None and atual not in vistas:
        vistas.append(atual)
        atual = atual.__cause__ or atual.__context__
    return vistas


def _codigo_http(cadeia: list[BaseException]) -> Optional[int]:
    """O código HTTP do erro do Gemini (o wrapper do LangChain guarda no __cause__) ou da Tavily na cadeia."""
    for erro in cadeia:
        if isinstance(erro, genai_errors.APIError) and isinstance(erro.code, int):
            return erro.code
        if isinstance(erro, ErroTavily) and isinstance(erro.codigo, int):
            return erro.codigo
    if any(isinstance(erro, ModelRateLimitError) for erro in cadeia):
        return 429
    return None


def classificar_erro(e: BaseException) -> str:
    """TRANSITORIO se repetir pode dar certo, PERMANENTE se não."""
    if isinstance(e, RespostaVazia):
        return TRANSITORIO
    # Vem antes da rede: o JSONDecodeError do requests e o do curl_cffi também herdam do JSONDecodeError.
    if isinstance(e, json.JSONDecodeError):
        return TRANSITORIO
    if isinstance(e, ERROS_DE_REDE) or isinstance(e, ERROS_BRAPI_TEMPORARIOS):
        return TRANSITORIO
    cadeia = _cadeia(e)
    codigo = _codigo_http(cadeia)
    if codigo not in CODIGOS_TEMPORARIOS:
        return PERMANENTE
    if codigo == 429:
        texto = " ".join(str(erro) for erro in cadeia).lower()
        if any(marca in texto for marca in MARCAS_DE_COTA):
            return PERMANENTE
    return TRANSITORIO


# Camada 3 (coordenador): rodadas do nó por etapa, a local mais 1 mandada pelo coordenador.
# A regra fica aqui, e não no supervisor, porque o Consolidador (agents/) também a lê e não pode importar graph/.
MAX_TENTATIVAS = 2


def desistiu(state: Mapping, agente: str) -> bool:
    """O agente falhou e o coordenador não manda de novo: erro permanente ou limite de rodadas atingido.

    `state` é o MessagesState (lido como dicionário: aqui não se importa types.py). Erro limpo
    (`None`, a última rodada deu certo) ou ausente não é desistência.
    """
    erro = (state.get("erros") or {}).get(agente)
    if erro is None:
        return False
    return erro.tipo == PERMANENTE or (state.get("tentativas") or {}).get(agente, 0) >= MAX_TENTATIVAS


def prefixo_de_erro(agente: str) -> str:
    """Começo da mensagem que o nó deixa no histórico quando o agente falha de vez (graph/graph.py)."""
    return f"Erro: {agente} falhou depois de "


def e_mensagem_de_erro(mensagem, agente: str) -> bool:
    """A mensagem é o "Erro: ..." que o nó do `agente` deixou no histórico depois do retry local."""
    texto = getattr(mensagem, "text", "")
    return getattr(mensagem, "name", None) == agente and isinstance(texto, str) and texto.startswith(prefixo_de_erro(agente))


def _esperar(segundos: float) -> None:
    """A espera entre tentativas. Os testes trocam esta função (tests/conftest.py): nenhum teste dorme."""
    time.sleep(segundos)


def com_retentativas(
    funcao: Callable[[], T],
    *,
    tentativas: int = 2,
    espera: float = 2.0,
    contexto: str = "",
    dormir: Optional[Callable[[float], None]] = None,
) -> T:
    """Chama `funcao()` e repete no erro temporário, com espera crescente (espera, 2x espera, ...).

    Erro permanente ou última tentativa: levanta a mesma exceção, para quem chama tratar.
    `dormir` troca a espera (sem ele, usa _esperar, procurada na hora da chamada).
    """
    if tentativas < 1:
        raise ValueError("tentativas precisa ser pelo menos 1")
    tentativa = 1
    while True:
        try:
            return funcao()
        except Exception as e:
            if tentativa >= tentativas or classificar_erro(e) == PERMANENTE:
                raise
            logger.warning(f"[retry] {contexto}: {type(e).__name__}, tentativa {tentativa} de {tentativas}")
            (dormir or _esperar)(espera * 2 ** (tentativa - 1))
            tentativa += 1
