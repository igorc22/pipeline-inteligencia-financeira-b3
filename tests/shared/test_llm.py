from unittest.mock import patch

import pytest

from langchain_google_genai import ChatGoogleGenerativeAI

from fluxo_financeiro.shared import llm as llm_module
from fluxo_financeiro.shared.config import MODEL, flag_ligada


def _criar_sem_cache(**patches):
    """Chama criar_llm ignorando o lru_cache, para testar cenários de chave diferentes."""
    with patch.multiple(llm_module, **patches):
        return llm_module.criar_llm.__wrapped__()


def test_criar_llm_usa_gemini_com_modelo_da_config_e_temperatura_padrao():
    """Confere que o LLM é Gemini, com o modelo de config.py e sem sobrescrever a temperatura."""
    llm = _criar_sem_cache(GEMINI_API_KEY="chave-de-teste")

    assert isinstance(llm, ChatGoogleGenerativeAI)
    assert llm.model.endswith(MODEL)
    assert llm.temperature is None


def test_criar_llm_sem_chave_nao_quebra_importacao():
    """Confere que, sem chave no .env, o LLM ainda é criado (o erro fica para a chamada real)."""
    llm = _criar_sem_cache(GEMINI_API_KEY=None)

    assert llm.google_api_key.get_secret_value() == llm_module.CHAVE_AUSENTE


@pytest.mark.parametrize("valor,esperado", [
    ("true", True), (" sim ", True), ("YES", True),
    ("", False), (None, False), ("talvez", False),
])
def test_flag_ligada_aceita_variacoes(valor, esperado):
    """Confere que a flag aceita os jeitos comuns de escrever 'ligado' e trata o resto como desligado."""
    assert flag_ligada(valor) is esperado


def test_sanitizador_usa_o_modelo_configurado():
    """Confere que o modelo do sanitizador vem de SANITIZACAO_MODELO, sem temperatura."""
    with patch.multiple(llm_module, SANITIZACAO_MODELO="modelo-x", GEMINI_API_KEY="chave-de-teste"):
        llm = llm_module.criar_llm_sanitizador.__wrapped__()

    assert isinstance(llm, ChatGoogleGenerativeAI)
    assert llm.model.endswith("modelo-x")
    assert llm.temperature is None

