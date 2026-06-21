from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from rule_agent_nodes import (
    RuleAgentState,
    example_generator_node,
    final_response_node,
    finance_relevance_node,
    normalize_rule_request,
    route_after_audit,
    route_after_build,
    route_after_cache,
    route_after_relevance,
    rule_auditor_node,
    rule_builder_node,
    rule_validator_node,
)


def create_rule_builder_graph():
    graph = StateGraph(RuleAgentState)
    graph.add_node("normalize", normalize_rule_request)
    graph.add_node("finance_relevance", finance_relevance_node)
    graph.add_node("rule_builder", rule_builder_node)
    graph.add_node("rule_validator", rule_validator_node)
    graph.add_node("rule_auditor", rule_auditor_node)
    graph.add_node("example_generator", example_generator_node)
    graph.add_node("final_response", final_response_node)

    graph.set_entry_point("normalize")
    graph.add_conditional_edges("normalize", route_after_cache, {"done": END, "continue": "finance_relevance"})
    graph.add_conditional_edges("finance_relevance", route_after_relevance, {"done": END, "continue": "rule_builder"})
    graph.add_conditional_edges("rule_builder", route_after_build, {"done": END, "continue": "rule_validator"})
    graph.add_edge("rule_validator", "rule_auditor")
    graph.add_conditional_edges("rule_auditor", route_after_audit, {"done": END, "continue": "example_generator"})
    graph.add_edge("example_generator", "final_response")
    graph.add_edge("final_response", END)
    return graph.compile()


rule_builder_app = create_rule_builder_graph()


def run_rule_builder_agent(
    natural_language_rule: str,
    portfolio_symbols: list[str],
    base_currency: str = "EUR",
    risk_level: str = "safe",
    new_asset_mode: str = "portfolio_only",
) -> dict[str, Any]:
    state: RuleAgentState = {
        "natural_language_rule": natural_language_rule,
        "portfolio_symbols": portfolio_symbols,
        "base_currency": base_currency,
        "risk_level": risk_level,
        "new_asset_mode": new_asset_mode,
    }
    result = rule_builder_app.invoke(state)
    return result["result"]
