from __future__ import annotations

import math
import os
import re
from typing import Any
from urllib.parse import unquote

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()


DEFAULT_TEMPLATE = {
    "management": True,
    "balance_sheet": True,
    "industry_analysis": True,
    "moat": True,
}

CATEGORY_TITLES = {
    "management": "Management",
    "balance_sheet": "Bilanz",
    "industry_analysis": "Branche",
    "moat": "Burggraben",
}


def normalize_template(template: dict[str, Any] | None) -> dict[str, bool]:
    """Keep only supported agent switches and coerce their values to bool."""
    template = template or {}
    return {
        key: bool(template.get(key, default))
        for key, default in DEFAULT_TEMPLATE.items()
    }


def normalize_instructions(instructions: dict[str, Any] | None) -> dict[str, str]:
    instructions = instructions or {}
    return {
        key: str(instructions.get(key, "") or "").strip()[:500]
        for key in DEFAULT_TEMPLATE
    }


def _safe_get_info(ticker: yf.Ticker) -> dict[str, Any]:
    try:
        return ticker.get_info()
    except Exception:
        try:
            return ticker.info or {}
        except Exception:
            return {}


def _frame_to_records(frame: Any, limit: int = 8) -> list[dict[str, Any]]:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return []

    clean = frame.copy()
    clean = clean.iloc[:limit, : min(len(clean.columns), 4)]
    clean.columns = [str(col.date() if hasattr(col, "date") else col) for col in clean.columns]
    clean = clean.astype(object).where(pd.notnull(clean), None)

    records = []
    for metric, row in clean.iterrows():
        item = {"metric": str(metric)}
        for col, value in row.items():
            if hasattr(value, "item"):
                value = value.item()
            if isinstance(value, float) and math.isnan(value):
                value = None
            item[str(col)] = value
        records.append(item)
    return records


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _clean_text(value: Any, max_len: int = 360) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_len:
        return text
    return f"{text[:max_len].rstrip()}..."


def _expand_instruction(instruction: str) -> str:
    text = instruction.lower()
    expansions = []
    mapping = {
        ("zukunft", "plan", "plaene", "pläne", "strategie", "ausblick"): "future plans strategy outlook roadmap",
        ("konkurrent", "wettbewerb", "rival", "competition"): "top competitors biggest rivals market share",
        ("groessten", "größten", "top", "drei", "3"): "top three largest",
        ("management", "ceo", "cfo", "vorstand"): "management leadership executives",
        ("burggraben", "moat", "vorteil"): "competitive advantage moat",
        ("bilanz", "kennzahl", "roe", "roce", "kgv"): "financial metrics annual report",
    }
    for keys, expansion in mapping.items():
        if any(key in text for key in keys):
            expansions.append(expansion)
    return " ".join(dict.fromkeys(expansions))


def _build_category_query(company: str, symbol: str, category: str, instruction: str, info: dict[str, Any]) -> str:
    base = f"{company} {symbol}".strip()
    if instruction:
        expanded = _expand_instruction(instruction)
        return f"{base} {instruction} {expanded}".strip()

    defaults = {
        "management": "management leadership strategy future plans",
        "balance_sheet": "balance sheet financial metrics annual report",
        "industry_analysis": f"{info.get('industry') or info.get('sector') or ''} competitors market share",
        "moat": "competitive advantage moat brand switching costs",
    }
    return f"{base} {defaults.get(category, '')}".strip()


def _normalize_source(title: Any, url: Any, content: Any, source_type: str) -> dict[str, Any]:
    return {
        "title": _clean_text(title, 120) or "Quelle",
        "url": str(url or ""),
        "content": _clean_text(content, 520),
        "source_type": source_type,
    }


def _search_internet_sources(query: str, max_results: int = 4) -> list[dict[str, Any]]:
    api_key = os.getenv("TAVILY_API_KEY")
    if api_key:
        try:
            from tavily import TavilyClient

            client = TavilyClient(api_key=api_key)
            response = client.search(query=query, max_results=max_results, include_answer=True)
            sources = []
            answer = response.get("answer") if isinstance(response, dict) else None
            if answer:
                sources.append(_normalize_source("Tavily Antwort", "", answer, "tavily_answer"))

            for result in (response.get("results", []) if isinstance(response, dict) else [])[:max_results]:
                if not isinstance(result, dict):
                    continue
                sources.append(_normalize_source(
                    result.get("title"),
                    result.get("url"),
                    result.get("content") or result.get("snippet"),
                    "web",
                ))
            if sources:
                return sources
        except Exception:
            pass

    return _search_duckduckgo_sources(query, max_results=max_results)


def _search_duckduckgo_sources(query: str, max_results: int = 4) -> list[dict[str, Any]]:
    try:
        import requests
        from bs4 import BeautifulSoup

        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=3,
        )
        response.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    sources = []
    for result in soup.select(".result")[:max_results]:
        link = result.select_one(".result__a")
        snippet = result.select_one(".result__snippet")
        if not link:
            continue
        href = link.get("href", "")
        if "uddg=" in href:
            href = unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        sources.append(_normalize_source(
            link.get_text(" ", strip=True),
            href,
            snippet.get_text(" ", strip=True) if snippet else "",
            "duckduckgo",
        ))
    return sources


def _news_sources_from_yfinance(symbol: str, instruction: str, max_results: int = 4) -> list[dict[str, Any]]:
    try:
        news = yf.Ticker(symbol).news or []
    except Exception:
        return []
    if not isinstance(news, list):
        return []

    expanded = f"{instruction} {_expand_instruction(instruction)}"
    words = {w for w in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", expanded.lower())}
    sources = []
    fallback_sources = []
    for item in news:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        title = content.get("title") or item.get("title")
        summary = content.get("summary") or content.get("description") or item.get("summary")
        url = (
            content.get("canonicalUrl", {}).get("url")
            if isinstance(content.get("canonicalUrl"), dict)
            else content.get("link") or item.get("link")
        )
        haystack = f"{title or ''} {summary or ''}".lower()
        source = _normalize_source(title, url, summary, "yfinance_news")
        fallback_sources.append(source)
        if words and not any(word in haystack for word in words):
            continue
        sources.append(source)
        if len(sources) >= max_results:
            break
    return sources or fallback_sources[:max_results]


def _source_items(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": source.get("title"),
            "value": source.get("content"),
            "url": source.get("url"),
            "source_type": source.get("source_type"),
        }
        for source in sources
    ]


def _web_summary(category: str, instruction: str, web_context: dict[str, Any], fallback: str) -> str:
    if not instruction:
        return fallback

    context = web_context.get(category, {})
    count = context.get("source_count", 0)
    query = context.get("query", instruction)
    if count:
        return f"Suchauftrag '{instruction}' wurde mit Query '{query}' ausgefuehrt; {count} Quellen wurden fuer diesen Abschnitt ausgewertet."
    return f"Suchauftrag '{instruction}' wurde mit Query '{query}' ausgefuehrt; es wurden keine passenden Web-/Newsquellen gefunden, deshalb nutze ich verfuegbare yfinance-Daten als Fallback."


def _items_with_web_context(base_items: list[dict[str, Any]], category: str, instruction: str, web_context: dict[str, Any]) -> list[dict[str, Any]]:
    if not instruction:
        return base_items

    context = web_context.get(category, {})
    sources = _source_items(context.get("sources", []))
    search_item = {
        "label": "Suchauftrag",
        "value": context.get("query", instruction),
        "source_type": "agent_query",
    }
    if sources:
        return [search_item, *sources, *base_items]
    return [search_item, *base_items]


def fetch_web_context(state: dict[str, Any]) -> dict[str, Any]:
    data = state.get("financial_data", {})
    info = data.get("info", {})
    template = normalize_template(data.get("template") or state.get("template"))
    instructions = normalize_instructions(data.get("instructions") or state.get("instructions"))
    symbol = data.get("symbol") or state.get("symbol", "")
    company = data.get("name") or info.get("longName") or symbol

    web_context: dict[str, Any] = {}
    for category, enabled in template.items():
        if not enabled:
            continue
        instruction = instructions.get(category, "")
        query = _build_category_query(company, symbol, category, instruction, info)
        sources = _search_internet_sources(query)
        if not sources:
            sources = _news_sources_from_yfinance(symbol, instruction)
        web_context[category] = {
            "query": query,
            "sources": sources,
            "source_count": len(sources),
        }

    return {"web_context": web_context}


def _fmt_money(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)

    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} Mrd."
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.2f} Mio."
    return f"{value:,.0f}"


def _fmt_percent(value: Any) -> str:
    if value in (None, ""):
        return "n/a"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _instruction_terms(text: str) -> list[str]:
    return [term.strip().lower() for term in re.split(r"[,;/\n]+|\s+und\s+|\s+oder\s+", text) if term.strip()]


def _latest_statement_value(frame: Any, row_patterns: list[str]) -> Any:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    for row_name, row in frame.iterrows():
        normalized = str(row_name).lower()
        if all(pattern.lower() in normalized for pattern in row_patterns):
            values = row.dropna()
            if not values.empty:
                value = values.iloc[0]
                return value.item() if hasattr(value, "item") else value
    return None


def _metric_items_from_instructions(
    instructions: str,
    info: dict[str, Any],
    balance_sheet: Any,
    financials: Any,
    cashflow: Any,
) -> list[dict[str, Any]]:
    terms = _instruction_terms(instructions)
    normalized_text = re.sub(r"[^a-z0-9]+", "", instructions.lower())
    items: list[dict[str, Any]] = []

    metric_map = {
        "roe": ("ROE", info.get("returnOnEquity"), _fmt_percent, "yfinance info.returnOnEquity"),
        "returnonequity": ("ROE", info.get("returnOnEquity"), _fmt_percent, "yfinance info.returnOnEquity"),
        "roce": ("ROCE", info.get("returnOnCapital"), _fmt_percent, "yfinance info.returnOnCapital"),
        "returnoncapital": ("ROCE", info.get("returnOnCapital"), _fmt_percent, "yfinance info.returnOnCapital"),
        "kgv": ("KGV", info.get("trailingPE"), str, "yfinance info.trailingPE"),
        "pe": ("KGV", info.get("trailingPE"), str, "yfinance info.trailingPE"),
        "p/e": ("KGV", info.get("trailingPE"), str, "yfinance info.trailingPE"),
        "verschuldung": ("Gesamtverschuldung", _latest_statement_value(balance_sheet, ["total", "debt"]), _fmt_money, "yfinance balance_sheet"),
        "debt": ("Gesamtverschuldung", _latest_statement_value(balance_sheet, ["total", "debt"]), _fmt_money, "yfinance balance_sheet"),
        "freecashflow": ("Free Cashflow", info.get("freeCashflow") or _latest_statement_value(cashflow, ["free", "cash", "flow"]), _fmt_money, "yfinance cashflow/info"),
        "free cashflow": ("Free Cashflow", info.get("freeCashflow") or _latest_statement_value(cashflow, ["free", "cash", "flow"]), _fmt_money, "yfinance cashflow/info"),
        "umsatz": ("Umsatz", info.get("totalRevenue") or _latest_statement_value(financials, ["total", "revenue"]), _fmt_money, "yfinance financials/info"),
        "revenue": ("Umsatz", info.get("totalRevenue") or _latest_statement_value(financials, ["total", "revenue"]), _fmt_money, "yfinance financials/info"),
        "marge": ("Gewinnmarge", info.get("profitMargins"), _fmt_percent, "yfinance info.profitMargins"),
        "margin": ("Gewinnmarge", info.get("profitMargins"), _fmt_percent, "yfinance info.profitMargins"),
    }

    seen = set()
    for alias, metric in metric_map.items():
        alias_normalized = re.sub(r"[^a-z0-9]+", "", alias.lower())
        if alias not in terms and alias_normalized not in normalized_text:
            continue
        label, raw_value, formatter, source = metric
        if label in seen:
            continue
        seen.add(label)
        items.append({
            "label": label,
            "value": formatter(raw_value) if raw_value is not None else "n/a",
            "source": source,
        })

    return items


def fetch_yfinance_data(state: dict[str, Any]) -> dict[str, Any]:
    symbol = state["symbol"].upper().strip()
    ticker = yf.Ticker(symbol)
    info = _safe_get_info(ticker)
    template = normalize_template(state.get("template"))

    data: dict[str, Any] = {
        "symbol": symbol,
        "name": state.get("name") or info.get("longName") or info.get("shortName") or symbol,
        "info": info,
        "template": template,
        "instructions": normalize_instructions(state.get("instructions")),
    }

    if template["balance_sheet"]:
        try:
            data["raw_balance_sheet"] = ticker.balance_sheet
            data["balance_sheet"] = _frame_to_records(data["raw_balance_sheet"])
        except Exception as exc:
            data["balance_sheet_error"] = str(exc)

        try:
            data["raw_financials"] = ticker.financials
        except Exception:
            data["raw_financials"] = None

        try:
            data["raw_cashflow"] = ticker.cashflow
        except Exception:
            data["raw_cashflow"] = None

    return {"financial_data": data}


def analyze_financial_data(state: dict[str, Any]) -> dict[str, Any]:
    data = state.get("financial_data", {})
    info = data.get("info", {})
    template = normalize_template(data.get("template"))
    instructions = normalize_instructions(data.get("instructions"))
    web_context = state.get("web_context", {})

    sections: list[dict[str, Any]] = []

    if template["management"]:
        officers = info.get("companyOfficers") or []
        management = [
            {
                "name": officer.get("name", "Unbekannt"),
                "title": officer.get("title", "Rolle nicht angegeben"),
                "age": officer.get("age"),
            }
            for officer in officers[:5]
            if isinstance(officer, dict)
        ]
        if not management and info.get("longBusinessSummary"):
            management = [{"name": "Management", "title": "In yfinance nicht einzeln ausgewiesen", "age": None}]
        fallback = "Fuehrungsteam und Management-Profile aus yfinance-Unternehmensdaten."
        sections.append({
            "key": "management",
            "title": "Management",
            "items": _items_with_web_context(management, "management", instructions["management"], web_context),
            "summary": _web_summary("management", instructions["management"], web_context, fallback),
            "requested_focus": instructions["management"],
            "search_query": web_context.get("management", {}).get("query", ""),
            "sources": web_context.get("management", {}).get("sources", []),
        })

    if template["balance_sheet"]:
        balance_sheet = data.get("balance_sheet", [])
        latest = balance_sheet[0] if balance_sheet else {}
        requested_metrics = _metric_items_from_instructions(
            instructions["balance_sheet"],
            info,
            data.get("raw_balance_sheet"),
            data.get("raw_financials"),
            data.get("raw_cashflow"),
        )
        fallback = (
            f"Aus deinen Vorgaben wurden {len(requested_metrics)} gezielte Kennzahlen extrahiert."
            if requested_metrics else
            f"Aktuellste verfuegbare Bilanzkennzahl: {latest.get('metric', 'n/a')} "
            f"mit Wert {_fmt_money(next((v for k, v in latest.items() if k != 'metric' and v is not None), None))}."
            if latest else "Keine Bilanzdaten ueber yfinance verfuegbar."
        )
        base_items = requested_metrics or balance_sheet
        sections.append({
            "key": "balance_sheet",
            "title": "Bilanz",
            "items": _items_with_web_context(base_items, "balance_sheet", instructions["balance_sheet"], web_context),
            "summary": _web_summary("balance_sheet", instructions["balance_sheet"], web_context, fallback),
            "requested_focus": instructions["balance_sheet"],
            "search_query": web_context.get("balance_sheet", {}).get("query", ""),
            "sources": web_context.get("balance_sheet", {}).get("sources", []),
        })

    if template["industry_analysis"]:
        sector = info.get("sector") or "n/a"
        industry = info.get("industry") or "n/a"
        market_cap = _fmt_money(info.get("marketCap"))
        trailing_pe = info.get("trailingPE", "n/a")
        profit_margin = info.get("profitMargins", "n/a")
        industry_items = [
            {"label": "Sektor", "value": sector},
            {"label": "Industrie", "value": industry},
            {"label": "Marktkapitalisierung", "value": market_cap},
            {"label": "KGV", "value": trailing_pe},
            {"label": "Gewinnmarge", "value": profit_margin},
            {"label": "Benutzerfokus", "value": instructions["industry_analysis"] or "Standard-Branchenprofil"},
        ]
        fallback = f"{data.get('name')} ist laut yfinance im Sektor {sector} und in der Industrie {industry} eingeordnet."
        sections.append({
            "key": "industry_analysis",
            "title": "Branche",
            "items": _items_with_web_context(industry_items, "industry_analysis", instructions["industry_analysis"], web_context),
            "summary": _web_summary("industry_analysis", instructions["industry_analysis"], web_context, fallback),
            "requested_focus": instructions["industry_analysis"],
            "search_query": web_context.get("industry_analysis", {}).get("query", ""),
            "sources": web_context.get("industry_analysis", {}).get("sources", []),
        })

    if template["moat"]:
        moat_signals = []
        if info.get("marketCap"):
            moat_signals.append("Groesse/Skaleneffekte")
        if info.get("grossMargins") and info.get("grossMargins") > 0.35:
            moat_signals.append("ueberdurchschnittliche Bruttomarge")
        if info.get("returnOnEquity") and info.get("returnOnEquity") > 0.15:
            moat_signals.append("hohe Eigenkapitalrendite")
        if info.get("heldPercentInstitutions") and info.get("heldPercentInstitutions") > 0.5:
            moat_signals.append("starke institutionelle Nachfrage")
        focus_text = instructions["moat"].lower()
        if "netzwerk" in focus_text:
            moat_signals.append("Netzwerkeffekt als gewuenschter Analysefokus")
        if "marke" in focus_text:
            moat_signals.append("Markenstaerke als gewuenschter Analysefokus")
        if "switch" in focus_text or "wechsel" in focus_text:
            moat_signals.append("Switching Costs als gewuenschter Analysefokus")
        if not moat_signals:
            moat_signals.append("kein klarer quantitativer Burggraben aus den yfinance-Kennzahlen ableitbar")
        moat_items = [{"signal": signal} for signal in moat_signals]
        fallback = "Moat-Einschaetzung aus Groesse, Margen, Kapitalrendite und Marktposition abgeleitet."
        sections.append({
            "key": "moat",
            "title": "Burggraben",
            "items": _items_with_web_context(moat_items, "moat", instructions["moat"], web_context),
            "summary": _web_summary("moat", instructions["moat"], web_context, fallback),
            "requested_focus": instructions["moat"],
            "search_query": web_context.get("moat", {}).get("query", ""),
            "sources": web_context.get("moat", {}).get("sources", []),
        })

    summary = (
        f"KI-Analyse fuer {data.get('name')} ({data.get('symbol')}): "
        f"{len(sections)} aktivierte Analysebereiche wurden mit yfinance-Live-Daten ausgewertet."
    )

    return _json_safe({
        "analysis": {
            "symbol": data.get("symbol"),
            "name": data.get("name"),
            "summary": summary,
            "sections": sections,
            "data_source": "yfinance + variable web/news context",
        }
    })


def build_initial_state(
    symbol: str,
    name: str | None,
    template: dict[str, Any] | None,
    instructions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": name,
        "template": normalize_template(template),
        "instructions": normalize_instructions(instructions),
        "financial_data": {},
        "web_context": {},
        "analysis": {},
    }
