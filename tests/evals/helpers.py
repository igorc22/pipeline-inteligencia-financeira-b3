"""Funções puras dos evals. Não importa nada da deepeval.

Vivem aqui e não no conftest porque fixture do pytest não é importável, e tanto os módulos de eval
quanto o próprio conftest precisam delas. Por não tocarem na deepeval nem na rede, são testadas
offline em test_helpers.py, na suíte padrão.
"""
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from langchain_core.messages import BaseMessage, messages_from_dict

PASTA_EVALS = Path(__file__).parent
NOTAS_CSV = PASTA_EVALS / "notas.csv"
FALHAS_DIR = PASTA_EVALS / "_falhas"
FIXTURES_DIR = PASTA_EVALS / "fixtures"

# Orçamento do juiz, não da produção: a produção recebe tudo, o eval corta para a chamada ao juiz
# não estourar o tempo limite da deepeval. Mudar estes valores só por timeout, nunca para uma nota passar.
MAX_FONTES = 20
MAX_CHARS_POR_FONTE = 6000

# Juiz diferente do modelo julgado (gemini-3.5-flash-lite), para o modelo não corrigir a própria prova.
# O 2.5-flash era a primeira escolha, mas a API recusa o modelo para chaves novas (404) e sugere o 3.8-flash.
# O 3.8-flash tem preço registrado na deepeval (custo_usd preenchido). Temperatura não é enviada (None):
# fica o padrão do Google, que ele recomenda para o Gemini 3+.
JUIZ_PADRAO = "gemini-3.8-flash"
TEMPERATURA_JUIZ = None

# Texto que o ToolCallLimitMiddleware devolve no lugar da busca que passou do teto: não é evidência.
AVISO_LIMITE = "Tool call limit exceeded"

# Quem entra no contexto de um agente além das tools dele: o pedido (sem name), a resposta do YFinance
# (com os sinais calculados em código) e as tarefas do Supervisor. Respostas de Analyzer e Investigator
# ficam de fora: são saída de LLM, e um fato inventado numa passagem contaria como fiel na seguinte.
NOMES_NO_CONTEXTO = (None, "YFinance", "Supervisor")

CABECALHO = ["data", "fixture", "teste", "metrica", "nota", "threshold", "passou", "custo_usd", "juiz"]


# ---------------------------------------------------------------------------
# notas.csv e despejo das falhas
# ---------------------------------------------------------------------------

def _escrever_linha(caminho: Path, campos: list) -> None:
    novo = not caminho.exists()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if novo:
            writer.writerow(CABECALHO)
        writer.writerow([datetime.now(timezone.utc).isoformat(), *campos])


def registrar(fixture: str, teste: str, metric, juiz: str, caminho: Path = NOTAS_CSV) -> None:
    """Acrescenta uma linha ao notas.csv, passando ou não. O cabeçalho entra só na primeira.

    O custo vem de metric.evaluation_cost (a deepeval calcula com o preço do modelo registrado; modelo
    sem preço deixa a coluna vazia). O LangSmith não vê as chamadas do juiz: o custo dos evals só fica aqui.
    """
    custo = getattr(metric, "evaluation_cost", None)
    _escrever_linha(caminho, [
        fixture, teste, metric.__name__, metric.score, metric.threshold, metric.success,
        "" if custo is None else custo, juiz,
    ])


def registrar_erro(fixture: str, teste: str, excecao: Exception, juiz: str, caminho: Path = NOTAS_CSV) -> None:
    """Acrescenta uma linha quando measure() quebra (timeout, 429) em vez de reprovar.

    Sem isso a tentativa some do notas.csv sem deixar rastro.
    """
    _escrever_linha(caminho, [fixture, teste, type(excecao).__name__, "", "", "erro", "", juiz])


def _bloco_contexto(tc) -> str:
    contexto = getattr(tc, "retrieval_context", None)
    if not contexto:
        return ""
    itens = "\n\n".join(f"[{i}]\n{texto}" for i, texto in enumerate(contexto, start=1))
    return f"\n\nretrieval_context ({len(contexto)} itens, já cortados por limitar_fontes):\n\n{itens}"


def despejar(fixture: str, teste: str, metric, tc, diretorio: Path = FALHAS_DIR) -> Path:
    """Na reprovação, grava entrada, saída, vereditos e o contexto que o juiz teve num arquivo, em vez de
    estourar dezenas de milhares de caracteres na mensagem do assert. Devolve o caminho do arquivo.

    O contexto vai um item por bloco numerado, para achar o trecho que o juiz tinha ao ler um veredito.
    """
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho = diretorio / f"{fixture}-{teste}.txt"
    caminho.write_text(
        f"input:\n{tc.input}\n\nactual_output:\n{tc.actual_output}\n\n{formatar(metric)}{_bloco_contexto(tc)}",
        encoding="utf-8",
    )
    return caminho


def _rotulo(verdict: str) -> str:
    """'no' contradiz a fonte: o texto tem de mudar. 'idk' é a fonte não ter falado daquilo: o texto
    pode estar certo mesmo assim. Rótulos iguais escondiam essa diferença.
    """
    return "[contradiz]" if verdict.strip().lower() == "no" else "[nao confirmado]"


def formatar(metric) -> str:
    """Mensagem de um eval reprovado: a nota e o veredito item a item.

    A nota sozinha não diz o que mudar. Cada métrica guarda os vereditos num campo diferente, lido por
    hasattr, então não é preciso importar os tipos da deepeval.
    """
    linhas = [f"{metric.__name__}: {metric.score:.2f} (threshold {metric.threshold})"]
    if metric.reason:
        linhas.append(f"\n{metric.reason}\n")

    # Summarization: alinhamento (o resumo contradiz o original?) e cobertura (o que ficou de fora).
    if hasattr(metric, "alignment_verdicts"):
        linhas.append(f"breakdown: {metric.score_breakdown}\n")
        for v in metric.alignment_verdicts:
            if v.verdict.strip().lower() == "yes":
                continue
            linhas.append(f"{_rotulo(v.verdict)} {v.reason}")
        for v in metric.coverage_verdicts:
            no_original = v.original_verdict.strip().lower() == "yes"
            no_resumo = v.summary_verdict.strip().lower() == "yes"
            if no_original and not no_resumo:
                linhas.append(f"[ficou de fora] {v.question}")

    # Faithfulness: um veredito por afirmação extraída do texto avaliado.
    elif hasattr(metric, "claims") and hasattr(metric, "verdicts"):
        for claim, v in zip(metric.claims, metric.verdicts):
            if v.verdict == "yes":
                continue
            linhas.append(f"{_rotulo(v.verdict)} {claim}")
            if v.reason:
                linhas.append(f"       -> {v.reason}")

    # Contextual Relevancy: um grupo de vereditos por fonte.
    elif hasattr(metric, "verdicts_list"):
        for i, grupo in enumerate(metric.verdicts_list):
            for v in grupo.verdicts:
                if v.verdict.strip().lower() == "yes":
                    continue
                linhas.append(f"[fonte {i}] {v.statement[:150]}")
                if v.reason:
                    linhas.append(f"       -> {v.reason}")

    # GEval não produz vereditos: só nota e justificativa, já incluídas acima.
    return "\n".join(linhas)


def medir_e_registrar(metric, tc, fixture: str, teste: str, juiz: str,
                      caminho: Path = NOTAS_CSV, diretorio: Path = FALHAS_DIR) -> None:
    """Mede sempre, registra a nota passando ou não, e só reprova o teste se a métrica reprovar.

    measure() que quebra (timeout, 429) vira linha 'erro' no CSV e a exceção sobe: o teste não passa
    em silêncio, nem dentro de um xfail(raises=pytest.fail.Exception). Reprovação despeja entrada,
    saída, vereditos e contexto em _falhas/ e a mensagem aponta para o arquivo.
    """
    try:
        metric.measure(tc)
    except Exception as e:
        registrar_erro(fixture, teste, e, juiz, caminho=caminho)
        raise
    registrar(fixture, teste, metric, juiz, caminho=caminho)
    if not metric.success:
        caminho_despejo = despejar(fixture, teste, metric, tc, diretorio=diretorio)
        pytest.fail(f"{formatar(metric)}\n\nentrada, saída e contexto em {caminho_despejo}")


# ---------------------------------------------------------------------------
# Leitura da fixture
# ---------------------------------------------------------------------------

def limitar_fontes(textos: list[str], max_fontes: int = MAX_FONTES, max_chars: int = MAX_CHARS_POR_FONTE) -> list[str]:
    """Corta a lista de textos do contexto no orçamento do juiz: no máximo max_fontes itens com no
    máximo max_chars caracteres cada. A produção não corta nada; test_fixture.py confere que, nas
    fixtures geradas, este corte não tira nada."""
    return [texto[:max_chars] for texto in textos[:max_fontes]]


def carregar_fixture(caminho: Path) -> dict:
    """Lê a fixture em UTF-8 (a localidade desta máquina é cp1252). Sem o arquivo, pula o teste."""
    if not caminho.exists():
        pytest.skip("fixture ausente: gere com make eval-fixtures")
    return json.loads(caminho.read_text(encoding="utf-8"))


def mensagens(estado: dict) -> list[BaseMessage]:
    """Mensagens do state final, de volta a objetos do LangChain."""
    return messages_from_dict(estado["messages"])


def _texto(mensagem: BaseMessage) -> str:
    return mensagem.content if isinstance(mensagem.content, str) else mensagem.text


def _indice_da_resposta(msgs: list[BaseMessage], agente: str, n: int) -> int | None:
    """Posição da n-ésima resposta do agente no histórico, ou None se ele não respondeu n vezes."""
    contagem = 0
    for i, m in enumerate(msgs):
        if m.name == agente:
            contagem += 1
            if contagem == n:
                return i
    return None


def resposta_do_agente(estado: dict, agente: str, n: int = 1) -> str | None:
    """Texto da n-ésima resposta do agente, ou None (fixture sem Investigator, por exemplo)."""
    msgs = mensagens(estado)
    indice = _indice_da_resposta(msgs, agente, n)
    return None if indice is None else _texto(msgs[indice])


def tarefa_do_supervisor(estado: dict, agente: str, n: int = 1) -> str | None:
    """Texto da última mensagem do Supervisor antes da n-ésima resposta do agente, ou None."""
    msgs = mensagens(estado)
    indice = _indice_da_resposta(msgs, agente, n)
    if indice is None:
        return None
    return next((_texto(m) for m in reversed(msgs[:indice]) if m.name == "Supervisor"), None)


def contexto_do_agente(estado: dict, agente: str, n: int = 1) -> list[str]:
    """O que o agente tinha em mãos na n-ésima passagem, um texto por item.

    Primeiro as saídas das tools daquela passagem ("<tool>: <conteúdo>"), sem o aviso de limite de
    buscas. Depois as mensagens anteriores à resposta cujo name está em NOMES_NO_CONTEXTO
    ("<name ou Usuario>: <texto>"). Passagem sem tool (a busca falhou e o agente respondeu do
    histórico) devolve só o histórico permitido.
    """
    passagem = next((p for p in estado["passagens"] if p["agente"] == agente and p["n"] == n), None)
    tools = passagem["tools"] if passagem else []
    contexto = [f"{t['nome']}: {t['conteudo']}" for t in tools if AVISO_LIMITE not in t["conteudo"]]

    msgs = mensagens(estado)
    indice = _indice_da_resposta(msgs, agente, n)
    anteriores = msgs if indice is None else msgs[:indice]
    contexto += [f"{m.name or 'Usuario'}: {_texto(m)}" for m in anteriores if m.name in NOMES_NO_CONTEXTO]
    return contexto
