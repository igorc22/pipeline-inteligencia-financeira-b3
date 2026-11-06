from langchain_core.messages import HumanMessage
from fluxo_financeiro import app
from fluxo_financeiro.shared.utils import TICKER_INVALIDO, validar_ticker


def main():
    print("=== Financial Pipeline Analysis ===\n")

    digitado = input("Digite o ticker para analisar (ex: WEGE3): ").strip()
    if not digitado:
        print("Ticker não fornecido.")
        return
    ticker = validar_ticker(digitado)
    if not ticker:
        print(TICKER_INVALIDO)
        return

    print(f"\nAnalisando {ticker}...\n")

    query = f"Analise a ação {ticker}"
    result = app.invoke({"messages": [HumanMessage(query)]})

    final_message = result["messages"][-1]
    print("Resultado Final:")
    print("-" * 50)
    print(final_message.content)
    print("-" * 50)
    print(f"\nTotal de iterações: {result['loop_count']}")


if __name__ == "__main__":
    main()
