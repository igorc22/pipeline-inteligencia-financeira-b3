from langchain_core.messages import HumanMessage
from fluxo_financeiro import app


def main():
    print("=== Financial Pipeline Analysis ===\n")

    ticker = input("Digite o ticker para analisar (ex: WEGE3): ").strip()
    if not ticker:
        print("Ticker não fornecido.")
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
