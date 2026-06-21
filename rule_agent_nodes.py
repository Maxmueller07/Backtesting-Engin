from __future__ import annotations

from typing import Any, TypedDict

from ai_rule_builder import (
    allows_new_assets,
    annotate_new_assets,
    build_rule_draft,
    cache_rule_build,
    check_finance_relevance,
    example_tests_for_rule,
    finalize_rule,
    finalize_rule_bundle,
    get_cached_rule_build,
    normalize_new_asset_mode,
    normalize_symbol_list,
    prepare_symbol_universe,
)
from custom_rule_engine import ALLOWED_ACTIONS, ALLOWED_OPERATORS, supported_indicators, validate_custom_rule


class RuleAgentState(TypedDict, total=False):
    natural_language_rule: str
    portfolio_symbols: list[str]
    original_portfolio_symbols: list[str]
    base_currency: str
    risk_level: str
    new_asset_mode: str
    allow_new_assets: bool
    new_asset_candidates: list[dict[str, Any]]
    relevance: dict[str, Any]
    draft_rule: dict[str, Any]
    draft_rules: list[dict[str, Any]]
    validation: dict[str, Any]
    audit: dict[str, Any]
    example_tests: list[dict[str, Any]]
    explanation: str
    warnings: list[str]
    self_healing: dict[str, Any]
    auto_extensions: list[dict[str, Any]]
    auto_extension_trace: dict[str, Any]
    result: dict[str, Any]


def normalize_rule_request(state: RuleAgentState) -> RuleAgentState:
    text = str(state.get("natural_language_rule") or "").strip()
    original_symbols = normalize_symbol_list(state.get("portfolio_symbols", []))
    mode = normalize_new_asset_mode(state.get("new_asset_mode"))
    symbols, new_asset_candidates = prepare_symbol_universe(text, original_symbols, mode)
    cached = get_cached_rule_build(text, symbols, mode)
    update: RuleAgentState = {
        "natural_language_rule": text,
        "portfolio_symbols": symbols,
        "original_portfolio_symbols": original_symbols,
        "base_currency": state.get("base_currency") or "EUR",
        "risk_level": state.get("risk_level") or "safe",
        "new_asset_mode": mode,
        "allow_new_assets": allows_new_assets(mode),
        "new_asset_candidates": new_asset_candidates,
        "warnings": [],
    }
    if cached:
        update["result"] = {**cached, "cache_hit": True}
    return update


def finance_relevance_node(state: RuleAgentState) -> RuleAgentState:
    relevance = check_finance_relevance(state["natural_language_rule"])
    if not relevance["is_relevant"]:
        result = {
            "status": "error",
            "code": "not_finance_related",
            "message": "Die Regel wirkt nicht wie eine Finanz-, Portfolio- oder Backtesting-Regel.",
            "reason": relevance["reason"],
        }
        cache_rule_build(state["natural_language_rule"], state["portfolio_symbols"], result, state.get("new_asset_mode", "portfolio_only"))
        return {"relevance": relevance, "result": result}
    return {"relevance": relevance}


def rule_builder_node(state: RuleAgentState) -> RuleAgentState:
    draft = build_rule_draft(
        state["natural_language_rule"],
        state["portfolio_symbols"],
        state.get("base_currency", "EUR"),
        state.get("risk_level", "safe"),
        allow_new_assets=state.get("allow_new_assets", False),
    )
    if draft.get("status") != "ok":
        cache_rule_build(state["natural_language_rule"], state["portfolio_symbols"], draft, state.get("new_asset_mode", "portfolio_only"))
        return {"result": draft}
    return {
        "draft_rules": draft["rules"] if "rules" in draft else [],
        "draft_rule": draft["rule"] if "rule" in draft else {},
        "explanation": draft.get("explanation", ""),
        "warnings": draft.get("warnings", []),
        "self_healing": draft.get("self_healing", {}),
        "auto_extensions": draft.get("auto_extensions", []),
        "auto_extension_trace": draft.get("auto_extension_trace", {}),
    }


def rule_validator_node(state: RuleAgentState) -> RuleAgentState:
    if state.get("draft_rules"):
        normalized_rules = []
        errors = []
        warnings = []
        for index, rule in enumerate(state["draft_rules"]):
            validation = validate_custom_rule(
                rule,
                state["portfolio_symbols"],
                allow_new_assets=state.get("allow_new_assets", False),
            )
            if validation.get("valid"):
                normalized_rules.append(validation["rule"])
            else:
                errors.extend([{**error, "rule_index": index} for error in validation.get("errors", [])])
            warnings.extend(validation.get("warnings", []))
        return {
            "validation": {
                "status": "ok" if not errors else "error",
                "valid": not errors,
                "errors": errors,
                "warnings": warnings,
                "rules": normalized_rules,
            }
        }

    validation = validate_custom_rule(
        state["draft_rule"],
        state["portfolio_symbols"],
        allow_new_assets=state.get("allow_new_assets", False),
    )
    return {"validation": validation}


def rule_auditor_node(state: RuleAgentState) -> RuleAgentState:
    validation = state["validation"]
    warnings = list(state.get("warnings", []))
    audit = {
        "status": "ok" if validation.get("valid") else "error",
        "checks": [
            "json_schema_validated",
            "portfolio_symbols_checked",
            "operators_allowlisted",
            "actions_allowlisted",
            "indicators_allowlisted",
            "no_code_execution",
        ],
        "allowed_actions": sorted(ALLOWED_ACTIONS),
        "allowed_indicators": sorted(supported_indicators()),
        "allowed_operators": sorted(ALLOWED_OPERATORS),
    }

    if not validation.get("valid"):
        result = {
            "status": "error",
            "code": "validation_failed",
            "message": "Die erzeugte Regel ist nicht valide.",
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []) + warnings,
            "audit": audit,
        }
        cache_rule_build(state["natural_language_rule"], state["portfolio_symbols"], result, state.get("new_asset_mode", "portfolio_only"))
        return {"audit": audit, "result": result}

    return {"audit": audit, "warnings": validation.get("warnings", []) + warnings}


def example_generator_node(state: RuleAgentState) -> RuleAgentState:
    if "rules" in state["validation"]:
        examples = []
        for rule in state["validation"]["rules"]:
            for example in example_tests_for_rule(rule)["example_tests"]:
                examples.append({"rule_id": rule.get("id"), **example})
        return {"example_tests": examples}
    examples = example_tests_for_rule(state["validation"]["rule"])["example_tests"]
    return {"example_tests": examples}


def final_response_node(state: RuleAgentState) -> RuleAgentState:
    if "rules" in state["validation"]:
        finalized = finalize_rule_bundle(
            state["validation"]["rules"],
            state["portfolio_symbols"],
            state.get("explanation", ""),
            state.get("warnings", []),
            allow_new_assets=state.get("allow_new_assets", False),
        )
    else:
        finalized = finalize_rule(
            state["validation"]["rule"],
            state["portfolio_symbols"],
            state.get("explanation", ""),
            state.get("warnings", []),
            allow_new_assets=state.get("allow_new_assets", False),
        )
    if finalized.get("status") == "ok":
        finalized = annotate_new_assets(
            finalized,
            state.get("original_portfolio_symbols", []),
            state.get("new_asset_mode", "portfolio_only"),
            state.get("new_asset_candidates", []),
        )
        finalized["example_tests"] = state.get("example_tests", finalized.get("example_tests", []))
        finalized["audit"] = state.get("audit", {})
        finalized["relevance"] = state.get("relevance", {})
        finalized["agent"] = "langgraph_rule_builder"
        if state.get("self_healing"):
            finalized["self_healing"] = state["self_healing"]
        if state.get("auto_extensions"):
            finalized["auto_extensions"] = state["auto_extensions"]
        if state.get("auto_extension_trace"):
            finalized["auto_extension_trace"] = state["auto_extension_trace"]
    cache_rule_build(state["natural_language_rule"], state["portfolio_symbols"], finalized, state.get("new_asset_mode", "portfolio_only"))
    return {"result": finalized}


def route_after_cache(state: RuleAgentState) -> str:
    return "done" if state.get("result") else "continue"


def route_after_relevance(state: RuleAgentState) -> str:
    return "done" if state.get("result") else "continue"


def route_after_build(state: RuleAgentState) -> str:
    return "done" if state.get("result") else "continue"


def route_after_audit(state: RuleAgentState) -> str:
    return "done" if state.get("result") else "continue"
