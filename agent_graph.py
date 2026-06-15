from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from agent_nodes import analyze_financial_data, build_initial_state, fetch_web_context, fetch_yfinance_data


class AnalysisState(TypedDict, total=False):
    symbol: str
    name: str | None
    template: dict[str, bool]
    instructions: dict[str, str]
    financial_data: dict[str, Any]
    web_context: dict[str, Any]
    analysis: dict[str, Any]


def create_graph():
    graph = StateGraph(AnalysisState)
    graph.add_node("fetch_yfinance_data", fetch_yfinance_data)
    graph.add_node("fetch_web_context", fetch_web_context)
    graph.add_node("analyze_financial_data", analyze_financial_data)
    graph.set_entry_point("fetch_yfinance_data")
    graph.add_edge("fetch_yfinance_data", "fetch_web_context")
    graph.add_edge("fetch_web_context", "analyze_financial_data")
    graph.add_edge("analyze_financial_data", END)
    return graph.compile()


app = create_graph()


def run_agent_analysis(
    symbol: str,
    name: str | None = None,
    template: dict[str, Any] | None = None,
    instructions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = build_initial_state(symbol=symbol, name=name, template=template, instructions=instructions)
    result = app.invoke(state)
    return result["analysis"]
