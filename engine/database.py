"""SQLite audit journal. Separate connections and transactions per operation."""
import json
import os
import sqlite3
from contextlib import contextmanager

PATH = os.environ.get("DDM_DB", os.path.join(os.path.dirname(__file__), "..", "data", "ddm.sqlite3"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
INSERT OR IGNORE INTO schema_version VALUES(2);
CREATE TABLE IF NOT EXISTS events(
 id TEXT NOT NULL, mode TEXT NOT NULL, sport TEXT NOT NULL, league TEXT NOT NULL,
 home TEXT NOT NULL, away TEXT NOT NULL, start REAL NOT NULL,
 PRIMARY KEY(id,mode));
CREATE TABLE IF NOT EXISTS snapshots(
 id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, mode TEXT NOT NULL,
 received_at REAL NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL,
 UNIQUE(mode,event_id,digest));
CREATE INDEX IF NOT EXISTS snapshots_time ON snapshots(mode,event_id,received_at);
CREATE TABLE IF NOT EXISTS decisions(
 id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
 event_id TEXT NOT NULL, mode TEXT NOT NULL, selection TEXT NOT NULL,
 bookmaker TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
 action TEXT NOT NULL, model_version TEXT NOT NULL, strategy_version TEXT NOT NULL,
 payload TEXT NOT NULL, UNIQUE(snapshot_id,selection,bookmaker,model_version,strategy_version));
CREATE INDEX IF NOT EXISTS decisions_mode ON decisions(mode,created_at);
CREATE TABLE IF NOT EXISTS accounts(mode TEXT PRIMARY KEY, deposits REAL NOT NULL DEFAULT 0, halted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY, mode TEXT NOT NULL, amount REAL NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bets(
 id INTEGER PRIMARY KEY, decision_id INTEGER NOT NULL REFERENCES decisions(id), mode TEXT NOT NULL,
 event_id TEXT NOT NULL, sport TEXT NOT NULL, league TEXT NOT NULL, selection TEXT NOT NULL,
 bookmaker TEXT NOT NULL, market TEXT NOT NULL, odds REAL NOT NULL, p REAL NOT NULL,
 market_p REAL NOT NULL, ev REAL NOT NULL, stake REAL NOT NULL, status TEXT NOT NULL,
 pnl REAL NOT NULL DEFAULT 0, placed_at REAL NOT NULL, settled_at REAL, closing_odds REAL,
 closing_at REAL, model_version TEXT NOT NULL, strategy_version TEXT NOT NULL,
 idempotency_key TEXT NOT NULL UNIQUE, UNIQUE(mode,event_id,market,selection));
CREATE INDEX IF NOT EXISTS bets_mode ON bets(mode,status,placed_at);
CREATE TABLE IF NOT EXISTS results(
 mode TEXT NOT NULL, event_id TEXT NOT NULL, winner TEXT, void INTEGER NOT NULL DEFAULT 0,
 received_at REAL NOT NULL, source TEXT NOT NULL, PRIMARY KEY(mode,event_id));
CREATE TABLE IF NOT EXISTS strategies(
 mode TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'EXPERIMENT', config TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts(
 id INTEGER PRIMARY KEY, mode TEXT NOT NULL, level TEXT NOT NULL, code TEXT NOT NULL,
 message TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 UNIQUE(mode,code));
CREATE TABLE IF NOT EXISTS provider_status(
 provider TEXT PRIMARY KEY, ok INTEGER NOT NULL, last_attempt REAL NOT NULL,
 last_success REAL, message TEXT NOT NULL, remaining INTEGER, latency_ms REAL);
CREATE TABLE IF NOT EXISTS provider_usage(day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS historical_matches(
 id TEXT PRIMARY KEY, league TEXT NOT NULL, home TEXT NOT NULL, away TEXT NOT NULL,
 start REAL NOT NULL, available_at REAL NOT NULL, home_goals INTEGER NOT NULL,
 away_goals INTEGER NOT NULL, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evaluations(
 id INTEGER PRIMARY KEY, created_at REAL NOT NULL, dataset_hash TEXT NOT NULL,
 model_version TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS historical_odds(
 digest TEXT PRIMARY KEY, event_id TEXT NOT NULL, received_at REAL NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS historical_odds_time ON historical_odds(event_id,received_at);
CREATE TRIGGER IF NOT EXISTS decisions_immutable BEFORE UPDATE ON decisions BEGIN SELECT RAISE(ABORT,'decisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT,'decisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS snapshots_immutable BEFORE UPDATE ON snapshots BEGIN SELECT RAISE(ABORT,'snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS snapshots_no_delete BEFORE DELETE ON snapshots BEGIN SELECT RAISE(ABORT,'snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS results_immutable BEFORE UPDATE ON results BEGIN SELECT RAISE(ABORT,'results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON results BEGIN SELECT RAISE(ABORT,'results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS bets_no_delete BEFORE DELETE ON bets BEGIN SELECT RAISE(ABORT,'bet history cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS bets_entry_immutable BEFORE UPDATE OF
 decision_id,mode,event_id,sport,league,selection,bookmaker,market,odds,p,market_p,ev,stake,placed_at,model_version,strategy_version,idempotency_key
 ON bets BEGIN SELECT RAISE(ABORT,'original bet entry is immutable'); END;
CREATE TRIGGER IF NOT EXISTS deposits_immutable BEFORE UPDATE ON deposits BEGIN SELECT RAISE(ABORT,'deposits are immutable'); END;
CREATE TRIGGER IF NOT EXISTS deposits_no_delete BEFORE DELETE ON deposits BEGIN SELECT RAISE(ABORT,'deposits are immutable'); END;
CREATE TRIGGER IF NOT EXISTS historical_matches_immutable BEFORE UPDATE ON historical_matches BEGIN SELECT RAISE(ABORT,'historical results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS historical_matches_no_delete BEFORE DELETE ON historical_matches BEGIN SELECT RAISE(ABORT,'historical results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS historical_odds_immutable BEFORE UPDATE ON historical_odds BEGIN SELECT RAISE(ABORT,'historical odds are immutable'); END;
CREATE TRIGGER IF NOT EXISTS historical_odds_no_delete BEFORE DELETE ON historical_odds BEGIN SELECT RAISE(ABORT,'historical odds are immutable'); END;
"""


@contextmanager
def connection(write=False):
    os.makedirs(os.path.dirname(os.path.abspath(PATH)), exist_ok=True)
    db = sqlite3.connect(PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.create_function("ddm_casefold", 1, lambda value: str(value or "").casefold(), deterministic=True)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    try:
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    os.makedirs(os.path.dirname(os.path.abspath(PATH)), exist_ok=True)
    db = sqlite3.connect(PATH, timeout=10)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        for mode in ("DEMO", "PAPER", "REAL"):
            db.execute("INSERT OR IGNORE INTO accounts(mode) VALUES(?)", (mode,))
            db.execute("INSERT OR IGNORE INTO strategies(mode,state,config) VALUES(?,?,?)",
                       (mode, "PAPER" if mode == "DEMO" else "EXPERIMENT", dumps({})))
        db.commit()
    finally:
        db.close()


def dumps(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def alert(db, mode, code, message, level="warning", now=None):
    import time
    now = time.time() if now is None else now
    db.execute("""INSERT INTO alerts(mode,level,code,message,created_at,updated_at) VALUES(?,?,?,?,?,?)
                  ON CONFLICT(mode,code) DO UPDATE SET message=excluded.message,level=excluded.level,updated_at=excluded.updated_at""",
               (mode, level, code, message, now, now))
