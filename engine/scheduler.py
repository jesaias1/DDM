"""
Baggrunds-scheduler — det der gør det HELE autonomt.

Uden dette kører motoren kun når du klikker, eller mens browserfanen er åben.
Scheduleren kører en baggrunds-tråd på serveren, der selv udfører cyklusser på et
fast interval — også når browseren er lukket — og genoptager efter en genstart.

Den kan køre to motorer:
  • auto-trader (krypto, rigtig/tør-kørsel)   — `run_live`
  • simulator (paper sport+krypto, baseline)   — `run_sim`

Konfigurationen gemmes i data/scheduler.json, så "kører"-tilstanden overlever en
genstart af serveren (ægte "sæt op og glem").
"""
import os
import time
import threading

from . import autotrader, bankroll, store

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "scheduler.json")
MIN_INTERVAL = 15      # sekunder — undgå at hamre børs-API'et
DEFAULT_INTERVAL = 60

_lock = threading.RLock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_runtime = {"last_run": None, "last_log": [], "error": None, "started_at": None}


def _load_cfg() -> dict:
    cfg = store.load(CONFIG_PATH) or {}
    return {
        "running": bool(cfg.get("running", False)),
        "interval": max(MIN_INTERVAL, int(cfg.get("interval", DEFAULT_INTERVAL))),
        "run_live": bool(cfg.get("run_live", True)),
        "run_sim": bool(cfg.get("run_sim", False)),
    }


def _save_cfg(cfg: dict) -> None:
    store.save(CONFIG_PATH, cfg)


def _one_round(cfg: dict) -> list[str]:
    """Kør de valgte motorer én gang. Fejl i én motor stopper ikke den anden."""
    log = []
    if cfg["run_live"]:
        try:
            r = autotrader.run_cycle()
            log.append(("[LIVE] " if r["live"] else "[TØR] ") + "; ".join(r["log"]))
        except Exception as e:
            log.append(f"auto-trader fejlede: {e}")
    if cfg["run_sim"]:
        try:
            r = bankroll.run_cycle()
            log.append("[SIM] " + "; ".join(r["log"]))
        except Exception as e:
            log.append(f"simulator fejlede: {e}")
    return log


def _loop() -> None:
    while not _stop.is_set():
        cfg = _load_cfg()
        try:
            log = _one_round(cfg)
            with _lock:
                _runtime["last_run"] = int(time.time())
                _runtime["last_log"] = log
                _runtime["error"] = None
        except Exception as e:  # backstop — bør aldrig ske, men holder tråden i live
            with _lock:
                _runtime["error"] = str(e)
        # vent intervallet, men reagér hurtigt på stop
        _stop.wait(_load_cfg()["interval"])


def start(interval: int = DEFAULT_INTERVAL, run_live: bool = True,
          run_sim: bool = False) -> dict:
    """Start (eller genkonfigurér) den autonome loop."""
    global _thread
    with _lock:
        cfg = {"running": True, "interval": max(MIN_INTERVAL, int(interval)),
               "run_live": bool(run_live), "run_sim": bool(run_sim)}
        _save_cfg(cfg)
        _runtime["started_at"] = int(time.time())
        if _thread is None or not _thread.is_alive():
            _stop.clear()
            _thread = threading.Thread(target=_loop, daemon=True, name="smartstake-scheduler")
            _thread.start()
    return status()


def stop() -> dict:
    """Stop loopet (positioner røres ikke — brug kill switch for at sælge)."""
    global _thread
    with _lock:
        cfg = _load_cfg()
        cfg["running"] = False
        _save_cfg(cfg)
        _stop.set()
        _thread = None
    return status()


def status() -> dict:
    cfg = _load_cfg()
    with _lock:
        alive = _thread is not None and _thread.is_alive()
        last_run, last_log = _runtime["last_run"], list(_runtime["last_log"])
        error = _runtime["error"]
    next_run = (last_run + cfg["interval"]) if (alive and last_run) else None
    return {
        "running": cfg["running"] and alive,
        "interval": cfg["interval"],
        "run_live": cfg["run_live"],
        "run_sim": cfg["run_sim"],
        "last_run": last_run,
        "next_run": next_run,
        "last_log": last_log,
        "error": error,
    }


def resume_if_enabled() -> None:
    """Kaldes ved server-opstart: genoptag loopet hvis det var slået til."""
    cfg = _load_cfg()
    if cfg["running"]:
        start(cfg["interval"], cfg["run_live"], cfg["run_sim"])
