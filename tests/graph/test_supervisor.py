import pytest
from unittest.mock import patch
from fluxo_financeiro.graph.supervisor import supervisor_node, router
from fluxo_financeiro.shared.types import MessagesState
from langchain_core.messages import HumanMessage


def test_supervisor_node_hard_stop():
    """Test that supervisor enforces hard stop at 3 loops."""
    state: MessagesState = {
        "messages": [HumanMessage(content="test")],
        "next_agent": "YFinance",
        "loop_count": 3
    }
    result = supervisor_node(state)
    assert result["next_agent"] == "FINISH"


def test_router_finish():
    """Test that router returns __end__ for FINISH."""
    state: MessagesState = {
        "messages": [HumanMessage(content="test")],
        "next_agent": "FINISH",
        "loop_count": 1
    }
    assert router(state) == "__end__"


def test_router_yfinance():
    """Test that router returns node name for valid agents."""
    state: MessagesState = {
        "messages": [HumanMessage(content="test")],
        "next_agent": "YFinance",
        "loop_count": 1
    }
    assert router(state) == "YFinance"
