import logging
import re
from typing import Optional

from fluxo_financeiro.shared.config import LOG_LEVEL

logger = logging.getLogger("fluxo_financeiro")
logger.setLevel(LOG_LEVEL)

handler = logging.StreamHandler()
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(handler)


# Ticker da B3: 4 letras + 1 ou 2 dígitos (VALE3, PETR4, TAEE11), com ou sem o sufixo .SA
_PADRAO_TICKER_B3 = re.compile(r"\b([A-Z]{4}\d{1,2})(?:\.SA)?\b")


def extrair_ticker(texto: str) -> Optional[str]:
    """Primeiro ticker da B3 encontrado no texto, sem o .SA (ex: 'Analise a vale3' → 'VALE3')."""
    encontrado = _PADRAO_TICKER_B3.search(texto.upper())
    return encontrado.group(1) if encontrado else None
