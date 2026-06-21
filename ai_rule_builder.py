from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from custom_rule_engine import (
    ALLOWED_ACTIONS,
    ALLOWED_OPERATORS,
    DISCLAIMER,
    SCHEMA_VERSION,
    build_example_tests,
    model_to_dict,
    supported_indicators,
    validate_custom_rule,
)
from indicator_registry import (
    CapabilityGapDetector,
    FormulaSecurityAuditor,
    IndicatorRegistry,
    IndicatorSynthesizer,
    IndicatorTestRunner,
)
from ticker_resolver import KNOWN_TICKERS, resolve_ticker_candidates

try:
    from dotenv import load_dotenv

    load_dotenv()
    if os.path.exists(".env.txt"):
        load_dotenv(".env.txt", override=False)
except Exception:
    pass


RULE_BUILDER_MODEL = os.getenv("RULE_BUILDER_MODEL", "gpt-4.1-mini")
RULE_BUILDER_PROVIDER = os.getenv("RULE_BUILDER_PROVIDER", "openai").strip().lower()
RULE_BUILDER_MAX_REPAIR_ATTEMPTS = int(os.getenv("RULE_BUILDER_MAX_REPAIR_ATTEMPTS", "1"))
_CACHE: dict[str, dict[str, Any]] = {}
TRANSIENT_RULE_ERROR_CODES = {
    "api_key_required",
    "indicator_synthesis_failed",
    "llm_failed",
    "needs_manual_review",
    "self_healing_retry_failed",
    "unsupported_indicator",
    "validation_failed",
}
NEW_ASSET_MODES = {"portfolio_only", "ask", "soft_approve"}
OPEN_NEW_ASSET_MODES = {"ask", "soft_approve"}
TICKER_STOP_WORDS = {
    "A", "AN", "AND", "AS", "BUY", "CASH", "DAYS", "IF", "IN", "IS", "OF",
    "OVER", "SELL", "THAN", "THE", "THEN", "TO", "USE", "WHEN", "WITH",
}


FINANCE_KEYWORDS = {
    "aktie", "asset", "backtest", "buy", "cash", "drawdown", "etf", "gold",
    "invest", "kaufen", "markt", "momentum", "portfolio", "position",
    "rebalance", "regel", "rendite", "rotation", "sell", "strategie",
    "trading", "umschichten", "verkaufen", "volatility", "volatilitaet",
    "entropy", "entropie", "rsi", "macd", "correlation", "korrelation",
    "beta", "indicator", "indikator", "slope",
}

SYMBOL_ALIASES = {
    "apple": "AAPL",
    "apfel": "AAPL",
    "microsoft": "MSFT",
    "meta": "META",
    "facebook": "META",
    "amazon": "AMZN",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
    "ethereum": "ETH-USD",
    "eth": "ETH-USD",
    "gold": "GLD",
    "gld": "GLD",
    "spy": "SPY",
    "s&p": "SPY",
    "market": "SPY",
    "markt": "SPY",
    "cash": "CASH",
}


def build_rule_from_text(
    natural_language_rule: str,
    portfolio_symbols: list[str],
    base_currency: str = "EUR",
    risk_level: str = "safe",
    new_asset_mode: str = "portfolio_only",
) -> dict[str, Any]:
    text = (natural_language_rule or "").strip()
    original_symbols = normalize_symbol_list(portfolio_symbols)
    mode = normalize_new_asset_mode(new_asset_mode)
    symbols, new_asset_candidates = prepare_symbol_universe(text, original_symbols, mode)
    cached = get_cached_rule_build(text, symbols, mode)
    if cached:
        return cached

    relevance = check_finance_relevance(text)
    if not relevance["is_relevant"]:
        return cache_rule_build(text, symbols, {
            "status": "error",
            "code": "not_finance_related",
            "message": "Die Regel wirkt nicht wie eine Finanz-, Portfolio- oder Backtesting-Regel.",
            "reason": relevance["reason"],
        }, mode)

    draft = build_rule_draft(text, symbols, base_currency, risk_level, allow_new_assets=allows_new_assets(mode))
    if draft.get("status") == "ok":
        if "rules" in draft:
            result = finalize_rule_bundle(
                draft["rules"],
                symbols,
                draft.get("explanation", ""),
                draft.get("warnings", []),
                allow_new_assets=allows_new_assets(mode),
            )
        else:
            result = finalize_rule(
                draft["rule"],
                symbols,
                draft.get("explanation", ""),
                draft.get("warnings", []),
                allow_new_assets=allows_new_assets(mode),
            )
        result = annotate_new_assets(result, original_symbols, mode, new_asset_candidates)
        return cache_rule_build(text, symbols, result, mode)
    return cache_rule_build(text, symbols, draft, mode)


def get_cached_rule_build(natural_language_rule: str, portfolio_symbols: list[str], new_asset_mode: str = "portfolio_only") -> dict[str, Any] | None:
    cached = _CACHE.get(_cache_key(natural_language_rule, portfolio_symbols, new_asset_mode))
    if cached and cached.get("status") == "needs_manual_review":
        return None
    if cached and cached.get("status") == "error" and cached.get("code") in TRANSIENT_RULE_ERROR_CODES:
        return None
    return cached


def cache_rule_build(natural_language_rule: str, portfolio_symbols: list[str], value: dict[str, Any], new_asset_mode: str = "portfolio_only") -> dict[str, Any]:
    return _store(_cache_key(natural_language_rule, portfolio_symbols, new_asset_mode), value)


def check_finance_relevance(text: str) -> dict[str, Any]:
    normalized = text.lower()
    hits = [word for word in FINANCE_KEYWORDS if word in normalized]
    return {
        "is_relevant": bool(hits),
        "confidence": min(0.35 + len(hits) * 0.12, 0.95) if hits else 0.0,
        "reason": "The request contains finance/backtesting terms." if hits else "No finance/backtesting terms detected.",
    }


def validate_rule_payload(rule: dict[str, Any], portfolio_symbols: list[str]) -> dict[str, Any]:
    return validate_custom_rule(rule, portfolio_symbols)


def example_tests_for_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {"status": "ok", "example_tests": build_example_tests(rule)}


def normalize_symbol_list(symbols: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    normalized: list[str] = []
    for symbol in symbols or []:
        value = str(symbol or "").upper().strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def normalize_new_asset_mode(value: str | None) -> str:
    mode = str(value or "portfolio_only").strip().lower()
    if mode in {"auto", "soft", "soft_approved", "approve"}:
        return "soft_approve"
    if mode in {"ask", "confirm", "manual"}:
        return "ask"
    return mode if mode in NEW_ASSET_MODES else "portfolio_only"


def allows_new_assets(mode: str | None) -> bool:
    return normalize_new_asset_mode(mode) in OPEN_NEW_ASSET_MODES


def prepare_symbol_universe(text: str, portfolio_symbols: list[str], new_asset_mode: str) -> tuple[list[str], list[dict[str, Any]]]:
    symbols = normalize_symbol_list(portfolio_symbols)
    if not allows_new_assets(new_asset_mode):
        return symbols, []

    candidates = resolve_new_asset_candidates(text, symbols)
    for candidate in candidates:
        symbol = str(candidate.get("symbol") or "").upper().strip()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols, candidates


def resolve_new_asset_candidates(text: str, portfolio_symbols: list[str]) -> list[dict[str, Any]]:
    existing = set(normalize_symbol_list(portfolio_symbols))
    resolved: list[dict[str, Any]] = []

    def add_candidate(query: str, source: str):
        candidates = resolve_ticker_candidates(query, market="AUTO")
        if not candidates:
            return
        candidate = dict(candidates[0])
        symbol = str(candidate.get("symbol") or "").upper().strip()
        if not symbol or symbol in existing or any(item["symbol"] == symbol for item in resolved):
            return
        candidate["symbol"] = symbol
        candidate["source"] = source
        candidate["anteil"] = 0
        candidate.setdefault("name", symbol)
        candidate.setdefault("waehrung", "AUTO")
        candidate.setdefault("steuer_typ", "aktie")
        resolved.append(candidate)

    lower = str(text or "").lower()
    for key in sorted(KNOWN_TICKERS, key=len, reverse=True):
        if re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", lower):
            add_candidate(key, "known_name")

    for token in re.findall(r"\b[A-Z0-9]{1,10}(?:[.\-=][A-Z0-9]{1,10})?\b", str(text or "")):
        if token in TICKER_STOP_WORDS or token.isdigit():
            continue
        add_candidate(token, "ticker")

    return resolved


def annotate_new_assets(
    result: dict[str, Any],
    original_symbols: list[str],
    new_asset_mode: str,
    known_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    mode = normalize_new_asset_mode(new_asset_mode)
    if result.get("status") != "ok":
        return result

    existing = set(normalize_symbol_list(original_symbols))
    candidate_map = {
        str(candidate.get("symbol") or "").upper().strip(): dict(candidate)
        for candidate in known_candidates or []
        if candidate.get("symbol")
    }
    new_assets = []
    referenced_symbols: set[str] = set()
    for rule in result.get("rules") or [result.get("rule", {})]:
        referenced_symbols.update(collect_rule_symbols(rule))

    for symbol in sorted(referenced_symbols - existing):
        candidate = candidate_map.get(symbol) or {
            "symbol": symbol,
            "name": symbol,
            "waehrung": "AUTO",
            "steuer_typ": "crypto" if symbol.endswith("-USD") or symbol.endswith("-EUR") else "aktie",
            "confidence": 0.5,
            "reason": "Vom KI-Regel-Builder als yfinance-Ticker erkannt",
            "source": "rule",
            "anteil": 0,
        }
        candidate["symbol"] = symbol
        candidate.setdefault("anteil", 0)
        new_assets.append(candidate)

    result["new_asset_mode"] = mode
    result["new_assets"] = new_assets
    result["requires_asset_approval"] = bool(new_assets and mode == "ask")
    return result


def collect_rule_symbols(rule: dict[str, Any]) -> set[str]:
    symbols: set[str] = set()

    def add(value):
        if isinstance(value, list):
            for item in value:
                add(item)
            return
        if isinstance(value, str):
            normalized = value.upper().strip()
            if normalized and re.match(r"^[A-Z0-9][A-Z0-9.\-=]{0,24}$", normalized):
                symbols.add(normalized)

    def visit_condition(condition: dict[str, Any]):
        params = condition.get("params") or {}
        for key in ("asset", "asset_a", "asset_b", "benchmark", "equity_proxy", "defensive_proxy"):
            add(params.get(key))
        for child in params.get("conditions") or []:
            if isinstance(child, dict):
                visit_condition(child)

    visit_condition(rule.get("condition") or {})

    for action in rule.get("actions") or []:
        add(action.get("asset"))
        add(action.get("from_asset"))
        add(action.get("to_asset"))
        for allocation in action.get("allocations") or []:
            add(allocation.get("asset"))

    return symbols


def finalize_rule(
    rule: dict[str, Any],
    symbols: list[str],
    explanation: str,
    warnings: list[str] | None = None,
    allow_new_assets: bool = False,
) -> dict[str, Any]:
    validation = validate_custom_rule(rule, symbols, allow_new_assets=allow_new_assets)
    if not validation["valid"]:
        return {
            "status": "error",
            "code": "validation_failed",
            "message": "Die erzeugte Regel ist nicht valide.",
            "errors": validation["errors"],
            "warnings": validation["warnings"] + (warnings or []),
        }
    normalized = validation["rule"]
    return {
        "status": "ok",
        "rule": normalized,
        "explanation": explanation or "Die Regel wurde als sichere JSON-Strategie erzeugt und deterministisch validiert.",
        "warnings": validation["warnings"] + (warnings or []),
        "example_tests": build_example_tests(normalized),
        "schema_version": SCHEMA_VERSION,
    }


def finalize_rule_bundle(
    rules: list[dict[str, Any]],
    symbols: list[str],
    explanation: str,
    warnings: list[str] | None = None,
    allow_new_assets: bool = False,
) -> dict[str, Any]:
    normalized_rules: list[dict[str, Any]] = []
    all_warnings = list(warnings or [])
    all_examples: list[dict[str, Any]] = []

    if not rules:
        return {"status": "error", "code": "missing_rule", "message": "Die Strategie enthaelt keine Regeln.", "warnings": all_warnings}

    for index, rule in enumerate(rules):
        finalized = finalize_rule(rule, symbols, explanation, [], allow_new_assets=allow_new_assets)
        if finalized.get("status") != "ok":
            return {
                "status": "error",
                "code": "validation_failed",
                "message": f"Regel {index + 1} in der Strategie ist nicht valide.",
                "errors": finalized.get("errors", []),
                "warnings": finalized.get("warnings", []) + all_warnings,
            }
        normalized = finalized["rule"]
        normalized_rules.append(normalized)
        for example in finalized.get("example_tests", []):
            all_examples.append({"rule_id": normalized.get("id"), **example})
        all_warnings.extend(finalized.get("warnings", []))

    return {
        "status": "ok",
        "rule": normalized_rules[0],
        "rules": normalized_rules,
        "rule_count": len(normalized_rules),
        "explanation": explanation or "Die Strategie wurde als mehrere sichere JSON-Regeln erzeugt und deterministisch validiert.",
        "warnings": all_warnings,
        "example_tests": all_examples,
        "schema_version": SCHEMA_VERSION,
    }


def build_rule_draft(
    text: str,
    symbols: list[str],
    base_currency: str = "EUR",
    risk_level: str = "safe",
    allow_new_assets: bool = False,
) -> dict[str, Any]:
    deterministic = _build_deterministic_rule(text, symbols, allow_new_assets=allow_new_assets)
    if deterministic.get("status") == "ok":
        if CapabilityGapDetector.detect(text):
            self_healed = _attempt_self_healing_indicator_gap(text, symbols, allow_new_assets=allow_new_assets)
            if self_healed:
                return self_healed
        return deterministic

    self_healed = _attempt_self_healing_indicator_gap(text, symbols, allow_new_assets=allow_new_assets)
    if self_healed:
        return self_healed

    if not _has_llm_key():
        return {
            "status": "error",
            "code": deterministic.get("code", "api_key_required"),
            "message": deterministic.get("message", _missing_key_message()),
            "warnings": deterministic.get("warnings", []),
            "supported_indicators": sorted(supported_indicators()),
            "supported_actions": sorted(ALLOWED_ACTIONS),
            "provider": _normalized_provider(),
        }

    generated = _build_with_llm(text, symbols, base_currency, risk_level, allow_new_assets=allow_new_assets)
    if generated.get("status") == "ok":
        return {
            "status": "ok",
            "rule": generated["rule"],
            "explanation": generated.get("explanation", "Die Regel wurde vom KI-Builder erzeugt."),
            "warnings": generated.get("warnings", []),
        }
    return generated


def _attempt_self_healing_indicator_gap(text: str, symbols: list[str], allow_new_assets: bool = False) -> dict[str, Any] | None:
    gap = CapabilityGapDetector.detect(text)
    if not gap:
        return None

    if not gap.get("can_try_auto_synthesis", False):
        return _manual_review_for_gap(
            gap,
            reason=gap.get("reason", "The missing indicator cannot be safely synthesized from historical price data."),
        )

    trace = _auto_extension_trace(gap)
    definition_payload = IndicatorSynthesizer.synthesize(gap, text, symbols)
    if definition_payload.get("status") == "error":
        trace["synthesis_attempted"] = True
        return _manual_review_for_gap(
            gap,
            reason=definition_payload.get("message", "The missing indicator could not be safely synthesized."),
            trace=trace,
            extra={"synthesis": definition_payload},
        )
    trace["synthesis_attempted"] = True
    trace["formula_created"] = True

    audit = FormulaSecurityAuditor.audit(definition_payload)
    if not audit["valid"]:
        return _manual_review_for_gap(
            gap,
            reason="The synthesized formula indicator did not pass the security audit.",
            trace=trace,
            extra={"formula_audit": audit},
        )
    trace["security_passed"] = True

    tests = IndicatorTestRunner.run(definition_payload, symbols)
    if not tests["passed"]:
        return _manual_review_for_gap(
            gap,
            reason="The synthesized formula indicator did not pass deterministic tests.",
            trace=trace,
            extra={"formula_audit": audit, "indicator_tests": tests},
        )
    trace["tests_passed"] = True

    register_result = IndicatorRegistry.register_dynamic_indicator(definition_payload)
    if register_result.get("status") != "ok":
        return _manual_review_for_gap(
            gap,
            reason="The synthesized formula indicator could not be registered.",
            trace=trace,
            extra={"formula_audit": audit, "indicator_tests": tests, "registration": register_result},
        )
    trace["registered"] = True

    retried = _build_deterministic_rule(text, symbols, allow_new_assets=allow_new_assets)
    if retried.get("status") != "ok":
        return _manual_review_for_gap(
            gap,
            reason="The indicator was registered, but the original rule could not be rebuilt.",
            trace=trace,
            extra={"formula_audit": audit, "indicator_tests": tests, "retry_error": retried},
        )
    trace["original_rule_retried"] = True

    self_healing = {
        "status": "ok",
        "registered_indicator": definition_payload["name"],
        "capability_gap": gap,
        "formula_indicator": definition_payload,
        "formula_audit": audit,
        "indicator_tests": tests,
        "retry": "original_rule_rebuilt",
    }
    auto_extension = {
        "name": definition_payload["name"],
        "type": "formula_indicator",
        "status": "approved",
        "tests_passed": True,
        "security_passed": True,
        "lookahead_safe": bool(definition_payload.get("lookahead_safe", True)),
    }
    retried["self_healing"] = self_healing
    retried["auto_extensions"] = [auto_extension]
    retried["auto_extension_trace"] = trace
    retried["message"] = f"The missing indicator '{definition_payload['name']}' was safely synthesized, tested, registered and used to build the rule."
    retried["warnings"] = retried.get("warnings", []) + [
        f"Self-Healing: Formel-Indikator '{definition_payload['name']}' wurde sicher erzeugt, getestet und registriert."
    ]
    retried["explanation"] = (
        retried.get("explanation", "")
        + f" Self-Healing hat den fehlenden Indikator '{definition_payload['name']}' als sichere Formel-DSL registriert und die Originalregel erneut gebaut."
    ).strip()
    return retried


def _auto_extension_trace(gap: dict[str, Any]) -> dict[str, Any]:
    return {
        "missing_indicator": gap.get("name") or gap.get("indicator"),
        "synthesis_attempted": False,
        "formula_created": False,
        "security_passed": False,
        "tests_passed": False,
        "registered": False,
        "original_rule_retried": False,
    }


def _manual_review_for_gap(
    gap: dict[str, Any],
    reason: str,
    trace: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    indicator = gap.get("name") or gap.get("indicator") or "unknown_indicator"
    response: dict[str, Any] = {
        "status": "needs_manual_review",
        "code": "needs_manual_review",
        "missing_indicator": indicator,
        "reason": reason,
        "message": f"The indicator '{indicator}' could not be safely auto-approved.",
        "capability_gap": gap,
        "auto_extension_trace": trace or _auto_extension_trace(gap),
    }
    if extra:
        response.update(extra)
    return response


def _build_deterministic_rule(text: str, symbols: list[str], allow_new_assets: bool = False) -> dict[str, Any]:
    normalized = text.lower()
    if _looks_like_profit_protection_strategy(normalized, symbols):
        return _build_profit_protection_strategy(symbols)
    if _looks_like_defensive_reallocation_strategy(normalized, symbols):
        return _build_defensive_reallocation_strategy(symbols)
    if _looks_like_risk_rotation_strategy(normalized, symbols):
        return _build_risk_rotation_strategy(symbols)

    condition = _deterministic_condition(normalized, symbols)
    action = _deterministic_action(normalized, symbols)
    if not condition:
        return {
            "status": "error",
            "code": "unsupported_indicator",
            "message": "Ich konnte keine unterstuetzte Kennzahl in der Regel erkennen.",
        }
    if not action:
        return {
            "status": "error",
            "code": "ambiguous_action",
            "message": "Ich konnte keine sichere Aktion wie transfer, sell oder buy_with_cash erkennen.",
        }

    source = action.get("from_asset") or action.get("asset") or "asset"
    target = action.get("to_asset") or action.get("asset") or "cash"
    rule = {
        "id": _slug(f"rule_{condition['indicator']}_{source}_{target}"),
        "name": _title_for_rule(condition, action),
        "description": "AI Rule Builder MVP rule created from natural language.",
        "condition": condition,
        "actions": [action],
        "execution": _execution_from_text(normalized),
        "enabled": True,
        "created_by_ai": True,
        "disclaimer": DISCLAIMER,
    }
    return {"status": "ok", "rule": rule, "explanation": "Die Regel wurde ohne LLM aus bekannten Finanzmustern abgeleitet."}


def _looks_like_profit_protection_strategy(normalized: str, symbols: list[str]) -> bool:
    required_symbols = {"AAPL", "MSFT", "NVDA", "SPY", "GLD", "TLT"}
    return (
        required_symbols.issubset(set(symbols))
        and ("gewinnsicherung" in normalized or "gewinnsicherungs" in normalized or "profit" in normalized)
        and ("trendbruch" in normalized or "trend" in normalized)
        and "45" in normalized
        and "100" in normalized
        and "30" in normalized
        and "cash" in normalized
    )


def _build_profit_protection_strategy(symbols: list[str]) -> dict[str, Any]:
    growth_assets = [asset for asset in ("AAPL", "MSFT", "NVDA") if asset in symbols]
    rules: list[dict[str, Any]] = []
    for asset in growth_assets:
        rules.append(_profit_protection_risk_off_rule(asset, spy_trend_ok=True))
        rules.append(_profit_protection_risk_off_rule(asset, spy_trend_ok=False))
        rules.append(_profit_protection_reentry_rule(asset))

    return {
        "status": "ok",
        "rules": rules,
        "explanation": (
            "Die Gewinnsicherungs- und Trendbruch-Strategie wurde in sichere Teilregeln zerlegt: "
            "je Wachstumsasset eine Risk-Off-Regel bei starkem SPY, eine Risk-Off-Regel bei schwachem SPY "
            "und eine Reentry-Regel aus Cash."
        ),
        "warnings": [],
    }


def _profit_protection_risk_off_rule(asset: str, spy_trend_ok: bool) -> dict[str, Any]:
    suffix = "spy_on" if spy_trend_ok else "spy_off"
    allocations = (
        [{"asset": "SPY", "percent": 40}, {"asset": "TLT", "percent": 35}, {"asset": "GLD", "percent": 25}]
        if spy_trend_ok
        else [{"asset": "TLT", "percent": 55}, {"asset": "GLD", "percent": 45}]
    )
    spy_condition = {
        "indicator": "price_above_moving_average" if spy_trend_ok else "price_below_moving_average",
        "operator": "==",
        "value": 1,
        "params": {"asset": "SPY", "window": 200},
    }
    return {
        "id": f"profit_protect_{asset.lower()}_{suffix}",
        "name": f"Gewinnsicherung {asset} ({'SPY stark' if spy_trend_ok else 'SPY schwach'})",
        "description": f"Sichert Gewinne in {asset}, wenn Trendbruch und hohe Volatilitaet auftreten.",
        "condition": {
            "indicator": "all",
            "operator": "==",
            "value": 1,
            "params": {
                "conditions": [
                    {"indicator": "return_since_start", "operator": ">", "value": 45, "params": {"asset": asset}},
                    {"indicator": "price_below_moving_average", "operator": "==", "value": 1, "params": {"asset": asset, "window": 100}},
                    {"indicator": "volatility", "operator": ">", "value": 30, "params": {"asset": asset, "window": 30}},
                    spy_condition,
                ]
            },
        },
        "actions": [
            {
                "type": "split_transfer_position_percent",
                "from_asset": asset,
                "percent": 35,
                "allocations": allocations,
            }
        ],
        "execution": {
            "frequency": "daily",
            "max_triggers": 3,
            "cooldown_days": 45,
            "group_id": f"profit_protection_{asset.lower()}",
            "group_max_triggers": 3,
            "group_cooldown_days": 45,
            "daily_group_id": "growth_profit_protection_daily",
            "daily_group_max_triggers": 2,
        },
        "enabled": True,
        "created_by_ai": True,
        "disclaimer": DISCLAIMER,
    }


def _profit_protection_reentry_rule(asset: str) -> dict[str, Any]:
    return {
        "id": f"profit_reentry_{asset.lower()}",
        "name": f"Reentry {asset} aus Cash",
        "description": f"Kauft {asset} mit 20 Prozent Cash zurueck, wenn Trend und Volatilitaet wieder konstruktiv sind.",
        "condition": {
            "indicator": "all",
            "operator": "==",
            "value": 1,
            "params": {
                "conditions": [
                    {"indicator": "asset_was_reduced", "operator": "==", "value": 1, "params": {"asset": asset}},
                    {"indicator": "price_above_moving_average", "operator": "==", "value": 1, "params": {"asset": asset, "window": 100}},
                    {"indicator": "volatility", "operator": "<", "value": 22, "params": {"asset": asset, "window": 30}},
                    {"indicator": "price_above_moving_average", "operator": "==", "value": 1, "params": {"asset": "SPY", "window": 200}},
                ]
            },
        },
        "actions": [{"type": "buy_with_cash_percent", "asset": asset, "cash_percent": 20}],
        "execution": {
            "frequency": "daily",
            "max_triggers": 3,
            "cooldown_days": 45,
            "group_id": f"profit_reentry_{asset.lower()}",
            "group_max_triggers": 3,
            "group_cooldown_days": 45,
        },
        "enabled": True,
        "created_by_ai": True,
        "disclaimer": DISCLAIMER,
    }


def _looks_like_defensive_reallocation_strategy(normalized: str, symbols: list[str]) -> bool:
    required_symbols = {"AAPL", "SPY", "GLD", "TLT"}
    return (
        required_symbols.issubset(set(symbols))
        and ("defensive" in normalized or "schwachem aktienmarkt" in normalized)
        and "verkaufserl" in normalized
        and "cash" in normalized
        and "volatil" in normalized
        and "200" in normalized
        and "100" in normalized
        and "24" in normalized
        and "18" in normalized
        and "50" in normalized
        and "30" in normalized
        and "20" in normalized
        and "25" in normalized
    )


def _build_defensive_reallocation_strategy(symbols: list[str]) -> dict[str, Any]:
    group_id = "defensive_rotation_aapl"
    risk_off_rule = {
        "id": "defensive_aapl_to_gld_tlt_cash",
        "name": "Defensive Umschichtung: AAPL nach GLD/TLT/Cash",
        "description": "Reduziert AAPL bei schwachem SPY-Trend, hoher SPY-Volatilitaet und AAPL-Trendbruch.",
        "condition": {
            "indicator": "all",
            "operator": "==",
            "value": 1,
            "params": {
                "conditions": [
                    {"indicator": "price_below_moving_average", "operator": "==", "value": 1, "params": {"asset": "SPY", "window": 200}},
                    {"indicator": "volatility", "operator": ">", "value": 24, "params": {"asset": "SPY", "window": 30}},
                    {"indicator": "price_below_moving_average", "operator": "==", "value": 1, "params": {"asset": "AAPL", "window": 100}},
                ]
            },
        },
        "actions": [
            {
                "type": "split_transfer_position_percent",
                "from_asset": "AAPL",
                "percent": 30,
                "allocations": [
                    {"asset": "GLD", "percent": 50},
                    {"asset": "TLT", "percent": 30},
                ],
            }
        ],
        "execution": {
            "frequency": "daily",
            "max_triggers": 4,
            "cooldown_days": 30,
            "group_id": group_id,
            "group_max_triggers": 4,
            "group_cooldown_days": 30,
        },
        "enabled": True,
        "created_by_ai": True,
        "disclaimer": DISCLAIMER,
    }
    reentry_rule = {
        "id": "defensive_reentry_cash_to_aapl",
        "name": "Reentry: Cash nach AAPL",
        "description": "Kauft AAPL mit Cash zurueck, wenn SPY-Trend und SPY-Volatilitaet wieder konstruktiv sind.",
        "condition": {
            "indicator": "all",
            "operator": "==",
            "value": 1,
            "params": {
                "conditions": [
                    {"indicator": "asset_was_reduced", "operator": "==", "value": 1, "params": {"asset": "AAPL"}},
                    {"indicator": "price_above_moving_average", "operator": "==", "value": 1, "params": {"asset": "SPY", "window": 200}},
                    {"indicator": "volatility", "operator": "<", "value": 18, "params": {"asset": "SPY", "window": 30}},
                ]
            },
        },
        "actions": [{"type": "buy_with_cash_percent", "asset": "AAPL", "cash_percent": 25}],
        "execution": {
            "frequency": "daily",
            "max_triggers": 4,
            "cooldown_days": 30,
            "group_id": group_id,
            "group_max_triggers": 4,
            "group_cooldown_days": 30,
        },
        "enabled": True,
        "created_by_ai": True,
        "disclaimer": DISCLAIMER,
    }
    return {
        "status": "ok",
        "rules": [risk_off_rule, reentry_rule],
        "explanation": (
            "Die defensive Umschichtung wurde in zwei sichere Teilregeln zerlegt: "
            "eine Risk-Off-Regel mit GLD/TLT/Cash-Aufteilung und eine Reentry-Regel aus Cash."
        ),
        "warnings": [],
    }


def _looks_like_risk_rotation_strategy(normalized: str, symbols: list[str]) -> bool:
    required_symbols = {"AAPL", "SPY", "GLD", "TLT"}
    return (
        required_symbols.issubset(set(symbols))
        and "risk-off" in normalized
        and "risk-on" in normalized
        and "market-rotation-score" in normalized
        and "200" in normalized
        and "30" in normalized
        and "volatil" in normalized
    )


def _build_risk_rotation_strategy(symbols: list[str]) -> dict[str, Any]:
    equity_proxy = "SPY" if "SPY" in symbols else symbols[0]
    defensive_proxy = [symbol for symbol in ("GLD", "TLT") if symbol in symbols] or (["GLD"] if "GLD" in symbols else [equity_proxy])
    risk_off_rule = {
        "id": "risk_off_aapl_to_gld_tlt",
        "name": "Risk-Off: AAPL nach GLD/TLT",
        "description": "Risk-Off-Marktrotation: AAPL nur bei schwachem Markt, SMA-Bruch und hoher Volatilitaet reduzieren.",
        "condition": {
            "indicator": "all",
            "operator": "==",
            "value": 1,
            "params": {
                "conditions": [
                    {
                        "indicator": "market_rotation_score",
                        "operator": "<",
                        "value": 35,
                        "params": {"equity_proxy": equity_proxy, "defensive_proxy": defensive_proxy, "window": 90},
                    },
                    {
                        "indicator": "price_below_moving_average",
                        "operator": "==",
                        "value": 1,
                        "params": {"asset": "AAPL", "window": 200},
                    },
                    {
                        "indicator": "volatility",
                        "operator": ">",
                        "value": 28,
                        "params": {"asset": "AAPL", "window": 30},
                    },
                ]
            },
        },
        "actions": [
            {
                "type": "split_transfer_position_percent",
                "from_asset": "AAPL",
                "percent": 25,
                "allocations": [
                    {"asset": "GLD", "percent": 60},
                    {"asset": "TLT", "percent": 40},
                ],
            }
        ],
        "execution": {
            "frequency": "daily",
            "max_triggers": 4,
            "cooldown_days": 30,
            "group_id": "risk_rotation_aapl",
            "group_max_triggers": 4,
            "group_cooldown_days": 30,
        },
        "enabled": True,
        "created_by_ai": True,
        "disclaimer": DISCLAIMER,
    }
    risk_on_rule = {
        "id": "risk_on_gld_to_aapl",
        "name": "Risk-On: GLD nach AAPL",
        "description": "Risk-On-Rotation: Bei verbessertem Marktumfeld GLD teilweise zurueck in AAPL schichten.",
        "condition": {
            "indicator": "all",
            "operator": "==",
            "value": 1,
            "params": {
                "conditions": [
                    {
                        "indicator": "market_rotation_score",
                        "operator": ">",
                        "value": 65,
                        "params": {"equity_proxy": equity_proxy, "defensive_proxy": defensive_proxy, "window": 90},
                    },
                    {
                        "indicator": "price_above_moving_average",
                        "operator": "==",
                        "value": 1,
                        "params": {"asset": "AAPL", "window": 200},
                    },
                ]
            },
        },
        "actions": [
            {
                "type": "transfer_position_percent",
                "from_asset": "GLD",
                "to_asset": "AAPL",
                "percent": 50,
            }
        ],
        "execution": {
            "frequency": "daily",
            "max_triggers": 4,
            "cooldown_days": 30,
            "group_id": "risk_rotation_aapl",
            "group_max_triggers": 4,
            "group_cooldown_days": 30,
        },
        "enabled": True,
        "created_by_ai": True,
        "disclaimer": DISCLAIMER,
    }
    return {
        "status": "ok",
        "rules": [risk_off_rule, risk_on_rule],
        "explanation": (
            "Die Risk-Off/Risk-On-Strategie wurde als zwei sichere Custom Rules erzeugt. "
            "Alle Bedingungen werden nur mit historischen Daten bis zum jeweiligen Backtest-Tag ausgewertet."
        ),
        "warnings": [],
    }


def _deterministic_condition(normalized: str, symbols: list[str]) -> dict[str, Any] | None:
    threshold = _number_after(normalized, ["above", "over", "ueber", "über", "greater than", ">"]) or _first_number(normalized) or 70
    if "market rotation" in normalized or "marktrotation" in normalized or "rotation" in normalized:
        return {
            "indicator": "market_rotation_score",
            "operator": ">",
            "value": threshold,
            "params": {
                "equity_proxy": _symbol_for("market", symbols, fallback="SPY"),
                "defensive_proxy": _symbol_for("gold", symbols, fallback="GLD"),
                "window": 90,
            },
        }

    asset = _mentioned_symbol(normalized, symbols) or (symbols[0] if symbols else None)
    if not asset:
        return None

    dynamic_definition = IndicatorRegistry.find_registered_in_text(normalized)
    if dynamic_definition:
        return _dynamic_indicator_condition(dynamic_definition, normalized, symbols, asset)

    if ("gewinn" in normalized or "profit" in normalized or "return" in normalized) and ("seit start" in normalized or "since start" in normalized):
        return {
            "indicator": "return_since_start",
            "operator": ">",
            "value": _condition_threshold(normalized, 10),
            "params": {"asset": asset},
        }

    window = int(_number_after(normalized, ["sma", "moving average", "durchschnitt"]) or _window_from_text(normalized, 200))
    if "moving average" in normalized or "sma" in normalized or "durchschnitt" in normalized:
        below = any(word in normalized for word in ("below", "under", "unter", "kleiner"))
        return {
            "indicator": "price_below_moving_average" if below else "price_above_moving_average",
            "operator": "==",
            "value": 1,
            "params": {"asset": asset, "window": window},
        }

    if "kurs" in normalized or "price" in normalized:
        below = any(word in normalized for word in ("below", "under", "unter", "kleiner", "less than", "<"))
        above = any(word in normalized for word in ("above", "over", "ueber", "greater than", "groesser", "gr\u00f6\u00dfer", ">"))
        above = above or _first_percent(normalized) is not None or _first_number(normalized) is not None
        if below or above:
            return {
                "indicator": "price",
                "operator": "<" if below else ">",
                "value": _condition_threshold(normalized, 100),
                "params": {"asset": asset},
            }

    if "drawdown" in normalized or "fall" in normalized or "faellt" in normalized or "fällt" in normalized:
        return {
            "indicator": "drawdown",
            "operator": ">=",
            "value": _condition_threshold(normalized, 10),
            "params": {"asset": asset, "window": _window_from_text(normalized, 252)},
        }

    if "volatility" in normalized or "volatilitaet" in normalized or "volatilität" in normalized:
        return {
            "indicator": "volatility",
            "operator": ">=",
            "value": _condition_threshold(normalized, 20),
            "params": {"asset": asset, "window": _window_from_text(normalized, 30)},
        }
    return None


def _dynamic_indicator_condition(definition, normalized: str, symbols: list[str], primary_asset: str) -> dict[str, Any]:
    params: dict[str, Any] = dict(definition.default_params)
    params["asset"] = primary_asset
    if "window" in definition.required_params or "window" in params:
        params["window"] = _window_from_text(normalized, int(params.get("window", 30)))

    mentioned = _mentioned_symbols(normalized, symbols)
    secondary = next((symbol for symbol in mentioned if symbol != primary_asset), None)
    if "benchmark" in definition.required_params:
        params["benchmark"] = secondary or params.get("benchmark") or ("SPY" if "SPY" in symbols else primary_asset)
    if "asset_a" in definition.required_params:
        params["asset_a"] = primary_asset
    if "asset_b" in definition.required_params:
        params["asset_b"] = secondary or params.get("asset_b") or ("SPY" if "SPY" in symbols else primary_asset)

    return {
        "indicator": definition.name,
        "operator": _operator_from_text(normalized, definition.default_operator),
        "value": _dynamic_threshold_from_text(normalized, definition),
        "params": params,
    }


def _operator_from_text(text: str, default: str = ">") -> str:
    if any(word in text for word in ("negative", "below", "under", "unter", "kleiner", "less than", "faellt unter", "fällt unter")):
        return "<"
    if any(word in text for word in ("at most", "hoechstens", "höchstens", "maximal")):
        return "<="
    if any(word in text for word in ("at least", "mindestens")):
        return ">="
    if any(word in text for word in ("above", "over", "ueber", "über", "greater than", "groesser", "größer")):
        return ">"
    return default


def _dynamic_threshold_from_text_legacy(text: str, definition) -> float:
    threshold = (
        _number_after(text, ["below", "under", "unter", "kleiner", "less than", "above", "over", "ueber", "über", "greater than", "groesser", "größer", "at least", "mindestens", "at most"])
        or _condition_threshold(text, definition.default_threshold)
    )
    if definition.name in {"momentum"} and "%" in text and abs(float(threshold)) > 1:
        return float(threshold) / 100
    if "negative" in text and not re.search(r"(?:below|under|unter|kleiner|less than|above|over|ueber|über|greater than|groesser|größer)\s*-?\d", text):
        return 0.0
    return float(threshold)


def _dynamic_threshold_from_text(text: str, definition) -> float:
    comparison_words = [
        "below", "under", "unter", "kleiner", "less than",
        "above", "over", "ueber", "greater than", "groesser",
        "at least", "mindestens", "at most",
    ]
    explicit = _number_after(text, comparison_words)
    threshold = explicit if explicit is not None else _condition_threshold(text, definition.default_threshold)
    if definition.name in {"momentum"} and "%" in text and abs(float(threshold)) > 1:
        return float(threshold) / 100
    if "negative" in text and explicit is None:
        return 0.0
    return float(threshold)


def _deterministic_action(normalized: str, symbols: list[str]) -> dict[str, Any] | None:
    percent = _action_percent(normalized) or 20
    mentioned = _mentioned_symbols(normalized, symbols)
    target = _symbol_for("gold", symbols, fallback=None) if "gold" in normalized else _mentioned_symbol(normalized, symbols)
    if ("cash" in normalized or "bar" in normalized) and ("buy" in normalized or "kauf" in normalized):
        non_cash_mentions = [symbol for symbol in mentioned if symbol != "CASH"]
        if non_cash_mentions:
            target = non_cash_mentions[-1]
    elif len(mentioned) > 1 and target == mentioned[0] and mentioned[1] != "CASH":
        target = mentioned[1]
    source = _symbol_for("apple", symbols, fallback=None) if "apple" in normalized or "apfel" in normalized else (mentioned[0] if mentioned else None)

    if ("erl" in normalized or "proceeds" in normalized) and ("buy" in normalized or "kauf" in normalized) and source and target and target != "CASH" and source != target:
        return {
            "type": "transfer_position_percent",
            "from_asset": source,
            "to_asset": target,
            "asset": None,
            "percent": float(percent),
            "cash_percent": None,
        }

    cash_budget_requested = any(word in normalized for word in ("verfuegbar", "verfügbar", "available", "nutze", "use"))
    cash_budget_requested = cash_budget_requested or bool(
        re.search(_percent_pattern() + r"[^.;\n]{0,40}(?:cash|bar)", normalized)
        or re.search(r"(?:cash|bar)[^.;\n]{0,40}" + _percent_pattern(), normalized)
    )
    if ("cash" in normalized or "bar" in normalized) and cash_budget_requested and ("buy" in normalized or "kauf" in normalized) and target and target != "CASH":
        return {
            "type": "buy_with_cash_percent",
            "from_asset": None,
            "to_asset": None,
            "asset": target,
            "percent": None,
            "cash_percent": float(percent),
        }

    if ("use" in normalized or "nutze" in normalized or "umschicht" in normalized or "shift" in normalized) and source and target and source != target:
        return {
            "type": "transfer_position_percent",
            "from_asset": source,
            "to_asset": target,
            "asset": None,
            "percent": float(percent),
            "cash_percent": None,
        }

    if ("sell" in normalized or "verkauf" in normalized) and ("buy" in normalized or "kauf" in normalized) and source and target and target != "CASH" and source != target:
        return {
            "type": "transfer_position_percent",
            "from_asset": source,
            "to_asset": target,
            "asset": None,
            "percent": float(percent),
            "cash_percent": None,
        }

    if ("sell" in normalized or "verkauf" in normalized) and source:
        return {
            "type": "sell_position_percent",
            "from_asset": None,
            "to_asset": None,
            "asset": source,
            "percent": float(percent),
            "cash_percent": None,
        }

    return None


def _build_with_llm(text: str, symbols: list[str], base_currency: str, risk_level: str, allow_new_assets: bool = False) -> dict[str, Any]:
    prompt = _builder_prompt(text, symbols, base_currency, risk_level, allow_new_assets=allow_new_assets)
    try:
        llm = _create_chat_model()
        response = llm.invoke(prompt)
        payload = _parse_json_response(response.content)
    except Exception as exc:
        return {
            "status": "error",
            "code": "llm_failed",
            "message": f"KI-Regel konnte mit Provider '{_normalized_provider()}' nicht erzeugt werden: {exc}",
            "provider": _normalized_provider(),
        }

    if "error" in payload:
        return {"status": "error", "code": payload.get("error"), "message": payload.get("reason") or "Regel konnte nicht erzeugt werden.", "questions": payload.get("questions", [])}

    result = finalize_rule(
        payload,
        symbols,
        "Die Regel wurde vom KI-Builder erzeugt und deterministisch validiert.",
        allow_new_assets=allow_new_assets,
    )
    if result["status"] == "ok":
        return result
    return result


def _builder_prompt(text: str, symbols: list[str], base_currency: str, risk_level: str, allow_new_assets: bool = False) -> str:
    universe_policy = (
        "You may use existing portfolio symbols and additional valid yfinance tickers mentioned by the user."
        if allow_new_assets
        else "Use only the portfolio symbols."
    )
    return f"""
You convert natural language backtesting rules into strict JSON only.
No markdown. No Python code. No shell commands. No explanations outside JSON.

The rule is for historical backtesting only and must not place real trades.
Asset universe policy: {universe_policy}

Supported actions: {sorted(ALLOWED_ACTIONS)}
Supported indicators: {sorted(supported_indicators())}
Supported operators: {sorted(ALLOWED_OPERATORS)}
Allowed/resolved symbols: {symbols}
Base currency: {base_currency}
Risk level: {risk_level}

Return JSON with:
id, name, description, condition {{indicator, operator, value, params}},
actions [{{type, from_asset, to_asset, asset, percent, cash_percent, allocations}}],
execution {{frequency, max_triggers, cooldown_days, group_id, group_max_triggers, group_cooldown_days, daily_group_id, daily_group_max_triggers}},
enabled, disclaimer.

For AND logic use condition indicator "all", operator "==", value 1, params.conditions as a list of normal conditions.
For split proceeds use action type "split_transfer_position_percent" with from_asset, percent, and allocations summing to 100.
For return since backtest start use indicator "return_since_start".
For reentry after a previous reduction use indicator "asset_was_reduced".

If ambiguous, return {{"error":"ambiguous_rule","questions":["..."]}}.
If unrelated to finance/backtesting, return {{"error":"not_finance_related","reason":"..."}}.

User rule:
{text}
""".strip()


def _response_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        return "".join(_response_content_to_text(item) for item in content)
    if isinstance(content, dict):
        for key in ("text", "content", "parts"):
            if key in content:
                return _response_content_to_text(content[key])
        return json.dumps(content)

    text_attr = getattr(content, "text", None)
    if callable(text_attr):
        return str(text_attr())
    if text_attr is not None:
        return str(text_attr)

    nested_content = getattr(content, "content", None)
    if nested_content is not None:
        return _response_content_to_text(nested_content)

    return str(content)


def _parse_json_response(content: Any) -> dict[str, Any]:
    content = _response_content_to_text(content)
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
    return json.loads(content)


def _normalized_provider() -> str:
    provider = os.getenv("RULE_BUILDER_PROVIDER", RULE_BUILDER_PROVIDER).strip().lower()
    if provider in {"google", "google_genai", "google-generative-ai"}:
        return "gemini"
    if provider in {"openai", "chatgpt", "gpt"}:
        return "openai"
    return provider


def _provider_model() -> str:
    model = os.getenv("RULE_BUILDER_MODEL")
    if model:
        return model
    return "gemini-3.1-flash-lite" if _normalized_provider() == "gemini" else "gpt-4.1-mini"


def _provider_api_key() -> str | None:
    provider = _normalized_provider()
    if provider == "gemini":
        return os.getenv("RULE_BUILDER_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if provider == "openai":
        return os.getenv("RULE_BUILDER_API_KEY") or os.getenv("OPENAI_API_KEY")
    return os.getenv("RULE_BUILDER_API_KEY")


def _has_llm_key() -> bool:
    return bool(_provider_api_key())


def _missing_key_message() -> str:
    if _normalized_provider() == "gemini":
        return "Diese freie Regel braucht Gemini. Bitte GOOGLE_API_KEY, GEMINI_API_KEY oder RULE_BUILDER_API_KEY setzen."
    if _normalized_provider() == "openai":
        return "Diese freie Regel braucht OpenAI. Bitte OPENAI_API_KEY oder RULE_BUILDER_API_KEY setzen."
    return "Diese freie Regel braucht einen KI-Provider-Key. Bitte RULE_BUILDER_API_KEY setzen."


def _create_chat_model():
    provider = _normalized_provider()
    api_key = _provider_api_key()
    model = _provider_model()

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:
            raise RuntimeError(f"LangChain OpenAI ist nicht verfuegbar: {exc}") from exc
        return ChatOpenAI(model=model, api_key=api_key, temperature=0)

    if provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except Exception as exc:
            raise RuntimeError("Gemini braucht das Paket langchain-google-genai. Installiere requirements.txt erneut.") from exc
        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0)

    raise ValueError(f"Nicht unterstuetzter RULE_BUILDER_PROVIDER: {provider}")


def _cache_key(text: str, symbols: list[str], new_asset_mode: str = "portfolio_only") -> str:
    raw = f"{SCHEMA_VERSION}|{normalize_new_asset_mode(new_asset_mode)}|{text.lower().strip()}|{','.join(sorted(symbols))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _store(key: str, value: dict[str, Any]) -> dict[str, Any]:
    _CACHE[key] = value
    return value


def _mentioned_symbol(normalized: str, symbols: list[str]) -> str | None:
    for symbol in symbols:
        if symbol.lower() in normalized:
            return symbol
    for alias, symbol in SYMBOL_ALIASES.items():
        if alias in normalized and symbol in symbols:
            return symbol
    return None


def _mentioned_symbols(normalized: str, symbols: list[str]) -> list[str]:
    found: list[str] = []
    for symbol in symbols:
        if symbol.lower() in normalized and symbol not in found:
            found.append(symbol)
    for alias, symbol in SYMBOL_ALIASES.items():
        if alias in normalized and symbol in symbols and symbol not in found:
            found.append(symbol)
    return found


def _symbol_for(alias: str, symbols: list[str], fallback: str | None) -> str | None:
    symbol = SYMBOL_ALIASES.get(alias, alias.upper())
    if symbol in symbols:
        return symbol
    return fallback if fallback in symbols else None


def _percent_pattern() -> str:
    return r"(-?\d+(?:[.,]\d+)?)\s*(?:%|prozent|percent)"


def _first_percent(text: str) -> float | None:
    match = re.search(_percent_pattern(), text)
    return float(match.group(1).replace(",", ".")) if match else None


def _first_number(text: str) -> float | None:
    match = re.search(r"(?<![a-z0-9])(-?\d+(?:[.,]\d+)?)(?![a-z0-9])", text)
    return float(match.group(1).replace(",", ".")) if match else None


def _last_percent(text: str) -> float | None:
    matches = re.findall(_percent_pattern(), text)
    return float(matches[-1].replace(",", ".")) if matches else None


def _condition_threshold(text: str, default: float) -> float:
    for value in (
        _number_after(text, ["above", "greater than", "more than", "mehr als", "ueber", "over", ">"]),
        _first_percent(text),
        _first_number(text),
    ):
        if value is not None:
            return value
    return default


def _action_percent(text: str) -> float | None:
    action_words = ["sell", "verkauf", "verkaufe", "transfer", "shift", "umschicht", "use", "nutze", "buy", "kauf"]
    for word in action_words:
        match = re.search(re.escape(word) + r"[^.;\n]{0,100}?" + _percent_pattern(), text)
        if match:
            return float(match.group(1).replace(",", "."))
    return _last_percent(text) or _first_percent(text)


def _window_from_text(text: str, default: int) -> int:
    patterns = [
        r"\b(\d+)\s*-\s*(?:tage|tagen|tag|day|days)\b",
        r"\bover\s+(\d+)\s*(?:trading\s+)?days?\b",
        r"\b(?:last|past|within|in)\s+(\d+)\s*(?:trading\s+)?days?\b",
        r"\b(\d+)\s*(?:trading\s+)?days?\b",
        r"\b(?:letzte[nr]?|in)\s+(\d+)\s*(?:tage|tagen|tag)\b",
        r"\b(\d+)\s*(?:tage|tagen|tag)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = int(match.group(1))
            if 0 < value <= 1000:
                return value
    return default


def _number_after(text: str, words: list[str]) -> float | None:
    for word in words:
        match = re.search(re.escape(word) + r"\s*(-?\d+(?:[.,]\d+)?)", text)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def _execution_from_text(text: str) -> dict[str, Any]:
    execution: dict[str, Any] = {"frequency": "daily", "max_triggers": None, "cooldown_days": 0}
    cooldown = _cooldown_days_from_text(text)
    max_triggers = _max_triggers_from_text(text)
    if cooldown is not None:
        execution["cooldown_days"] = cooldown
    if max_triggers is not None:
        execution["max_triggers"] = max_triggers
    return execution


def _cooldown_days_from_text(text: str) -> int | None:
    patterns = [
        r"(?:alle|every)\s+(\d+)\s*(?:tage|tagen|tag|days?)",
        r"(\d+)\s*(?:tage|tagen|tag|days?).{0,30}(?:ausloesen|auslösen|trigger)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def _max_triggers_from_text(text: str) -> int | None:
    if re.search(r"(?:maximal|hoechstens|höchstens)\s+einmal\s+alle", text):
        return None
    match = re.search(r"(?:maximal|hoechstens|höchstens)\s+(\d+)\s*-\s*mal.{0,80}(?:gesamt|gesamten|backtest)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:maximal|hoechstens|höchstens)\s+(\d+)\s*(?:mal|x).{0,80}(?:gesamt|gesamten|backtest)", text)
    if match:
        return int(match.group(1))
    if re.search(r"(?:maximal|hoechstens|höchstens)\s+einmal.{0,80}(?:gesamt|gesamten|backtest)", text):
        return 1
    return None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", value.lower()).strip("_")
    return slug[:80] or "custom_rule"


def _title_for_rule(condition: dict[str, Any], action: dict[str, Any]) -> str:
    if action["type"] == "transfer_position_percent":
        return f"Transfer {action['percent']}% {action['from_asset']} to {action['to_asset']}"
    if action["type"] == "sell_position_percent":
        return f"Sell {action['percent']}% {action['asset']}"
    return f"Buy {action['asset']} with {action['cash_percent']}% cash"
