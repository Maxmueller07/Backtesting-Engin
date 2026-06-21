from collections import defaultdict, deque
import os
import re
import time

from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional
import math

from ai_rule_builder import example_tests_for_rule, validate_rule_payload
from agent_graph import run_agent_analysis
from dashboard import build_portfolio_dashboard
from main import simuliere
from Protfolio import Portfolio
from rule_agent_graph import run_rule_builder_agent
from auth import hash_password, verify_password, create_token, get_current_user
from database import init_db, create_user, get_user_by_username, save_portfolio, get_portfolios, delete_portfolio, \
    save_result, get_results
from ticker_resolver import resolve_ticker_candidates

app = FastAPI()
AGENT_RATE_LIMIT = int(os.getenv("AGENT_RATE_LIMIT_PER_MINUTE", "20"))
AGENT_RATE_WINDOW = 60
AGENT_CALLS = defaultdict(deque)
PUBLIC_SIMULATION_RATE_LIMIT = int(os.getenv("PUBLIC_SIMULATION_RATE_LIMIT_PER_MINUTE", "30"))
PUBLIC_SIMULATION_CALLS = defaultdict(deque)
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",")
    if origin.strip()
]
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-=]{0,24}$")


# Datenbank beim Start initialisieren
@app.on_event("startup")
def startup():
    init_db()


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="."), name="static")


# ── Pydantic Models ───────────────────────────────────────────────────────────

class RegisterData(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    email: str = Field(max_length=160)
    password: str = Field(min_length=6, max_length=200)


class LoginData(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class AssetConfig(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    symbol: str = Field(min_length=1, max_length=25)
    anteil: int = Field(gt=0, le=100)
    waehrung: Optional[str] = None
    steuer_typ: Optional[str] = "aktie"
    regeln: dict = Field(default_factory=dict)


class SchwellwertConfig(BaseModel):
    schwelle: float = Field(default=100000, ge=0)
    von: str = ""
    zu: str = ""
    prozent: float = Field(default=20, ge=0, le=100)


class StopLossConfig(BaseModel):
    ausstieg_prozent: float = Field(default=15, ge=0, le=100)
    wiedereinstieg_prozent: float = Field(default=0, ge=0)


class TransaktionskostenConfig(BaseModel):
    aktiv: bool = False
    ordergebuehr_fix: float = Field(default=0, ge=0)
    ordergebuehr_prozent: float = Field(default=0, ge=0)
    mindestgebuehr: float = Field(default=0, ge=0)
    maximalgebuehr: float = Field(default=0, ge=0)


class SteuerConfig(BaseModel):
    aktiv: bool = False
    land: str = "DE"
    jahreseinkommen: float = Field(default=45000, ge=0)
    automatisch_aus_einkommen: bool = True
    sparer_pauschbetrag: float = Field(default=1000, ge=0)
    kapitalertragsteuer: float = Field(default=25, ge=0, le=100)
    solidaritaetszuschlag: float = Field(default=5.5, ge=0, le=100)
    kirchensteuer: float = Field(default=0, ge=0, le=20)
    tax_loss_harvesting: bool = False
    harvesting_schwelle_prozent: float = Field(default=5, ge=0, le=100)


class SimulationsConfig(BaseModel):
    startkapital: float = Field(gt=0)
    startdatum: str
    enddatum: str
    basiswaehrung: str = "EUR"
    intervall: int = Field(default=362, gt=0)
    sp_start: float = Field(default=500, ge=0)
    sparplan_dynamisierung: float = Field(default=10, ge=0)
    sparplan_limit: float = Field(default=2000, ge=0)
    aktive_regeln: list
    assets: list[AssetConfig]
    schwellwert_config: SchwellwertConfig = Field(default_factory=SchwellwertConfig)
    stop_loss_config: StopLossConfig = Field(default_factory=StopLossConfig)
    transaktionskosten_config: TransaktionskostenConfig = Field(default_factory=TransaktionskostenConfig)
    steuer_config: SteuerConfig = Field(default_factory=SteuerConfig)
    custom_regeln: list[dict] = Field(default_factory=list)
    name: Optional[str] = None
    speichern: bool = False


class PortfolioSpeichern(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    startkapital: float
    basiswaehrung: str = "EUR"
    assets: list[AssetConfig]


class AgentTemplateConfig(BaseModel):
    management: bool = True
    balance_sheet: bool = True
    industry_analysis: bool = True
    moat: bool = True


class AgentInstructionConfig(BaseModel):
    management: str = Field(default="", max_length=500)
    balance_sheet: str = Field(default="", max_length=500)
    industry_analysis: str = Field(default="", max_length=500)
    moat: str = Field(default="", max_length=500)


class AgentAnalysisRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=25)
    name: Optional[str] = Field(default=None, max_length=120)
    template: AgentTemplateConfig = Field(default_factory=AgentTemplateConfig)
    instructions: AgentInstructionConfig = Field(default_factory=AgentInstructionConfig)


class RuleBuildRequest(BaseModel):
    natural_language_rule: str = Field(min_length=5, max_length=5000)
    portfolio_symbols: list[str] = Field(default_factory=list, max_length=40)
    base_currency: str = "EUR"
    risk_level: str = "safe"
    new_asset_mode: str = Field(default="portfolio_only", max_length=20)


class RuleValidateRequest(BaseModel):
    rule: dict
    portfolio_symbols: list[str] = Field(default_factory=list, max_length=40)


class RuleExampleTestsRequest(BaseModel):
    rule: dict


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ticker/resolve")
def ticker_resolve(q: str = Query(..., min_length=1, max_length=80), market: str = Query("AUTO", max_length=20)):
    return {"query": q, "market": market, "candidates": resolve_ticker_candidates(q, market)}


@app.post("/agent/analyze")
def agent_analyze(data: AgentAnalysisRequest, current_user: dict = Depends(get_current_user)):
    symbol = data.symbol.upper().strip()
    if not SYMBOL_PATTERN.match(symbol):
        raise HTTPException(status_code=400, detail="Ungueltiges Symbol")

    _rate_limit_agent(current_user)

    try:
        template = data.template.model_dump() if hasattr(data.template, "model_dump") else data.template.dict()
        instructions = data.instructions.model_dump() if hasattr(data.instructions, "model_dump") else data.instructions.dict()
        return run_agent_analysis(
            symbol=symbol,
            name=data.name,
            template=template,
            instructions=instructions
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"KI-Agent konnte die Aktie nicht analysieren: {exc}")


@app.post("/rules/build")
def rules_build(data: RuleBuildRequest, current_user: dict = Depends(get_current_user)):
    _rate_limit_agent(current_user)
    symbols = _validate_symbol_list(data.portfolio_symbols)
    return run_rule_builder_agent(
        natural_language_rule=data.natural_language_rule,
        portfolio_symbols=symbols,
        base_currency=data.base_currency,
        risk_level=data.risk_level,
        new_asset_mode=data.new_asset_mode,
    )


@app.post("/rules/validate")
def rules_validate(data: RuleValidateRequest, current_user: dict = Depends(get_current_user)):
    symbols = _validate_symbol_list(data.portfolio_symbols)
    return validate_rule_payload(data.rule, symbols)


@app.post("/rules/example-tests")
def rules_example_tests(data: RuleExampleTestsRequest, current_user: dict = Depends(get_current_user)):
    try:
        return example_tests_for_rule(data.rule)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Regeltests konnten nicht erzeugt werden: {exc}")


def _rate_limit_agent(current_user: dict):
    key = str(current_user.get("user_id") or current_user.get("username") or "unknown")
    _rate_limit_bucket(
        AGENT_CALLS,
        key,
        AGENT_RATE_LIMIT,
        "KI-Agent Rate-Limit erreicht. Bitte kurz warten.",
    )


def _rate_limit_public_simulation(request: Request):
    key = request.client.host if request.client else "unknown"
    _rate_limit_bucket(
        PUBLIC_SIMULATION_CALLS,
        key,
        PUBLIC_SIMULATION_RATE_LIMIT,
        "Public Simulation Rate-Limit erreicht. Bitte kurz warten.",
    )


def _rate_limit_bucket(bucket, key: str, limit: int, detail: str):
    now = time.time()
    calls = bucket[key]
    while calls and now - calls[0] > AGENT_RATE_WINDOW:
        calls.popleft()
    if len(calls) >= limit:
        raise HTTPException(status_code=429, detail=detail)
    calls.append(now)


def _validate_symbol_list(symbols: list[str]) -> list[str]:
    normalized = []
    for symbol in symbols:
        value = str(symbol).upper().strip()
        if not SYMBOL_PATTERN.match(value):
            raise HTTPException(status_code=400, detail=f"Ungueltiges Symbol: {symbol}")
        normalized.append(value)
    return normalized


def _model_to_dict(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _simuliere_config(config: SimulationsConfig):
    portfolio = Portfolio(config.startkapital, True)

    for asset in config.assets:
        symbol = asset.symbol.upper().strip()
        if not SYMBOL_PATTERN.match(symbol):
            raise HTTPException(status_code=400, detail=f"Ungueltiges Symbol: {asset.symbol}")
        portfolio.add_asset(
            asset.name,
            symbol,
            asset.anteil,
            0,
            regeln=asset.regeln,
            waehrung=asset.waehrung,
            steuer_typ=asset.steuer_typ,
        )

    if not portfolio.check_antiel():
        raise HTTPException(status_code=400, detail="Anteile ergeben nicht 100%")

    if config.custom_regeln:
        symbols = [asset.symbol.upper().strip() for asset in config.assets]
        for rule in config.custom_regeln:
            validation = validate_rule_payload(rule, symbols)
            if not validation["valid"]:
                raise HTTPException(status_code=400, detail={"message": "Custom Rule ungueltig", "errors": validation["errors"]})

    try:
        ergebnis = simuliere(
            portfolio=portfolio,
            aktive_regeln=config.aktive_regeln,
            startdatum=config.startdatum,
            enddatum=config.enddatum,
            intervall=config.intervall,
            sp_start=config.sp_start,
            schwellwert_config=_model_to_dict(config.schwellwert_config),
            stop_loss_config=_model_to_dict(config.stop_loss_config),
            sparplan_dynamisierung=config.sparplan_dynamisierung / 100,
            sparplan_limit=config.sparplan_limit,
            basiswaehrung=config.basiswaehrung,
            transaktionskosten_config=_model_to_dict(config.transaktionskosten_config),
            steuer_config=_model_to_dict(config.steuer_config),
            custom_regeln=config.custom_regeln,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Simulation fehlgeschlagen: {exc}")

    ergebnis["historie"] = ergebnis["historie"].to_dict()
    return _json_safe(ergebnis)


# ── Auth Endpoints (fehlten komplett!) ────────────────────────────────────────

@app.post("/auth/register")
def register(data: RegisterData):
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Passwort mindestens 6 Zeichen")
    if len(data.username) < 3:
        raise HTTPException(status_code=400, detail="Username mindestens 3 Zeichen")

    password_hash = hash_password(data.password)
    erfolg = create_user(data.username, data.email, password_hash)

    if not erfolg:
        raise HTTPException(status_code=409, detail="Username oder Email bereits vergeben")

    return {"message": "Registrierung erfolgreich"}


@app.post("/auth/login")
def login(data: LoginData):
    user = get_user_by_username(data.username)

    if not user:
        raise HTTPException(status_code=401, detail="Username oder Passwort falsch")

    if not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Username oder Passwort falsch")

    token = create_token(user["id"], user["username"])

    return {
        "token": token,
        "username": user["username"],
        "user_id": user["id"]
    }


@app.get("/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user


# ── Portfolio Endpoints ───────────────────────────────────────────────────────

@app.post("/portfolios")
def portfolio_speichern(data: PortfolioSpeichern, current_user: dict = Depends(get_current_user)):
    assets = [_model_to_dict(a) for a in data.assets]
    portfolio_id = save_portfolio(
        current_user["user_id"],
        data.name,
        data.startkapital,
        assets,
        basiswaehrung=data.basiswaehrung,
    )
    return {"portfolio_id": portfolio_id, "message": "Portfolio gespeichert"}


@app.get("/portfolios")
def portfolios_laden(current_user: dict = Depends(get_current_user)):
    return get_portfolios(current_user["user_id"])


@app.get("/dashboard/portfolios")
def portfolio_dashboard_laden(current_user: dict = Depends(get_current_user)):
    portfolios = get_portfolios(current_user["user_id"])
    return {
        "portfolios": [
            build_portfolio_dashboard(portfolio)
            for portfolio in portfolios
        ]
    }


@app.delete("/portfolios/{portfolio_id}")
def portfolio_loeschen(portfolio_id: int, current_user: dict = Depends(get_current_user)):
    delete_portfolio(portfolio_id, current_user["user_id"])
    return {"message": "Portfolio gelöscht"}


# ── Simulations-Ergebnisse ────────────────────────────────────────────────────

@app.get("/results")
def ergebnisse_laden(current_user: dict = Depends(get_current_user)):
    return get_results(current_user["user_id"])


# ── Simulation ────────────────────────────────────────────────────────────────

@app.post("/simuliere")
def simuliere_endpoint(config: SimulationsConfig, current_user: dict = Depends(get_current_user)):
    ergebnis = _simuliere_config(config)

    # Optional: Ergebnis automatisch speichern
    if config.speichern and config.name:
        speicherbar = {k: v for k, v in ergebnis.items() if k != "historie"}
        save_result(current_user["user_id"], config.name, speicherbar)

    return ergebnis


# ── Öffentliche Simulation (ohne Login, für Tests) ────────────────────────────

@app.post("/simuliere/public")
def simuliere_public(config: SimulationsConfig, request: Request):
    _rate_limit_public_simulation(request)
    return _simuliere_config(config)
