"""Testes do cliente da Brapi (tools/brapi.py), sempre com o cliente falso: a rede é bloqueada.

As classes PerfilBrapi e ParesDoSetor são lidas pelo módulo (brapi_mod.PerfilBrapi), não importadas
no topo: o teste do reload cria classes novas, e o __eq__ do dataclass compara a classe.
"""
import importlib
import logging
from types import SimpleNamespace
from unittest.mock import patch

import brapi
import httpx
import pytest

import fluxo_financeiro.tools.brapi as brapi_mod

REQ = httpx.Request("GET", "https://brapi.dev")


def _erro_status(classe, codigo):
    return classe("erro", response=httpx.Response(codigo, request=REQ), body=None)


def _avisos_do_projeto(caplog):
    """Os avisos do cliente da Brapi. As linhas `[retry]` (erro temporário repetido) são contadas à parte."""
    return [
        r for r in caplog.records
        if r.name.startswith("fluxo_financeiro") and r.levelname == "WARNING" and r.getMessage().startswith("[brapi]")
    ]


def _avisos_de_retry(caplog):
    return [r for r in caplog.records if r.levelname == "WARNING" and r.getMessage().startswith("[retry]")]


def _resultado_wege3(summary_profile="padrao"):
    if summary_profile == "padrao":
        summary_profile = SimpleNamespace(
            sector="Bens Industriais",
            industry="Máquinas e Equipamentos",
            long_business_summary="A WEG fabrica motores elétricos.",
        )
    return SimpleNamespace(
        long_name="WEG SA",
        regular_market_price=48.19,
        regular_market_change_percent=-0.23,
        fifty_two_week_low=41.15,
        fifty_two_week_high=54.53,
        market_cap=210010383322,
        earnings_per_share=1.4940624,
        summary_profile=summary_profile,
    )


def _papel(stock, name, market_cap, sector="Producer Manufacturing"):
    return SimpleNamespace(stock=stock, name=name, market_cap=market_cap, sector=sector)


def _lista(stocks, total_pages=1):
    return SimpleNamespace(stocks=stocks, total_pages=float(total_pages))


@pytest.fixture
def cliente():
    with patch("fluxo_financeiro.tools.brapi.criar_cliente") as mock_criar:
        yield mock_criar.return_value


# ---------- ticker_existe ----------

def test_ticker_existe_sucesso(cliente):
    """Confere que a Brapi respondendo a cotação faz o ticker existir."""
    cliente.quote.retrieve.return_value = SimpleNamespace(results=[_resultado_wege3()])
    assert brapi_mod.ticker_existe("WEGE3") is True
    cliente.quote.retrieve.assert_called_once_with(tickers="WEGE3")


def test_ticker_existe_404_e_falso(cliente):
    """Confere que o 404 da Brapi é a única resposta que diz que o ticker não existe."""
    cliente.quote.retrieve.side_effect = _erro_status(brapi.NotFoundError, 404)
    assert brapi_mod.ticker_existe("XXXX3") is False


@pytest.mark.parametrize(
    "erro",
    [
        _erro_status(brapi.RateLimitError, 429),
        _erro_status(brapi.AuthenticationError, 401),
        brapi.APITimeoutError(request=REQ),
    ],
    ids=["429", "401", "timeout"],
)
def test_ticker_existe_erro_que_nao_e_404_segue(cliente, caplog, erro):
    """Confere que 429, 401 e timeout devolvem None (a análise segue) com uma linha de aviso sem traceback.

    O 429 e o timeout são temporários: repetem uma vez antes (uma linha de retry); o 401 não repete.
    """
    caplog.set_level(logging.INFO, logger="fluxo_financeiro")
    cliente.quote.retrieve.side_effect = erro

    assert brapi_mod.ticker_existe("WEGE3") is None

    repete = not isinstance(erro, brapi.AuthenticationError)
    assert cliente.quote.retrieve.call_count == (2 if repete else 1)
    assert len(_avisos_de_retry(caplog)) == (1 if repete else 0)
    avisos = _avisos_do_projeto(caplog)
    assert len(avisos) == 1
    msg = avisos[0].getMessage()
    assert "[brapi]" in msg and "WEGE3" in msg and type(erro).__name__ in msg
    assert chr(10) not in msg
    assert all(r.exc_info is None for r in caplog.records)


def test_brapi_repete_timeout(cliente, espera_falsa):
    """Confere que o timeout da Brapi é repetido uma vez (espera de 2 s) e a segunda resposta vale."""
    cliente.quote.retrieve.side_effect = [brapi.APITimeoutError(request=REQ), SimpleNamespace(results=[_resultado_wege3()])]

    assert brapi_mod.ticker_existe("WEGE3") is True

    assert cliente.quote.retrieve.call_count == 2
    espera_falsa.assert_called_once_with(2.0)


def test_brapi_404_nao_repete(cliente, espera_falsa):
    """Confere que o 404 (ticker inexistente) é permanente: uma chamada só, sem espera."""
    cliente.quote.retrieve.side_effect = _erro_status(brapi.NotFoundError, 404)

    assert brapi_mod.ticker_existe("XXXX3") is False

    assert cliente.quote.retrieve.call_count == 1
    espera_falsa.assert_not_called()


def test_ticker_existe_sem_chave_nao_levanta(monkeypatch):
    """Confere que, sem token, a criação do cliente falha dentro do try e devolve None, sem rede."""
    monkeypatch.delenv("BRAPI_API_KEY", raising=False)
    brapi_mod.criar_cliente.cache_clear()
    try:
        with patch("fluxo_financeiro.tools.brapi.BRAPI_API_KEY", None):
            assert brapi_mod.ticker_existe("WEGE3") is None
            assert brapi_mod.buscar_perfil("WEGE3") is None
    finally:
        brapi_mod.criar_cliente.cache_clear()


def test_criar_cliente_sem_retentativas():
    """Confere que o cliente não repete a chamada (o SDK repete 2 vezes por padrão em timeout, 429 e 5xx).

    Com a Brapi fora do ar, cada repetição seguraria a entrada por mais 10 s antes da análise começar.
    Criar o cliente não faz chamada de rede.
    """
    brapi_mod.criar_cliente.cache_clear()
    try:
        with patch("fluxo_financeiro.tools.brapi.BRAPI_API_KEY", "token-falso"):
            cliente_real = brapi_mod.criar_cliente()
        assert cliente_real.max_retries == brapi_mod.MAX_RETENTATIVAS == 0
        assert cliente_real.timeout == brapi_mod.TIMEOUT_SEGUNDOS
    finally:
        brapi_mod.criar_cliente.cache_clear()


def test_importar_nao_cria_cliente():
    """Confere que importar o módulo não cria o cliente (nem exige o token)."""
    brapi_mod.criar_cliente.cache_clear()
    modulo = importlib.reload(brapi_mod)
    assert modulo.criar_cliente.cache_info().currsize == 0


# ---------- buscar_perfil ----------

def test_buscar_perfil_le_cotacao_e_perfil(cliente):
    """Confere que o perfil junta a cotação e o summaryProfile da WEGE3 numa chamada só."""
    cliente.quote.retrieve.return_value = SimpleNamespace(results=[_resultado_wege3()])

    perfil = brapi_mod.buscar_perfil("WEGE3")

    assert perfil == brapi_mod.PerfilBrapi(
        nome="WEG SA",
        preco=48.19,
        variacao_pct=-0.23,
        minima_52s=41.15,
        maxima_52s=54.53,
        valor_mercado=210010383322,
        lpa=1.4940624,
        setor="Bens Industriais",
        subsetor="Máquinas e Equipamentos",
        sumario="A WEG fabrica motores elétricos.",
    )
    cliente.quote.retrieve.assert_called_once_with(tickers="WEGE3", modules="summaryProfile")


def test_buscar_perfil_sem_summary_profile(cliente):
    """Confere que, sem summaryProfile (FII, empresa sem perfil), nome e preço vêm e o setor fica None."""
    cliente.quote.retrieve.return_value = SimpleNamespace(results=[_resultado_wege3(summary_profile=None)])

    perfil = brapi_mod.buscar_perfil("WEGE3")

    assert perfil.nome == "WEG SA" and perfil.preco == 48.19
    assert perfil.setor is None and perfil.subsetor is None and perfil.sumario is None


def test_buscar_perfil_erro_devolve_none(cliente, caplog):
    """Confere que erro da Brapi ou results vazio devolvem None com uma linha de aviso."""
    caplog.set_level(logging.INFO, logger="fluxo_financeiro")
    cliente.quote.retrieve.side_effect = _erro_status(brapi.RateLimitError, 429)
    assert brapi_mod.buscar_perfil("WEGE3") is None
    assert len(_avisos_do_projeto(caplog)) == 1

    cliente.quote.retrieve.side_effect = None
    cliente.quote.retrieve.return_value = SimpleNamespace(results=[])
    assert brapi_mod.buscar_perfil("WEGE3") is None
    assert all(r.exc_info is None for r in caplog.records)


# ---------- ticker errado: sugestão ----------

@pytest.mark.parametrize(
    "codigo, esperado",
    [("WEGE3", True), ("TAEE11", True), ("WEGE3F", False), ("N1CL34F", False), ("WEG", False)],
)
def test_eh_papel_inteiro(codigo, esperado):
    """Confere que só o código de papel inteiro passa (o fracionário F e os estranhos ficam de fora)."""
    assert brapi_mod.eh_papel_inteiro(codigo) is esperado


def test_sugerir_ticker_pula_fracionario_e_o_proprio(cliente):
    """Confere que a sugestão pula o fracionário e o próprio ticker digitado, e devolve None sem resultado ou com erro."""
    cliente.quote.list.return_value = _lista(
        [_papel("WEGE4", "WEG S.A.", 1), _papel("WEGE3F", "WEG S.A.", 1), _papel("WEGE3", "WEG S.A.", 1)]
    )
    assert brapi_mod.sugerir_ticker("WEGE4") == "WEGE3"
    cliente.quote.list.assert_called_once_with(search="WEGE")

    cliente.quote.list.return_value = _lista([])
    assert brapi_mod.sugerir_ticker("WEGE4") is None

    cliente.quote.list.side_effect = _erro_status(brapi.RateLimitError, 429)
    assert brapi_mod.sugerir_ticker("WEGE4") is None


def test_mensagem_ticker_inexistente_com_e_sem_sugestao():
    """Confere a mensagem do ticker inexistente com a sugestão e sem ela."""
    with patch("fluxo_financeiro.tools.brapi.sugerir_ticker", return_value="WEGE3"):
        assert brapi_mod.mensagem_ticker_inexistente("WEGE4") == (
            "Ticker não encontrado na B3: WEGE4. Você quis dizer WEGE3?"
        )
    with patch("fluxo_financeiro.tools.brapi.sugerir_ticker", return_value=None):
        assert brapi_mod.mensagem_ticker_inexistente("XXXX3") == "Ticker não encontrado na B3: XXXX3."


# ---------- pares do setor ----------

SETOR = "Producer Manufacturing"


def _lista_falsa(paginas, busca):
    """side_effect do quote.list: a busca devolve `busca`; a lista do setor devolve a página pedida."""

    def listar(**kwargs):
        if "search" in kwargs:
            return _lista(busca)
        return _lista(paginas[int(kwargs["page"]) - 1], total_pages=len(paginas))

    return listar


def test_pares_do_setor_dedupe_e_posicao(cliente):
    """Confere que a lista do setor tira fracionário e papel repetido da mesma empresa e acha a posição."""
    pagina = [
        _papel("WEGE3", "WEG S.A.", 210.0e9),
        _papel("WEGE3F", "WEG S.A.", 210.0e9),
        _papel("FRAS3", "FRASLE MOBILITY S.A.", 5.9e9),
        _papel("FRAS3F", "FRASLE MOBILITY S.A.", 5.9e9),
        _papel("SHUL4", "SCHULZ S.A.", 1.5e9),
        _papel("SHUL4F", "SCHULZ S.A.", 1.5e9),
        _papel("SHUL3", "SCHULZ S.A.", 1.4e9),
        _papel("DXCO3", "DEXCO S.A.", 1.2e9),
    ]
    cliente.quote.list.side_effect = _lista_falsa([pagina], busca=[_papel("WEGE3", "WEG S.A.", 210.0e9)])

    pares = brapi_mod.buscar_pares_do_setor("WEGE3")

    assert pares.setor == SETOR
    assert pares.posicao == 1 and pares.total == 4
    assert [p[0] for p in pares.pares[:3]] == ["WEGE3", "FRAS3", "SHUL4"]
    assert pares.pares[1] == ("FRAS3", "FRASLE MOBILITY S.A.", 5.9e9)
    chamada_setor = [c for c in cliente.quote.list.call_args_list if "sector" in c.kwargs][0]
    assert chamada_setor.kwargs["sector"] == SETOR
    assert chamada_setor.kwargs["sort_by"] == "market_cap_basic"
    assert chamada_setor.kwargs["sort_order"] == "desc"
    assert chamada_setor.kwargs["type"] == "stock"


def test_pares_do_setor_percorre_paginas(cliente):
    """Confere que a lista do setor segue para a página seguinte e acha a empresa lá."""
    pagina1 = [_papel("AAAA3", "A S.A.", 9e9), _papel("BBBB3", "B S.A.", 8e9)]
    pagina2 = [_papel("CCCC3", "C S.A.", 7e9), _papel("WEGE3", "WEG S.A.", 6e9)]
    cliente.quote.list.side_effect = _lista_falsa([pagina1, pagina2], busca=[_papel("WEGE3", "WEG S.A.", 6e9)])

    pares = brapi_mod.buscar_pares_do_setor("WEGE3", limite=2)

    assert pares.posicao == 4 and pares.total == 4
    assert [p[0] for p in pares.pares] == ["AAAA3", "BBBB3"]
    paginas_pedidas = [c.kwargs["page"] for c in cliente.quote.list.call_args_list if "sector" in c.kwargs]
    assert paginas_pedidas == ["1", "2"]


def test_pares_do_setor_sem_setor_ou_erro_devolve_none(cliente, caplog):
    """Confere que, sem setor na busca, com erro ou com a lista vazia, o resultado é None com aviso."""
    caplog.set_level(logging.INFO, logger="fluxo_financeiro")

    cliente.quote.list.side_effect = _lista_falsa([[]], busca=[_papel("WEGE3", "WEG S.A.", 1, sector=None)])
    assert brapi_mod.buscar_pares_do_setor("WEGE3") is None

    cliente.quote.list.side_effect = _lista_falsa([[]], busca=[_papel("WEGE3", "WEG S.A.", 1)])
    assert brapi_mod.buscar_pares_do_setor("WEGE3") is None

    cliente.quote.list.side_effect = _erro_status(brapi.RateLimitError, 429)
    assert brapi_mod.buscar_pares_do_setor("WEGE3") is None

    assert len(_avisos_do_projeto(caplog)) == 3
    assert all(r.exc_info is None for r in caplog.records)
