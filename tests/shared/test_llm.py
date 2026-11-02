from unittest.mock import patch

from langchain_google_genai import ChatGoogleGenerativeAI

from fluxo_financeiro.shared import llm as llm_module
from fluxo_financeiro.shared.config import MODEL


def _criar_sem_cache(**patches):
    """Chama criar_llm ignorando o lru_cache, para testar cenários de chave diferentes."""
    with patch.multiple(llm_module, **patches):
        return llm_module.criar_llm.__wrapped__()


def test_criar_llm_usa_gemini_com_modelo_da_config_e_temperatura_padrao():
    """Test que o LLM é Gemini, com o modelo de config.py e sem sobrescrever a temperatura."""
    llm = _criar_sem_cache(GEMINI_API_KEY="chave-de-teste")

    assert isinstance(llm, ChatGoogleGenerativeAI)
    assert llm.model.endswith(MODEL)
    assert llm.temperature is None


def test_criar_llm_sem_chave_nao_quebra_importacao():
    """Test que, sem chave no .env, o LLM ainda é criado (o erro fica para a chamada real)."""
    llm = _criar_sem_cache(GEMINI_API_KEY=None)

    assert llm.google_api_key.get_secret_value() == llm_module.CHAVE_AUSENTE


def test_criar_llm_reutiliza_a_mesma_instancia():
    """Test que todos os agentes compartilham uma única instância do LLM."""
    assert llm_module.criar_llm() is llm_module.criar_llm()
