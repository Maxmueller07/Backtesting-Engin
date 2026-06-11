from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from main import simuliere
from Protfolio import Portfolio
from auth import hash_password, verify_password, create_token, get_current_user
from database import init_db, create_user, get_user_by_username, save_portfolio, get_portfolios, delete_portfolio, \
    save_result, get_results

app = FastAPI()


# Datenbank beim Start initialisieren
@app.on_event("startup")
def startup():
    init_db()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="."), name="static")


# ── Pydantic Models ───────────────────────────────────────────────────────────

class RegisterData(BaseModel):
    username: str
    email: str
    password: str


class LoginData(BaseModel):
    username: str
    password: str


class AssetConfig(BaseModel):
    name: str
    symbol: str
    anteil: int
    regeln: dict = {}


class SchwellwertConfig(BaseModel):
    schwelle: float = 100000
    von: str = ""
    zu: str = ""
    prozent: float = 20


class SimulationsConfig(BaseModel):
    startkapital: float
    startdatum: str
    enddatum: str
    intervall: int = 362
    sp_start: float = 500
    aktive_regeln: list
    assets: list[AssetConfig]
    schwellwert_config: SchwellwertConfig = SchwellwertConfig()
    name: Optional[str] = None
    speichern: bool = False


class PortfolioSpeichern(BaseModel):
    name: str
    startkapital: float
    assets: list[AssetConfig]


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


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
    assets = [a.dict() for a in data.assets]
    portfolio_id = save_portfolio(current_user["user_id"], data.name, data.startkapital, assets)
    return {"portfolio_id": portfolio_id, "message": "Portfolio gespeichert"}


@app.get("/portfolios")
def portfolios_laden(current_user: dict = Depends(get_current_user)):
    return get_portfolios(current_user["user_id"])


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
    portfolio = Portfolio(config.startkapital, True)

    for a in config.assets:
        portfolio.add_asset(a.name, a.symbol, a.anteil, 0, regeln=a.regeln)

    if not portfolio.check_antiel():
        raise HTTPException(status_code=400, detail="Anteile ergeben nicht 100%")

    ergebnis = simuliere(
        portfolio=portfolio,
        aktive_regeln=config.aktive_regeln,
        startdatum=config.startdatum,
        enddatum=config.enddatum,
        intervall=config.intervall,
        sp_start=config.sp_start
    )

    ergebnis["historie"] = ergebnis["historie"].to_dict()

    # Optional: Ergebnis automatisch speichern
    if config.speichern and config.name:
        speicherbar = {k: v for k, v in ergebnis.items() if k != "historie"}
        save_result(current_user["user_id"], config.name, speicherbar)

    return ergebnis


# ── Öffentliche Simulation (ohne Login, für Tests) ────────────────────────────

@app.post("/simuliere/public")
def simuliere_public(config: SimulationsConfig):
    portfolio = Portfolio(config.startkapital, True)

    for a in config.assets:
        portfolio.add_asset(a.name, a.symbol, a.anteil, 0, regeln=a.regeln)

    if not portfolio.check_antiel():
        raise HTTPException(status_code=400, detail="Anteile ergeben nicht 100%")

    ergebnis = simuliere(
        portfolio=portfolio,
        aktive_regeln=config.aktive_regeln,
        startdatum=config.startdatum,
        enddatum=config.enddatum,
        intervall=config.intervall,
        sp_start=config.sp_start
    )

    ergebnis["historie"] = ergebnis["historie"].to_dict()
    return ergebnis