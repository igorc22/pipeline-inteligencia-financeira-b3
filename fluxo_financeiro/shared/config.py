import os
from dotenv import load_dotenv

load_dotenv()

# LLM (Google Gemini). O modelo pode ser trocado pelo .env sem mexer no código.
MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
# Temperatura: não é enviada (ver shared/llm.py). O Google recomenda o padrão nos modelos Gemini 3+,
# e o gemini-3.5-flash-lite tem amostragem fixa (ignora o parâmetro e emite aviso se ele for enviado).
# GEMINI_API_KEY é o nome usado na documentação do Google; GOOGLE_API_KEY é aceito como alternativa.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
