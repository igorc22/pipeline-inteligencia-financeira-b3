"""Retry local: cada parte resolve a falha temporária antes de escalar para o coordenador.

Três camadas, de baixo para cima:
1. A biblioteca do Gemini já repete sozinha cada chamada ao LLM (não configurada por nós).
2. Local: as chamadas externas que o código faz sozinho (Banco Central, Brapi, detector de anomalias)
   passam por `com_retentativas`, que repete só o erro temporário, com espera crescente.
   As tools que o LLM chama continuam devolvendo "Erro ao ..." para o agente decidir.
3. Coordenador: recebe o erro que sobrou e decide se manda o agente de novo ou segue sem ele.

`classificar_erro` separa o erro temporário (repetir pode dar certo) do permanente (repetir só gasta):
timeout, conexão caída, resposta que não é JSON e 429/500/503/504 são temporários. A cota zerada
por falta de faturamento volta do Gemini como 429, igual a uma instabilidade, mas é permanente:
por isso o 429 com texto de cota ou faturamento conta como permanente.

Sem dependência interna além do logger: o módulo fica em shared/ e importa só bibliotecas.
"""
import json
import time
from typing import Callable, Optional, TypeVar

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
CODIGOS_TEMPORARIOS = {429, 500, 503, 504}
# Textos do 429 de cota zerada ou sem faturamento: repetir não adianta.
MARCAS_DE_COTA = ("exceeded your current quota", "quota", "billing", "freetier", "free_tier")


def _cadeia(e: BaseException) -> list[BaseException]:
    """A exceção e as que vieram antes dela (__cause__ e __context__), sem repetir."""
    vistas: list[BaseException] = []
    atual: Optional[BaseException] = e
    while atual is not None and atual not in vistas:
        vistas.append(atual)
        atual = atual.__cause__ or atual.__context__
    return vistas


def _codigo_http(cadeia: list[BaseException]) -> Optional[int]:
    """O código HTTP do erro do Gemini na cadeia (o wrapper do LangChain guarda no __cause__)."""
    for erro in cadeia:
        if isinstance(erro, genai_errors.APIError) and isinstance(erro.code, int):
            return erro.code
    if any(isinstance(erro, ModelRateLimitError) for erro in cadeia):
        return 429
    return None


def classificar_erro(e: BaseException) -> str:
    """TRANSITORIO se repetir pode dar certo, PERMANENTE se não."""
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
