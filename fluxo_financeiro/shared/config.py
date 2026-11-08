import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# LLM (Google Gemini). O modelo pode ser trocado pelo .env sem mexer no código.
MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")


def flag_ligada(valor: Optional[str]) -> bool:
    """Lê uma feature flag do .env: 1, true, sim, yes ou on (sem diferenciar maiúsculas) ligam."""
    return (valor or "").strip().lower() in ("1", "true", "sim", "yes", "on")


# Sanitização por IA (D48): com a flag ligada, o texto que volta das buscas passa por um classificador
# antes de chegar aos agentes. Liga só essa chamada extra ao LLM (que gasta a key); as tags XML e a
# validação do ticker não custam nada e ficam sempre ligadas.
SANITIZACAO_ATIVA = flag_ligada(os.getenv("SANITIZACAO_ATIVA"))
SANITIZACAO_MODELO = os.getenv("SANITIZACAO_MODELO", MODEL)
# Temperatura: não é enviada (ver shared/llm.py). O Google recomenda o padrão nos modelos Gemini 3+,
# e o gemini-3.5-flash-lite tem amostragem fixa (ignora o parâmetro e emite aviso se ele for enviado).
# GEMINI_API_KEY é o nome usado na documentação do Google; GOOGLE_API_KEY é aceito como alternativa.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
# Token da Brapi (plano gratuito): cotação, perfil e conferência do ticker. Vazio conta como ausente.
BRAPI_API_KEY = os.getenv("BRAPI_API_KEY") or None
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
