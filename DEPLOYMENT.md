# Deployment

## Railway Setup

Dieses Projekt ist fuer Railway vorbereitet.

1. GitHub-Repo mit Railway verbinden.
2. Neues Railway-Projekt aus dem GitHub-Repo erstellen.
3. PostgreSQL-Service in Railway hinzufuegen.
4. Diese Variablen im Railway-Service setzen:

```env
DATABASE_URL=<wird vom Railway-Postgres-Service bereitgestellt>
SECRET_KEY=<lange zufaellige Zeichenkette>
ALLOWED_ORIGINS=https://<deine-railway-domain>
TAVILY_API_KEY=<optional, fuer Web-KI-Recherche>
AGENT_RATE_LIMIT_PER_MINUTE=20
PUBLIC_SIMULATION_RATE_LIMIT_PER_MINUTE=30
```

Der Startbefehl liegt in `railway.json`:

```bash
uvicorn api:app --host 0.0.0.0 --port $PORT
```

Railway prueft den Service ueber `/health`.

## Wichtige Git-Regeln

Die Datei `.env` darf niemals committed werden.

Lokale SQLite-Dateien wie `backtesting.db` sollen ebenfalls nicht ins Repo. Falls `backtesting.db` bereits getrackt ist, vor dem naechsten Commit einmal aus dem Git-Index entfernen:

```bash
git rm --cached backtesting.db
```

Die Datei bleibt lokal erhalten, wird danach aber nicht mehr gepusht.

## Nach dem Deployment testen

1. `https://<deine-domain>/health` muss `{"status":"ok"}` liefern.
2. `https://<deine-domain>/static/login.html` muss die Login-Seite zeigen.
3. Registrierung und Login testen.
4. Portfolio speichern und Dashboard oeffnen.
5. Backtest starten und pruefen, ob Charts und Vergleich funktionieren.

