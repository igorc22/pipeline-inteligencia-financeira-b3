import logging
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
