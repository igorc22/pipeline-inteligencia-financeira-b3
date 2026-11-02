"""Busca na web via Gemini + Google Search (grounding). Usado por buscar_noticias_web e buscar_fatos_relevantes."""
from google import genai
from google.genai import types
from langsmith import wrappers

from fluxo_financeiro.shared.config import GEMINI_API_KEY, MODEL

MAX_FONTES = 5


def _criar_cliente() -> genai.Client:
    """Cliente do Google instrumentado para o LangSmith.

    Esta chamada usa o SDK do Google direto (fora do LangChain), então não entraria no trace
    sozinha. O wrap_gemini registra a chamada como um passo "busca_google" dentro da tool,
    com tokens e latência. Com LANGSMITH_TRACING desligado, o wrapper não faz nada.
    """
    return wrappers.wrap_gemini(genai.Client(api_key=GEMINI_API_KEY), chat_name="busca_google")


def pesquisar_na_web(prompt: str) -> str:
    """Pede ao Gemini para pesquisar no Google Search e resumir. Retorna o resumo seguido das fontes.

    Retorna string vazia se o modelo não produziu texto. Exceções (chave inválida, rede, cota)
    sobem para a tool que chamou, que as converte em mensagem de erro.
    """
    client = _criar_cliente()
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )

    texto = (response.text or "").strip()
    if not texto:
        return ""

    fontes = _extrair_fontes(response)
    if fontes:
        texto += "\n\nFontes:\n" + "\n".join(f"- {titulo}: {url}" for titulo, url in fontes)
    return texto


def _extrair_fontes(response) -> list[tuple[str, str]]:
    """Lista (título, url) das páginas que o Google Search usou, sem repetição."""
    if not response.candidates:
        return []
    metadata = response.candidates[0].grounding_metadata
    if not metadata or not metadata.grounding_chunks:
        return []

    fontes, vistas = [], set()
    for chunk in metadata.grounding_chunks:
        web = chunk.web
        if not web or not web.uri or web.uri in vistas:
            continue
        vistas.add(web.uri)
        fontes.append((web.title or web.domain or "fonte", web.uri))
    return fontes[:MAX_FONTES]
