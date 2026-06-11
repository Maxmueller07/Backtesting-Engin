import sqlite3
import os

DB_PATH = "backtesting.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            startkapital REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS portfolio_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            anteil INTEGER NOT NULL,
            regeln TEXT DEFAULT '{}',
            FOREIGN KEY (portfolio_id) REFERENCES portfolios(id)
        );

        CREATE TABLE IF NOT EXISTS simulation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            portfolio_id INTEGER,
            name TEXT,
            result TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)

    conn.commit()
    conn.close()
    print("Datenbank initialisiert")


# ── User Funktionen ───────────────────────────────────────────────────────────

def create_user(username: str, email: str, password_hash: str):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, password_hash)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_user_by_username(username: str):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return dict(user) if user else None

def get_user_by_id(user_id: int):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


# ── Portfolio Funktionen ──────────────────────────────────────────────────────

def save_portfolio(user_id: int, name: str, startkapital: float, assets: list):
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO portfolios (user_id, name, startkapital) VALUES (?, ?, ?)",
            (user_id, name, startkapital)
        )
        portfolio_id = cursor.lastrowid

        for asset in assets:
            import json
            conn.execute(
                "INSERT INTO portfolio_assets (portfolio_id, symbol, name, anteil, regeln) VALUES (?, ?, ?, ?, ?)",
                (portfolio_id, asset['symbol'], asset['name'], asset['anteil'], json.dumps(asset.get('regeln', {})))
            )

        conn.commit()
        return portfolio_id
    finally:
        conn.close()

def get_portfolios(user_id: int):
    conn = get_db()
    import json
    portfolios = conn.execute(
        "SELECT * FROM portfolios WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()

    result = []
    for p in portfolios:
        p = dict(p)
        assets = conn.execute(
            "SELECT * FROM portfolio_assets WHERE portfolio_id = ?",
            (p['id'],)
        ).fetchall()
        p['assets'] = [
            {**dict(a), 'regeln': json.loads(a['regeln'])}
            for a in assets
        ]
        result.append(p)

    conn.close()
    return result

def delete_portfolio(portfolio_id: int, user_id: int):
    conn = get_db()
    conn.execute(
        "DELETE FROM portfolio_assets WHERE portfolio_id = ?", (portfolio_id,)
    )
    conn.execute(
        "DELETE FROM portfolios WHERE id = ? AND user_id = ?", (portfolio_id, user_id)
    )
    conn.commit()
    conn.close()


# ── Simulation Results ────────────────────────────────────────────────────────

def save_result(user_id: int, name: str, result: dict, portfolio_id: int = None):
    import json
    conn = get_db()
    conn.execute(
        "INSERT INTO simulation_results (user_id, portfolio_id, name, result) VALUES (?, ?, ?, ?)",
        (user_id, portfolio_id, name, json.dumps(result))
    )
    conn.commit()
    conn.close()

def get_results(user_id: int):
    import json
    conn = get_db()
    results = conn.execute(
        "SELECT id, name, created_at FROM simulation_results WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in results]
