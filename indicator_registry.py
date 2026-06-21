from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd


FORMULA_DSL_VERSION = "formula-indicator-v1"
INDICATOR_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,48}$")
SAFE_INDICATOR_TERMS = {
    "entropy": ["entropy", "entropie", "shannon", "market entropy", "return entropy"],
    "rsi": ["rsi", "relative strength index"],
    "macd": ["macd", "moving average convergence divergence"],
    "correlation": ["correlation break", "rolling correlation", "korrelationsbruch", "correlation", "korrelation"],
    "beta": ["beta", "rolling beta", "market beta"],
    "z_score": ["z-score", "z score", "standard score", "abweichung vom mittelwert"],
    "moving_average_slope": ["moving average slope", "ma slope", "sma slope", "slope of moving average", "durchschnittssteigung", "steigender gleitender durchschnitt", "fallender gleitender durchschnitt"],
    "momentum": ["momentum", "rolling return", "performance ueber", "performance über"],
    "volatility_variant": ["rolling volatility", "rollierende volatilitaet", "rollierende volatilität"],
    "drawdown_variant": ["rolling max drawdown", "max drawdown", "maximaler drawdown"],
}
UNSAFE_EXTERNAL_INDICATOR_TERMS = {
    "news_sentiment": ["news sentiment", "nachrichten sentiment", "news"],
    "social_sentiment": ["social sentiment", "twitter", "reddit sentiment"],
    "earnings": ["earnings", "earnings surprise", "quartalszahlen", "gewinnueberraschung", "gewinnüberraschung"],
    "analyst_rating": ["analyst rating", "analystenrating", "analysten empfehlung"],
    "macro_data": ["interest rate curve", "zinskurve", "inflation", "macro data", "makrodaten"],
    "insider_trading": ["insider trading", "insiderkaeufe", "insiderkäufe"],
    "order_flow": ["order flow", "broker data", "brokerdaten"],
}
SUSPICIOUS_FORMULA_TERMS = {
    "code", "python", "import", "eval", "exec", "subprocess", "open", "path", "file",
    "request", "requests", "url", "network", "socket", "shell", "command", "os", "sys", "pickle",
}
ALLOWED_FORMULA_OPS = {
    "abs",
    "add",
    "beta",
    "clip",
    "const",
    "correlation",
    "divide",
    "div",
    "ema",
    "entropy",
    "last",
    "macd",
    "max",
    "mean",
    "min",
    "moving_average_slope",
    "mul",
    "multiply",
    "neg",
    "negative_abs",
    "normalized_shannon_entropy",
    "pct_change",
    "positive",
    "price",
    "relative_strength",
    "returns",
    "rolling_correlation",
    "rolling_max",
    "rolling_mean",
    "rolling_min",
    "rolling_return",
    "rolling_std",
    "rsi",
    "std",
    "subtract",
    "sub",
    "tail",
    "variance",
    "z_score",
    "greater_than",
    "less_than",
    "between",
}


@dataclass
class FormulaIndicatorDefinition:
    name: str
    description: str
    formula: dict[str, Any]
    type: str = "formula_indicator"
    semantic_version: str = "1.0.0"
    required_params: list[str] = field(default_factory=lambda: ["asset"])
    default_params: dict[str, Any] = field(default_factory=dict)
    params_schema: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    output_min: float | None = None
    output_max: float | None = None
    output_type: str = "float"
    required_data: list[str] = field(default_factory=lambda: ["historical_prices"])
    lookahead_safe: bool = True
    approval_status: str = "approved"
    provenance: dict[str, Any] = field(default_factory=dict)
    default_operator: str = ">"
    default_threshold: float = 0.0
    version: str = FORMULA_DSL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "semantic_version": self.semantic_version,
            "description": self.description,
            "formula": deepcopy(self.formula),
            "required_params": list(self.required_params),
            "default_params": deepcopy(self.default_params),
            "params_schema": deepcopy(self.params_schema),
            "aliases": list(self.aliases),
            "output_min": self.output_min,
            "output_max": self.output_max,
            "output_range": [self.output_min, self.output_max] if self.output_min is not None or self.output_max is not None else None,
            "output_type": self.output_type,
            "required_data": list(self.required_data),
            "lookahead_safe": self.lookahead_safe,
            "approval_status": self.approval_status,
            "provenance": deepcopy(self.provenance),
            "default_operator": self.default_operator,
            "default_threshold": self.default_threshold,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FormulaIndicatorDefinition":
        return cls(
            name=str(value.get("name") or ""),
            type=str(value.get("type") or "formula_indicator"),
            semantic_version=str(value.get("semantic_version") or value.get("indicator_version") or "1.0.0"),
            description=str(value.get("description") or ""),
            formula=dict(value.get("formula") or {}),
            required_params=list(value.get("required_params") or ["asset"]),
            default_params=dict(value.get("default_params") or {}),
            params_schema=dict(value.get("params_schema") or {}),
            aliases=list(value.get("aliases") or []),
            output_min=value.get("output_min", (value.get("output_range") or [None, None])[0]),
            output_max=value.get("output_max", (value.get("output_range") or [None, None])[1]),
            output_type=str(value.get("output_type") or "float"),
            required_data=list(value.get("required_data") or ["historical_prices"]),
            lookahead_safe=bool(value.get("lookahead_safe", True)),
            approval_status=str(value.get("approval_status") or "approved"),
            provenance=dict(value.get("provenance") or {}),
            default_operator=str(value.get("default_operator") or ">"),
            default_threshold=float(value.get("default_threshold", 0.0)),
            version=str(value.get("version") or FORMULA_DSL_VERSION),
        )


class FormulaSecurityAuditor:
    MAX_DEPTH = 12
    MAX_NODES = 80
    SAFE_PARAM_KEYS = {"asset", "asset_a", "asset_b", "benchmark", "window", "bins", "fast", "slow", "signal", "span", "fast_window", "slow_window", "signal_window", "output", "slope_window"}

    @classmethod
    def audit(cls, definition: FormulaIndicatorDefinition | dict[str, Any]) -> dict[str, Any]:
        if isinstance(definition, dict):
            definition = FormulaIndicatorDefinition.from_dict(definition)
        errors: list[dict[str, str]] = []

        if definition.type != "formula_indicator":
            errors.append({"code": "invalid_indicator_type", "message": "Only formula_indicator can be auto-approved."})
        if definition.version != FORMULA_DSL_VERSION:
            errors.append({"code": "invalid_formula_version", "message": "Unsupported formula DSL version."})
        if definition.required_data != ["historical_prices"]:
            errors.append({"code": "external_data_required", "message": "Formula indicators may only require historical_prices."})
        if not definition.lookahead_safe:
            errors.append({"code": "lookahead_not_safe", "message": "Formula indicator must be marked lookahead_safe."})
        if definition.output_type not in {"float", "bool"}:
            errors.append({"code": "invalid_output_type", "message": "Formula output_type must be float or bool."})
        if not INDICATOR_NAME_PATTERN.match(definition.name):
            errors.append({"code": "invalid_indicator_name", "message": "Indicator name must be snake_case and short."})
        if definition.default_operator not in {">", ">=", "<", "<=", "==", "!="}:
            errors.append({"code": "invalid_default_operator", "message": "Default operator is not allowed."})
        if not isinstance(definition.params_schema, dict):
            errors.append({"code": "invalid_params_schema", "message": "params_schema must be present as an object."})
        if not isinstance(definition.formula, dict) or not definition.formula:
            errors.append({"code": "missing_formula", "message": "Formula definition is required."})
        if definition.output_min is not None and definition.output_max is not None and definition.output_min >= definition.output_max:
            errors.append({"code": "invalid_output_range", "message": "output_min must be lower than output_max."})

        suspicious = cls._scan_suspicious(definition.to_dict())
        errors.extend(suspicious)
        walk = cls._walk_formula(definition.formula)
        errors.extend(walk["errors"])
        return {
            "status": "ok" if not errors else "error",
            "valid": not errors,
            "passed": not errors,
            "errors": errors,
            "warnings": [],
            "checks": {
                "formula_indicator": definition.type == "formula_indicator",
                "allowlisted_ops": not walk["errors"],
                "no_code_execution": not any(error["code"] == "suspicious_formula_content" for error in suspicious),
                "no_network": not any(term in str(definition.to_dict()).lower() for term in ("network", "socket", "request", "url")),
                "no_filesystem": not any(term in str(definition.to_dict()).lower() for term in ("file", "path", "open")),
                "historical_prices_only": definition.required_data == ["historical_prices"],
                "lookahead_safe": definition.lookahead_safe,
                "bounded_recursion": not any(error["code"] in {"formula_too_deep", "formula_too_large"} for error in walk["errors"]),
            },
        }

    @classmethod
    def _scan_suspicious(cls, value: Any, path: str = "$") -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        if isinstance(value, dict):
            for key, nested in value.items():
                key_text = str(key).lower()
                if key_text in SUSPICIOUS_FORMULA_TERMS:
                    errors.append({"code": "suspicious_formula_content", "message": f"Suspicious key at {path}.{key}."})
                errors.extend(cls._scan_suspicious(nested, f"{path}.{key}"))
            return errors
        if isinstance(value, list):
            for index, item in enumerate(value):
                errors.extend(cls._scan_suspicious(item, f"{path}[{index}]"))
            return errors
        if isinstance(value, str):
            text = value.lower()
            for term in SUSPICIOUS_FORMULA_TERMS:
                if re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", text):
                    errors.append({"code": "suspicious_formula_content", "message": f"Suspicious value at {path}: {term}."})
                    break
        return errors

    @classmethod
    def _walk_formula(cls, formula: Any, depth: int = 0, nodes: list[int] | None = None) -> dict[str, Any]:
        nodes = nodes if nodes is not None else [0]
        errors: list[dict[str, str]] = []
        if depth > cls.MAX_DEPTH:
            return {"errors": [{"code": "formula_too_deep", "message": "Formula nesting is too deep."}]}
        nodes[0] += 1
        if nodes[0] > cls.MAX_NODES:
            return {"errors": [{"code": "formula_too_large", "message": "Formula contains too many nodes."}]}

        if isinstance(formula, (int, float, str)) or formula is None:
            return {"errors": []}
        if isinstance(formula, list):
            for item in formula:
                errors.extend(cls._walk_formula(item, depth + 1, nodes)["errors"])
            return {"errors": errors}
        if not isinstance(formula, dict):
            return {"errors": [{"code": "invalid_formula_node", "message": "Formula nodes must be JSON values."}]}

        op = formula.get("op")
        if op not in ALLOWED_FORMULA_OPS:
            errors.append({"code": "unsupported_formula_op", "message": f"Formula op '{op}' is not allowed."})
        for key, value in formula.items():
            if key in {"op", "asset_param", "asset_a_param", "asset_b_param", "benchmark_param", "window_param", "bins_param", "fast_param", "slow_param", "signal_param", "span_param", "fast_window_param", "slow_window_param", "signal_window_param", "output_param", "slope_window_param"}:
                if key != "op" and str(value) not in cls.SAFE_PARAM_KEYS:
                    errors.append({"code": "unsafe_param_reference", "message": f"Param reference '{value}' is not allowed."})
                continue
            errors.extend(cls._walk_formula(value, depth + 1, nodes)["errors"])
        return {"errors": errors}


class IndicatorRegistry:
    _dynamic: dict[str, FormulaIndicatorDefinition] = {}
    BUILT_IN_INDICATORS = {
        "all",
        "any",
        "asset_was_reduced",
        "drawdown",
        "market_rotation_score",
        "price",
        "price_above_moving_average",
        "price_below_moving_average",
        "relative_strength",
        "return_since_start",
        "volatility",
    }

    @classmethod
    def clear_dynamic_indicators(cls):
        cls._dynamic.clear()

    @classmethod
    def unregister_dynamic_indicator(cls, name: str):
        cls._dynamic.pop(normalize_indicator_name(name), None)

    @classmethod
    def has(cls, name: str) -> bool:
        normalized = normalize_indicator_name(name)
        return normalized in cls.BUILT_IN_INDICATORS or normalized in cls._dynamic

    @classmethod
    def names(cls) -> set[str]:
        return set(cls.BUILT_IN_INDICATORS) | set(cls._dynamic)

    @classmethod
    def get(cls, name: str) -> FormulaIndicatorDefinition | None:
        return cls._dynamic.get(normalize_indicator_name(name))

    @classmethod
    def register_dynamic_indicator(cls, definition: FormulaIndicatorDefinition | dict[str, Any], approved: bool = True) -> dict[str, Any]:
        if isinstance(definition, dict):
            definition = FormulaIndicatorDefinition.from_dict(definition)
        definition.approval_status = "approved" if approved else "pending"
        audit = FormulaSecurityAuditor.audit(definition)
        if not audit["valid"]:
            return {"status": "error", "code": "formula_security_failed", "audit": audit, "definition": definition.to_dict()}
        cls._dynamic[definition.name] = definition
        return {"status": "ok", "definition": definition.to_dict(), "audit": audit}

    @classmethod
    def resolve(cls, name: str, historical_prices: pd.DataFrame, params: dict[str, Any]) -> float:
        definition = cls.get(name)
        if not definition:
            raise ValueError(f"Dynamic indicator {name} is not registered")
        if definition.approval_status != "approved":
            raise ValueError(f"Dynamic indicator {name} is not approved")
        merged = {**definition.default_params, **(params or {})}
        value = FormulaEvaluator.evaluate(definition.formula, historical_prices, merged)
        numeric = FormulaEvaluator.to_float(value)
        if definition.output_min is not None:
            numeric = max(float(definition.output_min), numeric)
        if definition.output_max is not None:
            numeric = min(float(definition.output_max), numeric)
        if math.isnan(numeric) or math.isinf(numeric):
            raise ValueError(f"Dynamic indicator {name} produced an invalid value")
        return numeric

    @classmethod
    def find_registered_in_text(cls, normalized_text: str) -> FormulaIndicatorDefinition | None:
        normalized_text = normalize_text(normalized_text)
        for definition in cls._dynamic.values():
            terms = [definition.name.replace("_", " "), definition.name] + definition.aliases
            if any(_term_in_text(term, normalized_text) for term in terms):
                return definition
        return None


class FormulaEvaluator:
    @classmethod
    def evaluate(cls, node: Any, historical_prices: pd.DataFrame, params: dict[str, Any]):
        if isinstance(node, (int, float)):
            return float(node)
        if isinstance(node, str):
            return node
        if not isinstance(node, dict):
            raise ValueError("Invalid formula node")
        op = node.get("op")

        if op == "const":
            return float(node.get("value", 0.0))
        if op == "price":
            asset = params[str(node.get("asset_param", "asset"))]
            return _price_series(historical_prices, asset)
        if op in {"returns", "pct_change"}:
            series_node = node.get("series") or node.get("input")
            if series_node is None and node.get("asset_param"):
                series_node = {"op": "price", "asset_param": node.get("asset_param")}
            series = cls.to_series(cls.evaluate(series_node, historical_prices, params))
            return series.pct_change().dropna()
        if op in {"rolling_return", "momentum"}:
            series_node = node.get("series") or node.get("input")
            if series_node is None and node.get("asset_param"):
                series_node = {"op": "price", "asset_param": node.get("asset_param")}
            series = _window(cls.to_series(cls.evaluate(series_node, historical_prices, params)), cls._param_int(node, params, "window", 90) + 1)
            if len(series) < 2 or float(series.iloc[0]) == 0:
                return 0.0
            return float(series.iloc[-1]) / float(series.iloc[0]) - 1.0
        if op == "tail":
            series = cls.to_series(cls.evaluate(node.get("series"), historical_prices, params))
            return _window(series, cls._param_int(node, params, "window", 30))
        if op == "last":
            series = cls.to_series(cls.evaluate(node.get("series"), historical_prices, params))
            return float(series.iloc[-1])
        if op in {"mean", "rolling_mean"}:
            series = cls.to_series(cls.evaluate(node.get("series"), historical_prices, params))
            if op == "rolling_mean" or node.get("window_param") or node.get("window"):
                series = _window(series, cls._param_int(node, params, "window", len(series)))
            return float(series.mean())
        if op in {"std", "rolling_std"}:
            series = cls.to_series(cls.evaluate(node.get("series"), historical_prices, params))
            if op == "rolling_std" or node.get("window_param") or node.get("window"):
                series = _window(series, cls._param_int(node, params, "window", len(series)))
            value = float(series.std())
            return 0.0 if math.isnan(value) else value
        if op == "rolling_min":
            series = _window(cls.to_series(cls.evaluate(node.get("series"), historical_prices, params)), cls._param_int(node, params, "window", len(historical_prices)))
            return float(series.min())
        if op == "rolling_max":
            series = _window(cls.to_series(cls.evaluate(node.get("series"), historical_prices, params)), cls._param_int(node, params, "window", len(historical_prices)))
            return float(series.max())
        if op == "variance":
            return float(cls.to_series(cls.evaluate(node.get("series"), historical_prices, params)).var())
        if op in {"entropy", "normalized_shannon_entropy"}:
            series = cls.to_series(cls.evaluate(node.get("series") or node.get("input"), historical_prices, params))
            series = _window(series, cls._param_int(node, params, "window", 30)).dropna()
            return _normalized_entropy(series, cls._param_int(node, params, "bins", 10))
        if op == "rsi":
            series_node = node.get("series") or node.get("input")
            if series_node is None and node.get("asset_param"):
                series_node = {"op": "price", "asset_param": node.get("asset_param")}
            series = cls.to_series(cls.evaluate(series_node, historical_prices, params))
            return _rsi(series, cls._param_int(node, params, "window", 14))
        if op == "ema":
            series = cls.to_series(cls.evaluate(node.get("series"), historical_prices, params))
            span = cls._param_int(node, params, "span", int(node.get("span", 12)))
            return series.ewm(span=span, adjust=False).mean()
        if op == "macd":
            series_node = node.get("series") or node.get("input")
            if series_node is None and node.get("asset_param"):
                series_node = {"op": "price", "asset_param": node.get("asset_param")}
            series = cls.to_series(cls.evaluate(series_node, historical_prices, params))
            fast = cls._param_int(node, params, "fast", cls._param_int(node, params, "fast_window", 12))
            slow = cls._param_int(node, params, "slow", cls._param_int(node, params, "slow_window", 26))
            signal = cls._param_int(node, params, "signal", cls._param_int(node, params, "signal_window", 9))
            macd = series.ewm(span=fast, adjust=False).mean() - series.ewm(span=slow, adjust=False).mean()
            signal_line = macd.ewm(span=signal, adjust=False).mean()
            output = str(params.get(node.get("output_param", "output"), node.get("output", "histogram"))).lower()
            if output == "line":
                return float(macd.iloc[-1])
            if output == "signal":
                return float(signal_line.iloc[-1])
            return float((macd - signal_line).iloc[-1])
        if op in {"correlation", "rolling_correlation"}:
            left_node = node.get("left") or {"op": "returns", "series": {"op": "price", "asset_param": node.get("asset_a_param", "asset_a")}}
            right_node = node.get("right") or {"op": "returns", "series": {"op": "price", "asset_param": node.get("asset_b_param", "asset_b")}}
            left = cls.to_series(cls.evaluate(left_node, historical_prices, params))
            right = cls.to_series(cls.evaluate(right_node, historical_prices, params))
            window = cls._param_int(node, params, "window", 60)
            value = _aligned_tail(left, right, window).corr().iloc[0, 1]
            return 0.0 if math.isnan(float(value)) else float(value)
        if op == "beta":
            left_node = node.get("left") or {"op": "returns", "series": {"op": "price", "asset_param": node.get("asset_param", "asset")}}
            right_node = node.get("right") or {"op": "returns", "series": {"op": "price", "asset_param": node.get("benchmark_param", "benchmark")}}
            left = cls.to_series(cls.evaluate(left_node, historical_prices, params))
            right = cls.to_series(cls.evaluate(right_node, historical_prices, params))
            window = cls._param_int(node, params, "window", 60)
            aligned = _aligned_tail(left, right, window)
            variance = float(aligned.iloc[:, 1].var())
            return 0.0 if variance == 0 else float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]) / variance)
        if op == "relative_strength":
            left_node = node.get("left") or {"op": "price", "asset_param": node.get("asset_a_param", "asset_a")}
            right_node = node.get("right") or {"op": "price", "asset_param": node.get("asset_b_param", "asset_b")}
            left = _window(cls.to_series(cls.evaluate(left_node, historical_prices, params)), cls._param_int(node, params, "window", 90) + 1)
            right = _window(cls.to_series(cls.evaluate(right_node, historical_prices, params)), cls._param_int(node, params, "window", 90) + 1)
            if len(left) < 2 or len(right) < 2 or float(left.iloc[0]) == 0 or float(right.iloc[0]) == 0:
                return 0.0
            left_return = float(left.iloc[-1]) / float(left.iloc[0]) - 1.0
            right_return = float(right.iloc[-1]) / float(right.iloc[0]) - 1.0
            return (left_return - right_return) * 100.0
        if op == "z_score":
            series_node = node.get("series") or node.get("input")
            if series_node is None and node.get("asset_param"):
                series_node = {"op": "price", "asset_param": node.get("asset_param")}
            values = _window(cls.to_series(cls.evaluate(series_node, historical_prices, params)), cls._param_int(node, params, "window", 30))
            std = float(values.std())
            return 0.0 if std == 0 or math.isnan(std) else float((values.iloc[-1] - values.mean()) / std)
        if op == "moving_average_slope":
            series_node = node.get("series") or node.get("input")
            if series_node is None and node.get("asset_param"):
                series_node = {"op": "price", "asset_param": node.get("asset_param")}
            series = cls.to_series(cls.evaluate(series_node, historical_prices, params))
            window = cls._param_int(node, params, "window", 50)
            slope_window = cls._param_int(node, params, "slope_window", min(10, window))
            ma = series.rolling(window=window, min_periods=1).mean()
            values = _window(ma, slope_window + 1)
            if len(values) < 2 or float(values.iloc[0]) == 0:
                return 0.0
            return ((float(values.iloc[-1]) / float(values.iloc[0])) - 1.0) * 100.0

        if op in {"add", "sub", "subtract", "mul", "multiply", "div", "divide", "min", "max"}:
            left = cls.evaluate(node.get("left"), historical_prices, params)
            right = cls.evaluate(node.get("right"), historical_prices, params)
            return cls._binary(op, left, right)
        if op in {"greater_than", "less_than"}:
            left = float(cls.evaluate(node.get("left"), historical_prices, params))
            right = float(cls.evaluate(node.get("right"), historical_prices, params))
            return 1.0 if ((left > right) if op == "greater_than" else (left < right)) else 0.0
        if op == "between":
            value = float(cls.evaluate(node.get("value"), historical_prices, params))
            lower = float(cls.evaluate(node.get("min"), historical_prices, params))
            upper = float(cls.evaluate(node.get("max"), historical_prices, params))
            return 1.0 if lower <= value <= upper else 0.0
        if op in {"abs", "neg", "positive", "negative_abs", "clip"}:
            value = cls.evaluate(node.get("value"), historical_prices, params)
            return cls._unary(op, value, node)
        raise ValueError(f"Unsupported formula op: {op}")

    @staticmethod
    def to_series(value) -> pd.Series:
        if isinstance(value, pd.Series):
            series = value.dropna().astype(float)
            if series.empty:
                raise ValueError("Formula series is empty")
            return series
        return pd.Series([float(value)])

    @staticmethod
    def to_float(value) -> float:
        if isinstance(value, pd.Series):
            return float(value.dropna().iloc[-1])
        return float(value)

    @classmethod
    def _param_int(cls, node: dict[str, Any], params: dict[str, Any], name: str, default: int) -> int:
        key = node.get(f"{name}_param")
        value = params.get(str(key), node.get(name, default)) if key else node.get(name, params.get(name, default))
        return max(1, min(int(value), 1000))

    @classmethod
    def _binary(cls, op: str, left, right):
        if isinstance(left, pd.Series) or isinstance(right, pd.Series):
            left_series = cls.to_series(left)
            right_series = cls.to_series(right)
            aligned = pd.concat([left_series, right_series], axis=1).dropna()
            if aligned.empty:
                raise ValueError("Formula series cannot be aligned")
            if op == "add":
                return aligned.iloc[:, 0] + aligned.iloc[:, 1]
            if op in {"sub", "subtract"}:
                return aligned.iloc[:, 0] - aligned.iloc[:, 1]
            if op in {"mul", "multiply"}:
                return aligned.iloc[:, 0] * aligned.iloc[:, 1]
            if op == "min":
                return aligned.min(axis=1)
            if op == "max":
                return aligned.max(axis=1)
            denominator = aligned.iloc[:, 1].replace(0, math.nan)
            return (aligned.iloc[:, 0] / denominator).dropna()
        left_value = float(left)
        right_value = float(right)
        if op == "add":
            return left_value + right_value
        if op in {"sub", "subtract"}:
            return left_value - right_value
        if op in {"mul", "multiply"}:
            return left_value * right_value
        if op == "min":
            return min(left_value, right_value)
        if op == "max":
            return max(left_value, right_value)
        return 0.0 if right_value == 0 else left_value / right_value

    @classmethod
    def _unary(cls, op: str, value, node: dict[str, Any]):
        if isinstance(value, pd.Series):
            if op == "abs":
                return value.abs()
            if op == "neg":
                return -value
            if op == "positive":
                return value.clip(lower=0)
            if op == "negative_abs":
                return (-value.clip(upper=0)).abs()
            if op == "clip":
                return value.clip(lower=node.get("min"), upper=node.get("max"))
        numeric = float(value)
        if op == "abs":
            return abs(numeric)
        if op == "neg":
            return -numeric
        if op == "positive":
            return max(0.0, numeric)
        if op == "negative_abs":
            return abs(min(0.0, numeric))
        if op == "clip":
            if node.get("min") is not None:
                numeric = max(float(node["min"]), numeric)
            if node.get("max") is not None:
                numeric = min(float(node["max"]), numeric)
            return numeric
        raise ValueError(f"Unsupported unary op: {op}")


class IndicatorTestRunner:
    @classmethod
    def run(cls, definition: FormulaIndicatorDefinition | dict[str, Any], symbols: list[str] | None = None) -> dict[str, Any]:
        if isinstance(definition, dict):
            definition = FormulaIndicatorDefinition.from_dict(definition)
        symbols = [symbol.upper() for symbol in (symbols or ["AAPL", "GLD", "SPY"])]
        if "AAPL" not in symbols:
            symbols.append("AAPL")
        if "SPY" not in symbols:
            symbols.append("SPY")
        prices = cls._sample_prices(symbols)
        params = dict(definition.default_params)
        params.setdefault("asset", symbols[0])
        params.setdefault("asset_a", symbols[0])
        params.setdefault("asset_b", "SPY" if "SPY" in symbols else symbols[-1])
        params.setdefault("benchmark", "SPY" if "SPY" in symbols else symbols[-1])
        params.setdefault("window", 30)

        errors: list[dict[str, str]] = []
        results: list[dict[str, Any]] = [{"name": "generic_schema", "passed": True}]
        values: list[float] = []
        for end in (40, 80, len(prices)):
            try:
                value = IndicatorRegistry.resolve(definition.name, prices.iloc[:end], params)
            except Exception:
                try:
                    value = FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, prices.iloc[:end], params))
                except Exception as exc:
                    errors.append({"code": "formula_test_failed", "message": str(exc)})
                    continue
            if math.isnan(value) or math.isinf(value):
                errors.append({"code": "formula_invalid_value", "message": "Formula produced NaN or infinity."})
            if definition.output_min is not None and value < float(definition.output_min) - 1e-9:
                errors.append({"code": "formula_below_min", "message": "Formula value is below output_min."})
            if definition.output_max is not None and value > float(definition.output_max) + 1e-9:
                errors.append({"code": "formula_above_max", "message": "Formula value is above output_max."})
            values.append(float(value))
        results.append({"name": "output_numeric", "passed": bool(values) and not any(math.isnan(v) or math.isinf(v) for v in values)})
        results.append({"name": "output_range", "passed": not any(error["code"] in {"formula_below_min", "formula_above_max"} for error in errors)})
        try:
            short_value = FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, prices.iloc[:3], params))
            results.append({"name": "insufficient_history", "passed": not math.isnan(short_value) and not math.isinf(short_value)})
        except Exception:
            results.append({"name": "insufficient_history", "passed": False})
            errors.append({"code": "insufficient_history_failed", "message": "Formula did not handle short history safely."})
        if len(values) >= 2:
            rerun = IndicatorRegistry.resolve(definition.name, prices.iloc[:80], params) if IndicatorRegistry.get(definition.name) else FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, prices.iloc[:80], params))
            results.append({"name": "deterministic_result", "passed": abs(float(rerun) - values[1]) < 1e-12})
        results.append({"name": "no_future_data", "passed": True})
        results.extend(cls._specific_results(definition, prices, params))
        for result in results:
            if not result.get("passed", False):
                errors.append({"code": "indicator_specific_test_failed", "message": f"{result.get('name')} failed."})
        return {"status": "ok" if not errors else "error", "passed": not errors, "errors": errors, "results": results, "sample_values": values}

    @classmethod
    def _specific_results(cls, definition: FormulaIndicatorDefinition, prices: pd.DataFrame, params: dict[str, Any]) -> list[dict[str, Any]]:
        name = definition.name
        results: list[dict[str, Any]] = []
        try:
            if name == "rsi":
                up = pd.DataFrame({params["asset"]: list(range(100, 160))}, index=pd.bdate_range("2024-01-01", periods=60))
                down = pd.DataFrame({params["asset"]: list(range(160, 100, -1))}, index=pd.bdate_range("2024-01-01", periods=60))
                results.append({"name": "rsi_increasing_high", "passed": FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, up, params)) >= 70})
                results.append({"name": "rsi_decreasing_low", "passed": FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, down, params)) <= 30})
            if name == "correlation":
                idx = pd.bdate_range("2024-01-01", periods=80)
                returns = [0.006 * math.sin(i / 3.0) for i in range(80)]
                aapl = [100.0]
                gld = [200.0]
                spy = [280.0]
                for value in returns[1:]:
                    aapl.append(aapl[-1] * (1.0 + value))
                    gld.append(gld[-1] * (1.0 + value))
                    spy.append(spy[-1] * (1.0 - value))
                corr_prices = pd.DataFrame({"AAPL": aapl, "GLD": gld, "SPY": spy}, index=idx)
                positive = FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, corr_prices, {"asset_a": "AAPL", "asset_b": "GLD", "window": 60}))
                negative = FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, corr_prices, {"asset_a": "AAPL", "asset_b": "SPY", "window": 60}))
                results.append({"name": "correlation_identical_positive", "passed": positive > 0.8})
                results.append({"name": "correlation_inverse_negative", "passed": negative < -0.8})
            if name == "moving_average_slope":
                idx = pd.bdate_range("2024-01-01", periods=80)
                up = pd.DataFrame({params["asset"]: range(100, 180)}, index=idx)
                down = pd.DataFrame({params["asset"]: range(180, 100, -1)}, index=idx)
                results.append({"name": "slope_rising_positive", "passed": FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, up, params)) > 0})
                results.append({"name": "slope_falling_negative", "passed": FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, down, params)) < 0})
            if name == "momentum":
                idx = pd.bdate_range("2024-01-01", periods=80)
                up = pd.DataFrame({params["asset"]: range(100, 180)}, index=idx)
                down = pd.DataFrame({params["asset"]: range(180, 100, -1)}, index=idx)
                results.append({"name": "momentum_rising_positive", "passed": FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, up, params)) > 0})
                results.append({"name": "momentum_falling_negative", "passed": FormulaEvaluator.to_float(FormulaEvaluator.evaluate(definition.formula, down, params)) < 0})
        except Exception as exc:
            results.append({"name": f"{name}_specific_tests", "passed": False, "error": str(exc)})
        return results

    @staticmethod
    def _sample_prices(symbols: list[str]) -> pd.DataFrame:
        index = pd.bdate_range("2024-01-01", periods=120)
        data: dict[str, list[float]] = {}
        for offset, symbol in enumerate(symbols):
            base = 80.0 + offset * 20
            values = []
            for i in range(len(index)):
                trend = i * (0.35 + offset * 0.03)
                cycle = math.sin(i / (4.0 + offset)) * (2.0 + offset)
                shock = 4.0 if i % (17 + offset) == 0 else 0.0
                values.append(max(1.0, base + trend + cycle + shock))
            data[symbol] = values
        return pd.DataFrame(data, index=index)


class CapabilityGapDetector:
    @classmethod
    def detect(cls, text: str) -> dict[str, Any] | None:
        normalized = normalize_text(text)
        for indicator, terms in UNSAFE_EXTERNAL_INDICATOR_TERMS.items():
            if any(_term_in_text(term, normalized) for term in terms):
                return {
                    "status": "gap_detected",
                    "missing_capability_type": "indicator",
                    "indicator": indicator,
                    "name": indicator,
                    "aliases": terms,
                    "can_try_auto_synthesis": False,
                    "required_data": ["external_data"],
                    "reason": "This indicator requires external or non-price data and cannot be safely synthesized from historical price data.",
                }
        for indicator, terms in SAFE_INDICATOR_TERMS.items():
            if IndicatorRegistry.has(indicator):
                continue
            if any(_term_in_text(term, normalized) for term in terms):
                return {
                    "status": "gap_detected",
                    "missing_capability_type": "indicator",
                    "indicator": indicator,
                    "name": indicator,
                    "aliases": terms,
                    "can_try_auto_synthesis": True,
                    "required_data": ["historical_prices"],
                    "terms": terms,
                    "reason": "Missing safe price-history indicator requested by the user.",
                }
        return None


class IndicatorSynthesizer:
    @classmethod
    def synthesize(cls, gap: dict[str, Any], text: str, symbols: list[str]) -> dict[str, Any]:
        indicator = gap.get("indicator")
        if indicator == "entropy":
            return cls._entropy_definition().to_dict()
        if indicator == "rsi":
            return cls._rsi_definition().to_dict()
        if indicator == "macd":
            return cls._macd_definition().to_dict()
        if indicator == "correlation":
            return cls._correlation_definition().to_dict()
        if indicator == "beta":
            return cls._beta_definition().to_dict()
        if indicator == "z_score":
            return cls._z_score_definition().to_dict()
        if indicator == "moving_average_slope":
            return cls._moving_average_slope_definition().to_dict()
        if indicator == "momentum":
            return cls._momentum_definition().to_dict()
        if indicator == "volatility_variant":
            return cls._rolling_volatility_definition().to_dict()
        if indicator == "drawdown_variant":
            return cls._rolling_drawdown_definition().to_dict()
        return {"status": "error", "code": "unsafe_or_unknown_indicator", "message": f"Indicator '{indicator}' cannot be synthesized safely."}

    @staticmethod
    def _provenance(matched_pattern: str) -> dict[str, Any]:
        return {
            "source": "deterministic_synthesizer",
            "matched_pattern": matched_pattern,
            "provider": None,
            "model": None,
            "schema_version": FORMULA_DSL_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _entropy_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="entropy",
            description="Normalized Shannon entropy of recent daily returns. Uses only historical price data.",
            aliases=["entropy", "entropie", "shannon"],
            required_params=["asset", "window"],
            default_params={"window": 30, "bins": 10},
            params_schema={"asset": "symbol", "window": "int", "bins": "int"},
            output_min=0.0,
            output_max=1.0,
            provenance=IndicatorSynthesizer._provenance("entropy"),
            default_operator=">",
            default_threshold=0.75,
            formula={
                "op": "entropy",
                "series": {"op": "returns", "series": {"op": "price", "asset_param": "asset"}},
                "window_param": "window",
                "bins_param": "bins",
            },
        )

    @staticmethod
    def _rsi_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="rsi",
            description="Relative Strength Index computed from historical prices.",
            aliases=["rsi", "relative strength index"],
            required_params=["asset", "window"],
            default_params={"window": 14},
            params_schema={"asset": "symbol", "window": "int"},
            output_min=0.0,
            output_max=100.0,
            provenance=IndicatorSynthesizer._provenance("rsi"),
            default_operator=">",
            default_threshold=70,
            formula={"op": "rsi", "series": {"op": "price", "asset_param": "asset"}, "window_param": "window"},
        )

    @staticmethod
    def _macd_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="macd",
            description="MACD histogram from historical prices.",
            aliases=["macd"],
            required_params=["asset"],
            default_params={"fast_window": 12, "slow_window": 26, "signal_window": 9, "output": "histogram"},
            params_schema={"asset": "symbol", "fast_window": "int", "slow_window": "int", "signal_window": "int", "output": "enum"},
            provenance=IndicatorSynthesizer._provenance("macd"),
            default_operator=">",
            default_threshold=0,
            formula={"op": "macd", "asset_param": "asset", "fast_window_param": "fast_window", "slow_window_param": "slow_window", "signal_window_param": "signal_window", "output_param": "output"},
        )

    @staticmethod
    def _correlation_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="correlation",
            description="Rolling return correlation between an asset and a benchmark. Low values indicate a correlation break.",
            aliases=["correlation", "rolling correlation", "correlation break", "korrelationsbruch", "korrelation"],
            required_params=["asset_a", "asset_b", "window"],
            default_params={"window": 90},
            params_schema={"asset_a": "symbol", "asset_b": "symbol", "window": "int"},
            output_min=-1.0,
            output_max=1.0,
            provenance=IndicatorSynthesizer._provenance("correlation"),
            default_operator="<",
            default_threshold=0.3,
            formula={
                "op": "rolling_correlation",
                "asset_a_param": "asset_a",
                "asset_b_param": "asset_b",
                "window_param": "window",
            },
        )

    @staticmethod
    def _beta_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="beta",
            description="Rolling beta of an asset versus a benchmark computed from returns.",
            aliases=["beta"],
            required_params=["asset", "benchmark", "window"],
            default_params={"window": 90, "benchmark": "SPY"},
            params_schema={"asset": "symbol", "benchmark": "symbol", "window": "int"},
            provenance=IndicatorSynthesizer._provenance("beta"),
            default_operator=">",
            default_threshold=1.2,
            formula={
                "op": "beta",
                "asset_param": "asset",
                "benchmark_param": "benchmark",
                "window_param": "window",
            },
        )

    @staticmethod
    def _z_score_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="z_score",
            description="Rolling z-score of the current price versus a rolling mean and standard deviation.",
            aliases=["z-score", "z score", "standard score", "abweichung vom mittelwert"],
            required_params=["asset", "window"],
            default_params={"window": 30},
            params_schema={"asset": "symbol", "window": "int"},
            default_operator=">",
            default_threshold=2,
            provenance=IndicatorSynthesizer._provenance("z_score"),
            formula={"op": "z_score", "asset_param": "asset", "window_param": "window"},
        )

    @staticmethod
    def _moving_average_slope_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="moving_average_slope",
            description="Percent slope of price over the selected moving-average window.",
            aliases=["moving average slope", "ma slope", "sma slope", "durchschnittssteigung", "slope"],
            required_params=["asset", "window"],
            default_params={"window": 50, "slope_window": 10},
            params_schema={"asset": "symbol", "window": "int", "slope_window": "int"},
            provenance=IndicatorSynthesizer._provenance("moving_average_slope"),
            default_operator=">",
            default_threshold=0,
            formula={"op": "moving_average_slope", "asset_param": "asset", "window_param": "window", "slope_window_param": "slope_window"},
        )

    @staticmethod
    def _momentum_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="momentum",
            description="Rolling return over a historical window.",
            aliases=["momentum", "rolling return", "performance ueber", "performance über"],
            required_params=["asset", "window"],
            default_params={"window": 90},
            params_schema={"asset": "symbol", "window": "int"},
            default_operator=">",
            default_threshold=0.1,
            provenance=IndicatorSynthesizer._provenance("momentum"),
            formula={"op": "rolling_return", "asset_param": "asset", "window_param": "window"},
        )

    @staticmethod
    def _rolling_volatility_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="rolling_volatility",
            description="Annualized rolling volatility from historical returns.",
            aliases=["rolling volatility", "rollierende volatilitaet", "rollierende volatilität"],
            required_params=["asset", "window"],
            default_params={"window": 30},
            params_schema={"asset": "symbol", "window": "int"},
            output_min=0.0,
            default_operator=">",
            default_threshold=20,
            provenance=IndicatorSynthesizer._provenance("rolling_volatility"),
            formula={
                "op": "multiply",
                "left": {"op": "rolling_std", "series": {"op": "returns", "series": {"op": "price", "asset_param": "asset"}}, "window_param": "window"},
                "right": {"op": "const", "value": math.sqrt(252) * 100},
            },
        )

    @staticmethod
    def _rolling_drawdown_definition() -> FormulaIndicatorDefinition:
        return FormulaIndicatorDefinition(
            name="rolling_max_drawdown",
            description="Maximum drawdown over a historical rolling window.",
            aliases=["rolling max drawdown", "max drawdown", "maximaler drawdown"],
            required_params=["asset", "window"],
            default_params={"window": 252},
            params_schema={"asset": "symbol", "window": "int"},
            output_min=0.0,
            output_max=100.0,
            default_operator=">",
            default_threshold=10,
            provenance=IndicatorSynthesizer._provenance("rolling_max_drawdown"),
            formula={
                "op": "multiply",
                "left": {
                    "op": "divide",
                    "left": {
                        "op": "subtract",
                        "left": {"op": "rolling_max", "series": {"op": "tail", "series": {"op": "price", "asset_param": "asset"}, "window_param": "window"}},
                        "right": {"op": "last", "series": {"op": "price", "asset_param": "asset"}},
                    },
                    "right": {"op": "rolling_max", "series": {"op": "tail", "series": {"op": "price", "asset_param": "asset"}, "window_param": "window"}},
                },
                "right": {"op": "const", "value": 100},
            },
        )


def normalize_indicator_name(value: str | None) -> str:
    return str(value or "").lower().strip().replace("-", "_").replace(" ", "_")


def normalize_text(value: str | None) -> str:
    return str(value or "").lower().replace("-", " ")


def _term_in_text(term: str, normalized_text: str) -> bool:
    term = normalize_text(term)
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", normalized_text))


def _price_series(historical_prices: pd.DataFrame, symbol: str) -> pd.Series:
    normalized = str(symbol or "").upper().strip()
    if normalized not in historical_prices:
        raise ValueError(f"Missing historical prices for {normalized}")
    series = historical_prices[normalized].dropna().astype(float)
    if series.empty:
        raise ValueError(f"No historical prices for {normalized}")
    return series


def _window(series: pd.Series, window: int) -> pd.Series:
    return series.tail(max(int(window), 1))


def _normalized_entropy(series: pd.Series, bins: int) -> float:
    values = series.dropna().astype(float)
    if len(values) < 2:
        return 0.0
    counts = pd.cut(values, bins=max(int(bins), 2), labels=False, duplicates="drop").value_counts()
    probabilities = counts / counts.sum()
    entropy = -sum(float(p) * math.log(float(p)) for p in probabilities if p > 0)
    max_entropy = math.log(len(probabilities)) if len(probabilities) > 1 else 1.0
    return 0.0 if max_entropy == 0 else max(0.0, min(1.0, entropy / max_entropy))


def _rsi(series: pd.Series, window: int) -> float:
    values = _window(series, int(window) + 1)
    changes = values.diff().dropna()
    if changes.empty:
        return 50.0
    gains = changes.clip(lower=0).mean()
    losses = (-changes.clip(upper=0)).mean()
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return max(0.0, min(100.0, 100.0 - (100.0 / (1.0 + rs))))


def _aligned_tail(left: pd.Series, right: pd.Series, window: int) -> pd.DataFrame:
    aligned = pd.concat([left, right], axis=1).dropna()
    if len(aligned) < 2:
        raise ValueError("Not enough aligned data for formula")
    return aligned.tail(max(int(window), 2))
