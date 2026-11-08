"""Testes do retry local (shared/retry.py): classificação do erro e repetição com espera crescente.

A espera é sempre falsa: aqui pelo parâmetro `dormir`, no resto da suíte pela fixture `espera_falsa`.
"""
import json
import logging
from unittest.mock import MagicMock

import brapi
import httpx
import pytest
import requests
from curl_cffi.requests import exceptions as curl_exceptions
from google.genai import errors as genai_errors
from langchain_google_genai.chat_models import (
    GoogleAPIError,
    GoogleAuthenticationError,
    GoogleModelNotFoundError,
    GoogleRateLimitError,
)

from fluxo_financeiro.shared.retry import (
    PERMANENTE,
    TRANSITORIO,
    RespostaVazia,
    classificar_erro,
    com_retentativas,
)

REQ = httpx.Request("GET", "https://brapi.dev")


def _erro_gemini(classe, codigo, mensagem, status):
    """Erro do SDK google-genai como ele chega da API (código HTTP e corpo JSON)."""
    return classe(codigo, {"error": {"code": codigo, "message": mensagem, "status": status}})


def _embrulhado(classe_langchain, erro_sdk):
    """O erro como o ChatGoogleGenerativeAI levanta: a classe do LangChain com o do SDK no __cause__."""
    try:
        raise classe_langchain(f"Error calling model 'gemini' ({erro_sdk.status}): {erro_sdk}") from erro_sdk
    except classe_langchain as e:
        return e


@pytest.mark.parametrize(
    "erro",
    [
        requests.Timeout("lento"),
        requests.ConnectionError("caiu"),
        httpx.ReadTimeout("lento"),
        httpx.ConnectError("caiu"),
        curl_exceptions.Timeout("lento"),
        curl_exceptions.ConnectionError("caiu"),
        TimeoutError("lento"),
        ConnectionError("caiu"),
        brapi.APITimeoutError(request=REQ),
        brapi.APIConnectionError(request=REQ),
        brapi.RateLimitError("429", response=httpx.Response(429, request=REQ), body=None),
        brapi.InternalServerError("500", response=httpx.Response(500, request=REQ), body=None),
        _erro_gemini(genai_errors.ServerError, 500, "Internal error", "INTERNAL"),
        _erro_gemini(GoogleAPIError, 503, "The model is overloaded.", "UNAVAILABLE"),
        _erro_gemini(genai_errors.ServerError, 504, "Deadline exceeded", "DEADLINE_EXCEEDED"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_classifica_timeout_e_conexao_como_transitorio(erro):
    """Confere que timeout, conexão caída e 429/5xx (Brapi e Gemini) são temporários."""
    assert classificar_erro(erro) == TRANSITORIO


def test_classifica_json_invalido_como_transitorio():
    """Confere que resposta que não é JSON (o BCB devolveu isso numa execução real) é temporária."""
    assert classificar_erro(json.JSONDecodeError("Expecting value", "<html>", 0)) == TRANSITORIO
    assert classificar_erro(requests.JSONDecodeError("Expecting value", "<html>", 0)) == TRANSITORIO


def test_classifica_resposta_vazia_como_transitoria():
    """Confere que a resposta final vazia de um agente é temporária (repetir o agente pode dar certo)."""
    assert classificar_erro(RespostaVazia("o agente não respondeu")) == TRANSITORIO


def test_classifica_404_401_como_permanente():
    """Confere que 404, 401, 400 e erros sem relação com rede não são repetidos."""
    nao_encontrado = _erro_gemini(genai_errors.ClientError, 404, "model not found", "NOT_FOUND")
    sem_chave = _erro_gemini(genai_errors.ClientError, 401, "API key not valid", "UNAUTHENTICATED")
    assert classificar_erro(nao_encontrado) == PERMANENTE
    assert classificar_erro(sem_chave) == PERMANENTE
    assert classificar_erro(_embrulhado(GoogleModelNotFoundError, nao_encontrado)) == PERMANENTE
    assert classificar_erro(_embrulhado(GoogleAuthenticationError, sem_chave)) == PERMANENTE
    assert classificar_erro(_erro_gemini(genai_errors.ClientError, 400, "bad", "INVALID_ARGUMENT")) == PERMANENTE
    assert classificar_erro(brapi.NotFoundError("404", response=httpx.Response(404, request=REQ), body=None)) == PERMANENTE
    assert classificar_erro(brapi.AuthenticationError("401", response=httpx.Response(401, request=REQ), body=None)) == PERMANENTE
    assert classificar_erro(ValueError("valor estranho")) == PERMANENTE
    assert classificar_erro(FileNotFoundError("arquivo")) == PERMANENTE


def test_429_de_cota_e_permanente_e_de_instabilidade_e_transitorio():
    """Confere que o 429 de cota zerada ou sem faturamento é permanente e o 429 de instabilidade é temporário.

    Vale para o erro do SDK e para o embrulhado pelo LangChain (que guarda o código no __cause__).
    """
    cota = _erro_gemini(
        genai_errors.ClientError, 429,
        "You exceeded your current quota, please check your plan and billing details. "
        "Quota exceeded for metric: generate_content_free_tier_requests",
        "RESOURCE_EXHAUSTED",
    )
    faturamento = _erro_gemini(
        genai_errors.ClientError, 429, "Billing is not enabled for this project (FreeTier).", "RESOURCE_EXHAUSTED",
    )
    instabilidade = _erro_gemini(
        genai_errors.ClientError, 429, "Too many requests, try again later.", "RESOURCE_EXHAUSTED",
    )

    assert classificar_erro(cota) == PERMANENTE
    assert classificar_erro(faturamento) == PERMANENTE
    assert classificar_erro(_embrulhado(GoogleRateLimitError, cota)) == PERMANENTE
    assert classificar_erro(instabilidade) == TRANSITORIO
    assert classificar_erro(_embrulhado(GoogleRateLimitError, instabilidade)) == TRANSITORIO


def test_com_retentativas_repete_transitorio_e_acerta(caplog):
    """Confere que o erro temporário é repetido depois da espera de 2 s, com uma linha de aviso."""
    caplog.set_level(logging.INFO, logger="fluxo_financeiro")
    funcao = MagicMock(side_effect=[TimeoutError("lento"), "ok"])
    dormir = MagicMock()

    assert com_retentativas(funcao, contexto="[bcb] SELIC", dormir=dormir) == "ok"

    assert funcao.call_count == 2
    dormir.assert_called_once_with(2.0)
    avisos = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert avisos == ["[retry] [bcb] SELIC: TimeoutError, tentativa 1 de 2"]


def test_com_retentativas_espera_cresce():
    """Confere que a espera dobra a cada tentativa (2 s, 4 s)."""
    funcao = MagicMock(side_effect=[TimeoutError(), TimeoutError(), "ok"])
    dormir = MagicMock()

    assert com_retentativas(funcao, tentativas=3, dormir=dormir) == "ok"

    assert [c.args[0] for c in dormir.call_args_list] == [2.0, 4.0]


def test_com_retentativas_nao_repete_permanente():
    """Confere que o erro permanente sobe na hora, sem espera e sem segunda chamada."""
    erro = ValueError("permanente")
    funcao = MagicMock(side_effect=[erro, "ok"])
    dormir = MagicMock()

    with pytest.raises(ValueError) as levantado:
        com_retentativas(funcao, dormir=dormir)

    assert levantado.value is erro
    assert funcao.call_count == 1
    dormir.assert_not_called()


def test_com_retentativas_esgota_e_levanta():
    """Confere que, esgotadas as tentativas, sobe a exceção da última."""
    primeira, ultima = TimeoutError("primeira"), TimeoutError("ultima")
    funcao = MagicMock(side_effect=[primeira, ultima])

    with pytest.raises(TimeoutError) as levantado:
        com_retentativas(funcao, dormir=MagicMock())

    assert levantado.value is ultima
    assert funcao.call_count == 2


def test_com_retentativas_sem_dormir_usa_a_espera_do_modulo(espera_falsa):
    """Confere que, sem `dormir`, a espera é a do módulo (trocada nos testes pela fixture)."""
    funcao = MagicMock(side_effect=[TimeoutError(), "ok"])

    assert com_retentativas(funcao) == "ok"

    espera_falsa.assert_called_once_with(2.0)
