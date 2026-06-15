import json
import os
import sqlite3
from urllib.parse import urlparse


DB_PATH = os.getenv("DB_PATH", "backtesting.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def _is_postgres():
    return DATABASE_URL.startswith(("postgres://", "postgresql://"))


def _param():
    return "%s" if _is_postgres() else "?"


def _placeholders(count):
    return ", ".join([_param()] * count)


def _normalize_database_url(url):
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def get_db():
    if _is_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL benoetigt das Paket psycopg[binary].") from exc
        return psycopg.connect(_normalize_database_url(DATABASE_URL), row_factory=dict_row)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row):
    return dict(row) if row else None


def _fetchone(cursor, sql, params=()):
    cursor.execute(sql, params)
    return cursor.fetchone()


def _fetchall(cursor, sql, params=()):
    cursor.execute(sql, params)
    return cursor.fetchall()


def _execute_schema(cursor, statements):
    for statement in statements:
        cursor.execute(statement)


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    if _is_postgres():
        _execute_schema(cursor, [
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS portfolios (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                startkapital DOUBLE PRECISION NOT NULL,
                basiswaehrung TEXT DEFAULT 'EUR',
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS portfolio_assets (
                id SERIAL PRIMARY KEY,
                portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                anteil INTEGER NOT NULL,
                regeln TEXT DEFAULT '{}',
                waehrung TEXT DEFAULT NULL,
                steuer_typ TEXT DEFAULT 'aktie'
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS simulation_results (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE SET NULL,
                name TEXT,
                result TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS basiswaehrung TEXT DEFAULT 'EUR'",
            "ALTER TABLE portfolio_assets ADD COLUMN IF NOT EXISTS waehrung TEXT DEFAULT NULL",
            "ALTER TABLE portfolio_assets ADD COLUMN IF NOT EXISTS steuer_typ TEXT DEFAULT 'aktie'",
            "CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON portfolios(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_portfolio_assets_portfolio_id ON portfolio_assets(portfolio_id)",
            "CREATE INDEX IF NOT EXISTS idx_simulation_results_user_id ON simulation_results(user_id)",
        ])
    else:
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
        _ensure_sqlite_column(cursor, "portfolios", "basiswaehrung", "TEXT DEFAULT 'EUR'")
        _ensure_sqlite_column(cursor, "portfolio_assets", "waehrung", "TEXT DEFAULT NULL")
        _ensure_sqlite_column(cursor, "portfolio_assets", "steuer_typ", "TEXT DEFAULT 'aktie'")

    conn.commit()
    conn.close()


def _ensure_sqlite_column(cursor, table, column, ddl):
    allowed = {
        ("portfolios", "basiswaehrung"),
        ("portfolio_assets", "waehrung"),
        ("portfolio_assets", "steuer_typ"),
    }
    if (table, column) not in allowed:
        raise ValueError("Nicht erlaubte Schema-Migration")
    columns = [row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def create_user(username: str, email: str, password_hash: str):
    conn = get_db()
    try:
        cursor = conn.cursor()
        sql = f"INSERT INTO users (username, email, password_hash) VALUES ({_placeholders(3)})"
        cursor.execute(sql, (username, email, password_hash))
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        if _is_unique_violation(exc):
            return False
        raise
    finally:
        conn.close()


def _is_unique_violation(exc):
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    return exc.__class__.__name__ in {"UniqueViolation", "IntegrityError"}


def get_user_by_username(username: str):
    conn = get_db()
    cursor = conn.cursor()
    row = _fetchone(cursor, f"SELECT * FROM users WHERE username = {_param()}", (username,))
    conn.close()
    return _row_to_dict(row)


def get_user_by_id(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    row = _fetchone(cursor, f"SELECT * FROM users WHERE id = {_param()}", (user_id,))
    conn.close()
    return _row_to_dict(row)


def save_portfolio(user_id: int, name: str, startkapital: float, assets: list, basiswaehrung: str = "EUR"):
    conn = get_db()
    try:
        cursor = conn.cursor()
        if _is_postgres():
            cursor.execute(
                f"INSERT INTO portfolios (user_id, name, startkapital, basiswaehrung) VALUES ({_placeholders(4)}) RETURNING id",
                (user_id, name, startkapital, basiswaehrung),
            )
            portfolio_id = cursor.fetchone()["id"]
        else:
            cursor.execute(
                f"INSERT INTO portfolios (user_id, name, startkapital, basiswaehrung) VALUES ({_placeholders(4)})",
                (user_id, name, startkapital, basiswaehrung),
            )
            portfolio_id = cursor.lastrowid

        for asset in assets:
            cursor.execute(
                f"""
                INSERT INTO portfolio_assets
                    (portfolio_id, symbol, name, anteil, regeln, waehrung, steuer_typ)
                VALUES ({_placeholders(7)})
                """,
                (
                    portfolio_id,
                    asset["symbol"],
                    asset["name"],
                    asset["anteil"],
                    json.dumps(asset.get("regeln", {})),
                    asset.get("waehrung"),
                    asset.get("steuer_typ", "aktie"),
                ),
            )

        conn.commit()
        return portfolio_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_portfolios(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    rows = _fetchall(
        cursor,
        f"SELECT * FROM portfolios WHERE user_id = {_param()} ORDER BY created_at DESC",
        (user_id,),
    )

    result = []
    for row in rows:
        portfolio = _row_to_dict(row)
        portfolio["basiswaehrung"] = portfolio.get("basiswaehrung") or "EUR"
        assets = _fetchall(
            cursor,
            f"SELECT * FROM portfolio_assets WHERE portfolio_id = {_param()}",
            (portfolio["id"],),
        )
        portfolio["assets"] = []
        for asset_row in assets:
            asset = _row_to_dict(asset_row)
            asset["regeln"] = json.loads(asset.get("regeln") or "{}")
            portfolio["assets"].append(asset)
        result.append(portfolio)

    conn.close()
    return result


def delete_portfolio(portfolio_id: int, user_id: int):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            DELETE FROM portfolio_assets
            WHERE portfolio_id IN (
                SELECT id FROM portfolios WHERE id = {_param()} AND user_id = {_param()}
            )
            """,
            (portfolio_id, user_id),
        )
        cursor.execute(
            f"DELETE FROM portfolios WHERE id = {_param()} AND user_id = {_param()}",
            (portfolio_id, user_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_result(user_id: int, name: str, result: dict, portfolio_id: int = None):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO simulation_results (user_id, portfolio_id, name, result) VALUES ({_placeholders(4)})",
            (user_id, portfolio_id, name, json.dumps(result)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_results(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    rows = _fetchall(
        cursor,
        f"SELECT id, name, created_at FROM simulation_results WHERE user_id = {_param()} ORDER BY created_at DESC LIMIT 20",
        (user_id,),
    )
    conn.close()
    return [_row_to_dict(row) for row in rows]
