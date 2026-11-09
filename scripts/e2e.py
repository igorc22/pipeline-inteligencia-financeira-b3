"""Roda o grafo completo para um ticker (chamadas REAIS: gasta créditos de API) e mostra o caminho percorrido.

Uso:
    uv run python scripts/e2e.py VALE3
    uv run python scripts/e2e.py VALE3 --espera-investigator
    uv run python scripts/e2e.py WEGE3 --espera-sem-investigator

Com --espera-*, o script sai com código 1 se o comportamento não for o esperado.
"""
import argparse
import sys
import time

from langchain_core.messages import HumanMessage

from fluxo_financeiro import app
from fluxo_financeiro.shared.config import SANITIZACAO_ATIVA
from fluxo_financeiro.shared.prompts import TAG_CONTEUDO_EXTERNO
from fluxo_financeiro.shared.utils import TICKER_INVALIDO, validar_ticker

SECOES_DIAGNOSTICO = ["Causa", "Natureza", "Evidências", "Impacto"]
HARD_STOP = 6


def conferir_diagnostico(diag: str, final: str) -> list[str]:
    """Falhas do diagnóstico: seções faltando no texto do Investigator, ou o texto dele fora do relatório final.

    O Consolidador copia o diagnóstico literalmente (D41); procurar só as quatro palavras deixaria
    passar um relatório que resumiu ou reescreveu o diagnóstico.
    """
    falhas = []
    faltando = [s for s in SECOES_DIAGNOSTICO if s.lower() not in diag.lower()]
    if faltando:
        falhas.append(f"diagnóstico sem as seções: {', '.join(faltando)}")
    if diag.strip() not in final:
        falhas.append("o relatório final não traz o diagnóstico do Investigator na íntegra")
    return falhas


def conferir_tags_vazadas(mensagens: list[tuple[str, str]]) -> list[str]:
    """Agentes cuja resposta repetiu a tag <conteudo_externo> (D47), na ordem, sem repetir nomes.

    A tag é para o agente ler, não para aparecer no relatório e no dashboard. Só avisa: vazar
    a tag não muda a análise, então o e2e não reprova por isso.
    """
    return list(dict.fromkeys(nome for nome, texto in mensagens if f"<{TAG_CONTEUDO_EXTERNO}" in texto))


def rodar(ticker: str) -> dict:
    t_inicio = time.perf_counter()
    caminho: list[str] = []
    mensagens: dict[str, str] = {}
    todas: list[tuple[str, str]] = []  # cada resposta (o Analyzer fala duas vezes; o dict guarda só a última)
    relatorio = None
    loops = 0

    initial = {"messages": [HumanMessage(content=f"Analise a ação {ticker}")]}
    for event in app.stream(initial):
        for node, update in event.items():
            update = update or {}
            loops += update.get("loop_count", 0)
            if node == "Supervisor":
                decisao = update.get("next_agent", "?")
                rotulo = f"[{decisao}]" if decisao == "Analyzer+Investigator" else decisao
                caminho.append(f"Supervisor→{rotulo}")
                print(f"\n[Supervisor] → {rotulo}")
                if update.get("supervisor_reasoning"):
                    print(f"  motivo: {update['supervisor_reasoning']}")
                for m in update.get("messages", []):
                    print(f"  tarefa: {m.content[:200]}")
            else:
                caminho.append(node)
                conteudo = update["messages"][-1].content if update.get("messages") else ""
                mensagens[node] = conteudo
                todas.append((node, conteudo))
                if node == "Consolidador":
                    relatorio = update.get("relatorio")
                print(f"\n[{node}] ({len(conteudo)} chars)\n{conteudo[:600]}{'...' if len(conteudo) > 600 else ''}")

    tempo_total = time.perf_counter() - t_inicio
    return {
        "caminho": caminho,
        "mensagens": mensagens,
        "todas": todas,
        "relatorio": relatorio,
        "loops": loops,
        "tempo_total": tempo_total,
    }


def main(argv: list[str] | None = None) -> int:
    # Importado aqui para o patch no módulo de origem valer nos testes.
    from fluxo_financeiro.tools.brapi import mensagem_ticker_inexistente, ticker_existe

    parser = argparse.ArgumentParser()
    parser.add_argument("ticker")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--espera-investigator", action="store_true")
    grupo.add_argument("--espera-sem-investigator", action="store_true")
    args = parser.parse_args(argv)

    ticker = validar_ticker(args.ticker)
    if ticker is None:
        print(TICKER_INVALIDO)
        return 2
    if ticker_existe(ticker) is False:  # None (Brapi sem resposta) segue
        print(mensagem_ticker_inexistente(ticker))
        return 2

    resultado = rodar(ticker)
    ativou = "Investigator" in resultado["mensagens"]

    print("\n" + "=" * 60)
    print(f"Ticker:        {ticker}")
    print(f"Caminho:       {' | '.join(resultado['caminho'])}")
    print(f"Loops:         {resultado['loops']} (hard stop em {HARD_STOP})")
    print(f"Investigator:  {'ATIVADO' if ativou else 'não ativado'}")
    print(f"Sanitização:   {'LIGADA' if SANITIZACAO_ATIVA else 'desligada'} (SANITIZACAO_ATIVA)")
    tempo = resultado.get("tempo_total", 0.0)
    print(f"Tempo total:   {tempo:.1f} s")
    vazaram = conferir_tags_vazadas(resultado["todas"])
    if vazaram:
        print(f"AVISO: tags de conteúdo externo vazaram nas mensagens de: {', '.join(vazaram)}")

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
        problemas = conferir_diagnostico(resultado["mensagens"]["Investigator"],
                                         resultado["mensagens"].get("Consolidador", ""))
        print(f"Diagnóstico:   {'completo e copiado na íntegra' if not problemas else '; '.join(problemas)}")
        falhas += problemas
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
