"""Roda o grafo completo para um ticker (chamadas REAIS: gasta créditos de API) e mostra o caminho percorrido.

Uso:
    uv run python scripts/e2e.py VALE3
    uv run python scripts/e2e.py VALE3 --espera-investigator
    uv run python scripts/e2e.py WEGE3 --espera-sem-investigator

Com --espera-*, o script sai com código 1 se o comportamento não for o esperado.
"""
import argparse
import sys

from langchain_core.messages import HumanMessage

from fluxo_financeiro import app

SECOES_DIAGNOSTICO = ["Causa", "Natureza", "Evidências", "Impacto"]
HARD_STOP = 6


def rodar(ticker: str) -> dict:
    caminho: list[str] = []
    mensagens: dict[str, str] = {}
    relatorio = None
    loops = 0

    initial = {"messages": [HumanMessage(content=f"Analise a ação {ticker.upper()}")]}
    for event in app.stream(initial):
        for node, update in event.items():
            update = update or {}
            loops += update.get("loop_count", 0)
            if node == "Supervisor":
                decisao = update.get("next_agent", "?")
                caminho.append(f"Supervisor→{decisao}")
                print(f"\n[Supervisor] → {decisao}")
                if update.get("supervisor_reasoning"):
                    print(f"  motivo: {update['supervisor_reasoning']}")
                for m in update.get("messages", []):
                    print(f"  tarefa: {m.content[:200]}")
            else:
                caminho.append(node)
                conteudo = update["messages"][-1].content if update.get("messages") else ""
                mensagens[node] = conteudo
                if node == "Consolidador":
                    relatorio = update.get("relatorio")
                print(f"\n[{node}] ({len(conteudo)} chars)\n{conteudo[:600]}{'...' if len(conteudo) > 600 else ''}")

    return {"caminho": caminho, "mensagens": mensagens, "relatorio": relatorio, "loops": loops}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--espera-investigator", action="store_true")
    grupo.add_argument("--espera-sem-investigator", action="store_true")
    args = parser.parse_args()

    resultado = rodar(args.ticker)
    ativou = "Investigator" in resultado["mensagens"]

    print("\n" + "=" * 60)
    print(f"Ticker:        {args.ticker.upper()}")
    print(f"Caminho:       {' | '.join(resultado['caminho'])}")
    print(f"Loops:         {resultado['loops']} (hard stop em {HARD_STOP})")
    print(f"Investigator:  {'ATIVADO' if ativou else 'não ativado'}")

    falhas = []
    relatorio = resultado["relatorio"]
    if not resultado["caminho"] or resultado["caminho"][-1] != "Consolidador":
        falhas.append("o fluxo não terminou no Consolidador")
    if relatorio is None:
        falhas.append("relatório estruturado ausente (o LLM do Consolidador falhou e entrou o fallback; veja o log)")
    else:
        print(f"Relatório:     {len(relatorio.indicadores)} indicadores, {len(relatorio.riscos)} riscos, "
              f"{len(relatorio.limitacoes)} limitações")
    if resultado["loops"] > HARD_STOP:
        falhas.append(f"loop_count {resultado['loops']} passou do hard stop")
    if ativou:
        diag = resultado["mensagens"]["Investigator"]
        faltando = [s for s in SECOES_DIAGNOSTICO if s.lower() not in diag.lower()]
        print(f"Diagnóstico:   {'formato completo' if not faltando else 'faltando ' + ', '.join(faltando)}")
        if faltando:
            falhas.append(f"diagnóstico sem as seções: {', '.join(faltando)}")
        final = resultado["mensagens"].get("Consolidador", "")
        perdidas = [s for s in SECOES_DIAGNOSTICO if s.lower() not in final.lower()]
        if perdidas:
            falhas.append(f"o relatório final perdeu as seções do diagnóstico: {', '.join(perdidas)}")
    if args.espera_investigator and not ativou:
        falhas.append("esperava o Investigator e ele não foi ativado")
    if args.espera_sem_investigator and ativou:
        falhas.append("não esperava o Investigator e ele foi ativado")

    for f in falhas:
        print(f"FALHA: {f}")
    print("=" * 60)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
