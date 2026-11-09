"""Tipos do subgrafo de pesquisa e a formatação do diagnóstico (as 4 linhas-contrato)."""
import pytest
from pydantic import ValidationError

from fluxo_financeiro.shared.types import (
    CriticaPesquisa,
    DiagnosticoPesquisa,
    PerguntasPesquisa,
    PesquisaFeita,
    formatar_diagnostico,
)

LINHAS_CONTRATO = (
    "- Causa identificada:",
    "- Natureza do evento:",
    "- Evidências:",
    "- Impacto no investimento:",
)


def _diagnostico(**campos) -> DiagnosticoPesquisa:
    base = {
        "causa": "impairment de níquel",
        "natureza": "pontual",
        "evidencias": ["baixa contábil de US$ 2B no 3T26", "lucro dos trimestres anteriores estável"],
        "impacto": "o lucro recorrente segue no patamar anterior",
    }
    return DiagnosticoPesquisa(**{**base, **campos})


def test_formatar_diagnostico_tem_as_quatro_linhas_em_ordem():
    """Confere que o texto traz as 4 linhas-contrato, uma por linha e na ordem que o e2e e o Consolidador esperam."""
    texto = formatar_diagnostico(_diagnostico(), [])

    linhas = texto.splitlines()
    for prefixo, linha in zip(LINHAS_CONTRATO, linhas):
        assert linha.startswith(prefixo)
    assert linhas[0] == "- Causa identificada: impairment de níquel"
    assert linhas[1] == "- Natureza do evento: pontual"
    assert linhas[3] == "- Impacto no investimento: o lucro recorrente segue no patamar anterior"


def test_formatar_diagnostico_une_evidencias_na_mesma_linha():
    """Confere que as evidências ficam numa linha só, separadas por '; '."""
    texto = formatar_diagnostico(_diagnostico(), [])

    assert "- Evidências: baixa contábil de US$ 2B no 3T26; lucro dos trimestres anteriores estável" in texto.splitlines()


def test_formatar_diagnostico_sem_ponto_antes_do_separador():
    """Confere que a frase do LLM que termina em ponto não sai como '.;' (aconteceu no e2e da VALE3)."""
    texto = formatar_diagnostico(_diagnostico(evidencias=["Lucro caiu 53%.", "Impairment de US$ 242 mi. "]), [])

    assert "- Evidências: Lucro caiu 53%; Impairment de US$ 242 mi" in texto.splitlines()


def test_formatar_diagnostico_sem_evidencias_mantem_a_linha():
    """Confere que, sem evidências, a linha continua lá e diz que não houve evidência, sem ficar vazia."""
    texto = formatar_diagnostico(_diagnostico(evidencias=[]), [])

    linha = next(l for l in texto.splitlines() if l.startswith("- Evidências:"))
    assert linha.removeprefix("- Evidências:").strip()


def test_formatar_diagnostico_com_fontes_termina_com_elas():
    """Confere que as fontes entram numa linha 'Fontes: a, b' no fim."""
    texto = formatar_diagnostico(_diagnostico(), ["valor.com.br", "infomoney.com.br"])

    assert texto.splitlines()[-1] == "Fontes: valor.com.br, infomoney.com.br"


def test_formatar_diagnostico_sem_fontes_nao_tem_a_linha():
    """Confere que, sem fontes, o texto termina no impacto, sem uma linha 'Fontes:' vazia."""
    texto = formatar_diagnostico(_diagnostico(), [])

    assert "Fontes:" not in texto
    assert texto.splitlines()[-1].startswith("- Impacto no investimento:")


@pytest.mark.parametrize("natureza", ["pontual", "estrutural", "cíclico", "indeterminado"])
def test_diagnostico_aceita_as_quatro_naturezas(natureza):
    """Confere que as quatro naturezas do evento são aceitas e saem como estão na linha da natureza."""
    texto = formatar_diagnostico(_diagnostico(natureza=natureza), [])

    assert f"- Natureza do evento: {natureza}" in texto


def test_diagnostico_recusa_natureza_fora_da_lista():
    """Confere que uma natureza fora das quatro previstas é recusada pela validação."""
    with pytest.raises(ValidationError):
        _diagnostico(natureza="sazonal")


def test_perguntas_e_lacunas_acima_do_limite_nao_quebram_a_validacao():
    """Confere que o limite de perguntas e de lacunas não é imposto pela validação: o subgrafo corta em código."""
    perguntas = PerguntasPesquisa(perguntas=["a?", "b?", "c?", "d?", "e?"])
    critica = CriticaPesquisa(aprovado=False, lacunas=["x?", "y?", "z?"])

    assert len(perguntas.perguntas) == 5
    assert len(critica.lacunas) == 3


def test_pesquisa_feita_guarda_perguntas_achados_e_voltas():
    """Confere que o registro da pesquisa guarda as perguntas, os achados por rodada e as voltas do crítico."""
    feita = PesquisaFeita(
        perguntas=["Por que o lucro caiu?"],
        achados=[{"pergunta": "Por que o lucro caiu?", "rodada": 0, "texto": "impairment"}],
        voltas=1,
    )

    assert feita.achados[0]["rodada"] == 0
    assert feita.voltas == 1
