"""Busca na web com Google Search (via Gemini) ou Tavily, escolhida por BUSCA_PROVEDOR no .env.

`buscar_na_web` é a interface única, usada por buscar_noticias_web, buscar_fatos_relevantes e
pesquisar_pergunta. `pesquisar_na_web` é a implementação Google (o Gemini busca e resume); a da
Tavily é uma API de busca: devolve a resposta curta dela e os trechos das páginas, sem LLM nosso.
"""
import re
from urllib.parse import urlparse

from google import genai
from google.genai import types
from langchain_tavily import TavilySearch
from langsmith import wrappers

from fluxo_financeiro.shared.config import BUSCA_PROVEDOR, GEMINI_API_KEY, MODEL, TAVILY_API_KEY
from fluxo_financeiro.shared.prompts import escapar_tags
from fluxo_financeiro.shared.retry import ErroTavily
from fluxo_financeiro.shared.utils import logger

MAX_FONTES = 5
MAX_ERRO_LOG = 300
# Trecho de cada página que a Tavily devolve, cortado: 5 resultados inteiros encheriam o contexto dos agentes.
MAX_TRECHO = 400
FORMATO_PADRAO = "Seja conciso: no máximo 3 parágrafos."

PROVEDORES = ("google", "tavily")
# Origem que vai na tag <conteudo_externo> (tools/sanitizacao.py) de cada provedor.
ORIGEM_DO_PROVEDOR = {"google": "google_search", "tavily": "tavily"}

# Redes sociais ficam fora da Tavily: legenda curta e promocional, sem o corpo de texto que a análise
# precisa (o youtube.com é vídeo). Lista do Fluxo Pesquisa, onde o instagram.com de uma conta de
# "consultoria de investimentos" voltava como lixo em rodadas diferentes.
REDES_SOCIAIS = ["youtube.com", "instagram.com", "x.com", "twitter.com", "facebook.com", "tiktok.com"]

# O langchain-tavily põe o código HTTP só no texto do erro: "Error 429: ...".
_CODIGO_NO_ERRO = re.compile(r"Error (\d{3})")


def provedor_da_busca() -> str:
    """O provedor que a busca usa de fato: o de BUSCA_PROVEDOR, ou google se o valor é inválido ou falta a chave da Tavily.

    Lido na hora da chamada (não na importação), para os testes trocarem a configuração com patch.
    """
    if BUSCA_PROVEDOR == "tavily" and TAVILY_API_KEY:
        return "tavily"
    return "google"


def origem_da_busca() -> str:
    """A origem do texto da busca para a tag <conteudo_externo>: google_search ou tavily."""
    return ORIGEM_DO_PROVEDOR[provedor_da_busca()]


def buscar_na_web(consulta: str, instrucao: str, *, empresa: str = "", formato: str = FORMATO_PADRAO) -> str:
    """Busca na web pelo provedor configurado. Devolve o texto seguido de `Fontes: site1, site2` (ou "").

    `consulta` é o que se procura. `instrucao` (texto nosso, não de terceiros) só vale para o Google,
    onde vira a <tarefa> do prompt do Gemini; a Tavily recebe só a consulta, com a `empresa` na frente.
    Exceções (chave inválida, rede, cota) sobem para quem chamou: as tools convertem em mensagem de
    erro e o subgrafo de pesquisa repete o erro temporário. Provedor inválido ou Tavily sem chave: uma
    linha de aviso e a busca vai ao Google.
    """
    provedor = provedor_da_busca()
    if provedor != BUSCA_PROVEDOR:
        motivo = "sem TAVILY_API_KEY" if BUSCA_PROVEDOR == "tavily" else f"valor inválido, aceitos: {', '.join(PROVEDORES)}"
        logger.warning(f"[busca] BUSCA_PROVEDOR={BUSCA_PROVEDOR!r} ({motivo}): usando o google")
    if provedor == "tavily":
        return _buscar_na_tavily(f"{empresa} {consulta}" if empresa else consulta)
    linha_empresa = f"<empresa>{escapar_tags(empresa)}</empresa>\n" if empresa else ""
    return pesquisar_na_web(
        f"<tarefa>\n{instrucao}\n</tarefa>\n"
        + linha_empresa
        + f"<consulta>{escapar_tags(consulta)}</consulta>\n"
        f"<formato_resposta>{formato}</formato_resposta>"
    )


def _criar_cliente() -> genai.Client:
    """Cliente do Google instrumentado para o LangSmith.

    Esta chamada usa o SDK do Google direto (fora do LangChain), então não entraria no trace
    sozinha. O wrap_gemini registra a chamada como um passo "busca_google" dentro da tool,
    com tokens e latência. Com LANGSMITH_TRACING desligado, o wrapper não faz nada.
    """
    return wrappers.wrap_gemini(genai.Client(api_key=GEMINI_API_KEY), chat_name="busca_google")


def pesquisar_na_web(prompt: str) -> str:
    """Pede ao Gemini para pesquisar no Google Search e resumir. Retorna o resumo seguido das fontes.

    É a implementação Google de `buscar_na_web`. Retorna string vazia se o modelo não produziu
    texto. Exceções (chave inválida, rede, cota) sobem para quem chamou.
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
        texto += "\n\nFontes: " + ", ".join(fontes)
    return texto


def _buscar_na_tavily(consulta: str) -> str:
    """A implementação Tavily: a resposta curta da Tavily (se veio), os trechos das páginas e as fontes no fim.

    A consulta vai crua (o escape de tags é para prompt de LLM; numa API de busca só pioraria a
    consulta). O que volta é texto de terceiros: quem chamou passa por tratar_conteudo_externo.
    Duas armadilhas do langchain-tavily: (1) zero resultado vira STRING de erro, não exceção (o
    handle_tool_error da tool converte), e aqui conta como busca vazia; (2) erro HTTP ou de rede
    volta como {"error": exceção}, e aqui sobe como exceção para o retry e para a tool decidirem.
    """
    tavily = TavilySearch(
        max_results=5,
        time_range="year",
        exclude_domains=REDES_SOCIAIS,
        include_answer=True,
        tavily_api_key=TAVILY_API_KEY,
    )
    resposta = tavily.invoke({"query": consulta})
    if not isinstance(resposta, dict):
        logger.info(f"[busca] tavily sem resultados para '{consulta[:80]}'")
        return ""
    if "error" in resposta:
        _levantar_erro_da_tavily(resposta["error"])

    trechos: list[str] = []
    fontes: list[str] = []
    for resultado in resposta.get("results") or []:
        trecho = " ".join((resultado.get("content") or "").split())[:MAX_TRECHO]
        if not trecho:
            continue
        titulo = (resultado.get("title") or "").strip()
        trechos.append(f"- {titulo}: {trecho}" if titulo else f"- {trecho}")
        site = _dominio(resultado.get("url") or "")
        if site and site not in fontes:
            fontes.append(site)

    resumo = (resposta.get("answer") or "").strip()
    blocos = ([resumo] if resumo else []) + (["\n".join(trechos)] if trechos else [])
    if not blocos:
        return ""
    texto = "\n\n".join(blocos)
    if fontes:
        texto += "\n\nFontes: " + ", ".join(fontes[:MAX_FONTES])
    return texto


def _levantar_erro_da_tavily(erro) -> None:
    """Levanta o erro que a Tavily devolveu dentro do dict: o de rede como veio, o HTTP como ErroTavily com o código.

    O HTTP é um ValueError puro ("Error 429: ..."). Subclasse de ValueError (o JSONDecodeError de
    uma resposta que não era JSON) sobe como veio, para `classificar_erro` tratar como sempre.
    """
    if isinstance(erro, Exception) and type(erro) is not ValueError:
        raise erro
    achado = _CODIGO_NO_ERRO.search(str(erro))
    raise ErroTavily(int(achado.group(1)) if achado else None, f"Tavily: {erro}")


def _dominio(url: str) -> str:
    """O site de uma URL, sem o www (ex: https://www.valor.com.br/a → valor.com.br)."""
    site = urlparse(url).netloc.lower()
    return site.removeprefix("www.")


def registrar_falha_busca(contexto: str, erro: Exception) -> None:
    """Loga a falha da busca numa linha só; o traceback completo fica para LOG_LEVEL=DEBUG.

    O erro do SDK do Google traz o JSON inteiro da resposta, e o logger.exception imprimia
    dezenas de linhas a cada busca que falhava. Para a linha, basta o tipo e o status.
    """
    primeira = next((linha.strip() for linha in str(erro).splitlines() if linha.strip()), "")
    resumo = primeira[:MAX_ERRO_LOG]
    logger.error(f"{contexto}: {type(erro).__name__}: {resumo}")
    logger.debug(f"{contexto}: traceback", exc_info=erro)


def _extrair_fontes(response) -> list[str]:
    """Nomes dos sites (ex: seudinheiro.com) que o Google Search usou, sem repetição.

    Só o nome, sem o link: o Google devolve links de redirecionamento com ~200 caracteres
    cada, que gastariam tokens no contexto de todos os agentes seguintes sem ajudar a análise.
    """
    if not response.candidates:
        return []
    metadata = response.candidates[0].grounding_metadata
    if not metadata or not metadata.grounding_chunks:
        return []

    fontes = []
    for chunk in metadata.grounding_chunks:
        web = chunk.web
        nome = (web.title or web.domain) if web else None
        if nome and nome not in fontes:
            fontes.append(nome)
    return fontes[:MAX_FONTES]
