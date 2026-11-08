"""Gera a fixture dos evals a partir de uma análise real (chamadas REAIS: gasta créditos de API).

Uso:
    uv run python scripts/gerar_fixture_eval.py VALE3
    uv run python scripts/gerar_fixture_eval.py WEGE3

Roda o grafo com subgraphs=True para ver, além do state final, as saídas das tools de cada
passagem de cada agente (elas ficam dentro do create_agent e não chegam ao state). Grava tudo em
tests/evals/fixtures/<ticker>.json, em UTF-8: texto da busca na web traz caractere fora do cp1252.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

from langchain_core.messages import HumanMessage, ToolMessage, messages_to_dict

from fluxo_financeiro import app
from fluxo_financeiro.shared.config import MODEL
from fluxo_financeiro.shared.utils import TICKER_INVALIDO, validar_ticker

RAIZ = Path(__file__).resolve().parents[1]
VERSAO_FIXTURE = 1
PASTA_FIXTURES = RAIZ / "tests" / "evals" / "fixtures"


def _texto(mensagem: ToolMessage) -> str:
    return mensagem.content if isinstance(mensagem.content, str) else mensagem.text


def coletar(eventos: Iterable[tuple[tuple[str, ...], str, dict]]) -> tuple[dict, list[dict]]:
    """State final e uma passagem por namespace de agente, com as saídas das tools na ordem.

    Cada chamada de um agente dentro de um nó ganha um namespace próprio ('Analyzer:<id>'), então
    as duas passagens do Analyzer se separam pela ordem de aparição. As ToolMessage só são lidas
    dos eventos 'updates': os 'values' do subgrafo repetem o histórico inteiro do agente.
    """
    estado_final: dict = {}
    passagens: list[dict] = []
    por_namespace: dict[str, dict] = {}
    contagem: dict[str, int] = {}

    for ns, modo, dados in eventos:
        if not ns:
            if modo == "values":
                estado_final = dados
            continue

        chave = ns[0]
        passagem = por_namespace.get(chave)
        if passagem is None:
            agente = chave.split(":")[0]
            contagem[agente] = contagem.get(agente, 0) + 1
            passagem = {"agente": agente, "n": contagem[agente], "tools": []}
            por_namespace[chave] = passagem
            passagens.append(passagem)

        if modo != "updates" or not isinstance(dados, dict):
            continue
        for update_do_no in dados.values():
            if not isinstance(update_do_no, dict):
                continue
            for mensagem in update_do_no.get("messages") or []:
                if isinstance(mensagem, ToolMessage):
                    passagem["tools"].append({"nome": mensagem.name, "conteudo": _texto(mensagem)})

    return estado_final, passagens


def rodar(ticker: str) -> tuple[dict, list[dict]]:
    """Roda o grafo real para o ticker (mesmo pedido do e2e.py) e coleta state e passagens."""
    eventos = app.stream(
        {"messages": [HumanMessage(f"Analise a ação {ticker}")]},
        stream_mode=["updates", "values"],
        subgraphs=True,
    )
    return coletar(eventos)


def montar_fixture(ticker: str, estado_final: dict, passagens: list[dict], modelo: str, gerado_em: str) -> dict:
    """Fixture em formato JSON. Recusa a análise cujo Consolidador caiu no fallback (relatorio None)."""
    relatorio = estado_final.get("relatorio")
    if relatorio is None:
        raise ValueError(f"relatório ausente: o Consolidador de {ticker} caiu no fallback, a análise não vira fixture")
    return {
        "versao": VERSAO_FIXTURE,
        "ticker": ticker,
        "gerado_em": gerado_em,
        "modelo": modelo,
        "messages": messages_to_dict(estado_final.get("messages") or []),
        "passagens": passagens,
        "sinais_anomalia": [s.model_dump() for s in estado_final.get("sinais_anomalia") or []],
        "relatorio": relatorio.model_dump(),
    }


def main(argv: list[str] | None = None, pasta: Path = PASTA_FIXTURES) -> int:
    parser = argparse.ArgumentParser(description="Gera a fixture dos evals (GASTA CREDITOS).")
    parser.add_argument("ticker", help="Ticker da B3, ex: VALE3")
    args = parser.parse_args(argv)

    # Importado aqui para o patch no módulo de origem valer nos testes.
    from fluxo_financeiro.tools.brapi import mensagem_ticker_inexistente, ticker_existe

    ticker = validar_ticker(args.ticker)
    if ticker is None:
        print(TICKER_INVALIDO)
        return 2
    if ticker_existe(ticker) is False:  # None (Brapi sem resposta) segue
        print(mensagem_ticker_inexistente(ticker))
        return 2

    estado_final, passagens = rodar(ticker)
    gerado_em = datetime.now().isoformat(timespec="seconds")
    try:
        fixture = montar_fixture(ticker, estado_final, passagens, MODEL, gerado_em)
    except ValueError as e:
        print(f"Fixture não gravada: {e}")
        return 1

    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{ticker.lower()}.json"
    texto = json.dumps(fixture, ensure_ascii=False, indent=2)
    with open(caminho, "w", encoding="utf-8") as arquivo:
        arquivo.write(texto)

    print(f"Fixture gravada em {caminho}")
    for p in passagens:
        print(f"  {p['agente']} {p['n']}: {len(p['tools'])} tools")
    print(f"Tamanho: {len(texto)} caracteres")
    return 0


if __name__ == "__main__":
    sys.exit(main())
