"""
Auto-trader: den rigtige "indbetal → AI styrer → hæv ud"-loop på krypto.

Kører momentum + Kelly-motoren mod en RIGTIG børs. To tilstande, valgt automatisk:

  TØR-KØRSEL (standard): ægte live-priser, men ingen ordrer sendes. En paper-saldo
      bruges, så du kan se loopet arbejde uden risiko.
  LIVE: kun hvis DDM_LIVE=1 (eller legacy SMARTSTAKE_LIVE=1) OG handels-nøgler er sat. Da sendes rigtige
      markedsordrer og saldoen aflæses fra din konto.

Hver cyklus:
  1. Styr åbne positioner: hård stop-loss eller trailing stop efter ny top.
  2. Find momentum-signaler fra børsens egne candles.
  3. Allokér med Kelly (kontant-buffer + eksponeringsloft beskytter puljen).
  4. Køb nye positioner (rigtige ordrer i live, simuleret i tør-kørsel).

Kill switch: flatten() sælger/lukker alt og stopper.
"""
import os
import time

from . import exchange, allocator, notify, store, strategy, settings

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "live_state.json")
PAPER_START_EUR = float(os.environ.get("DDM_PAPER_START", os.environ.get("SMARTSTAKE_PAPER_START", 0.0)))
DAILY_LOSS_LIMIT = float(os.environ.get("DDM_DAILY_LOSS_LIMIT", "-0.05"))
TOTAL_LOSS_LIMIT = float(os.environ.get("DDM_TOTAL_LOSS_LIMIT", "-0.10"))
AUTO_FLATTEN_ON_HALT = os.environ.get("DDM_AUTO_FLATTEN_ON_HALT", "1") == "1"


def _load() -> dict | None:
    return store.load(STATE_PATH)


def _save(state: dict) -> None:
    store.save(STATE_PATH, state)


def _default(starting: float = PAPER_START_EUR) -> dict:
    return {"paper_cash": starting, "paper_start": starting, "positions": [],
            "history": [], "equity_curve": [], "cooldowns": {}, "halted": False,
            "halt_reason": None, "day": None, "day_start_equity": starting,
            "risk_start_equity": starting,
            "trade_day": None, "daily_buy_count": 0, "canary_done": False,
            "created": int(time.time())}


def reset(starting: float = PAPER_START_EUR) -> dict:
    s = _default(starting)
    _save(s)
    return s


def _available_cash(state: dict) -> float:
    """Fri kontant: rigtig saldo i live, ellers paper-saldoen."""
    if exchange.live_enabled():
        try:
            return exchange.get_quote_balance()
        except Exception as e:
            print(f"[autotrader] kunne ikke hente saldo, falder til tør-kørsel: {e}")
    return state.get("paper_cash", PAPER_START_EUR)


def _positions_value(state: dict) -> float:
    total = 0.0
    for p in state["positions"]:
        total += p["amount"] * exchange.get_price(p["symbol"]) * (1 - strategy.FEE)
    return total


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _test_limits() -> dict:
    cfg = settings.load()
    defaults = settings.PUBLIC_DEFAULTS
    return {
        "max_live_stake": max(0.0, float(cfg.get("max_live_stake", defaults["max_live_stake"]))),
        "max_daily_buys": max(0, int(cfg.get("max_daily_buys", defaults["max_daily_buys"]))),
        "max_open_positions": max(0, int(cfg.get("max_open_positions", defaults["max_open_positions"]))),
        "canary_mode": bool(cfg.get("canary_mode", defaults["canary_mode"])),
        "canary_stake": max(0.0, float(cfg.get("canary_stake", defaults["canary_stake"]))),
    }


def _ensure_trade_window(state: dict) -> None:
    today = _today()
    if state.get("trade_day") != today:
        state["trade_day"] = today
        state["daily_buy_count"] = 0
        state["canary_done"] = False


def _ensure_risk_window(state: dict, equity: float) -> None:
    if not state.get("risk_start_equity"):
        state["risk_start_equity"] = equity
    today = _today()
    if state.get("day") != today:
        state["day"] = today
        state["day_start_equity"] = equity
        state["halted"] = False
        state["halt_reason"] = None


def _risk_status(state: dict, equity: float) -> dict:
    _ensure_risk_window(state, equity)
    day_start = float(state.get("day_start_equity") or equity or 1.0)
    total_start = float(state.get("risk_start_equity") or state.get("paper_start") or day_start or 1.0)
    daily_return = (equity / day_start - 1) if day_start > 0 else 0.0
    total_return = (equity / total_start - 1) if total_start > 0 else 0.0
    return {
        "halted": bool(state.get("halted", False)),
        "halt_reason": state.get("halt_reason"),
        "day": state.get("day"),
        "day_start_equity": round(day_start, 2),
        "daily_return_pct": round(daily_return * 100, 2),
        "total_return_pct": round(total_return * 100, 2),
        "daily_loss_limit_pct": round(DAILY_LOSS_LIMIT * 100, 2),
        "total_loss_limit_pct": round(TOTAL_LOSS_LIMIT * 100, 2),
        "auto_flatten_on_halt": AUTO_FLATTEN_ON_HALT,
    }


def _apply_risk_guard(state: dict, equity: float) -> str | None:
    risk = _risk_status(state, equity)
    if risk["halted"]:
        return risk["halt_reason"] or "handel stoppet af risikobremsen"
    if risk["daily_return_pct"] <= DAILY_LOSS_LIMIT * 100:
        state["halted"] = True
        state["halt_reason"] = f"dagligt tabsloft ramt ({risk['daily_return_pct']:.2f}%)"
        return state["halt_reason"]
    if risk["total_return_pct"] <= TOTAL_LOSS_LIMIT * 100:
        state["halted"] = True
        state["halt_reason"] = f"samlet tabsloft ramt ({risk['total_return_pct']:.2f}%)"
        return state["halt_reason"]
    return None


def clear_halt() -> dict:
    """Manuel genåbning efter risikobremsen har stoppet handel."""
    with store.lock_for(STATE_PATH):
        state = _load() or reset()
        equity = _available_cash(state) + _positions_value(state)
        state["halted"] = False
        state["halt_reason"] = None
        state["day"] = _today()
        state["day_start_equity"] = equity
        state["risk_start_equity"] = equity
        _save(state)
        return {"ok": True, "equity": round(equity, 2)}


def readiness() -> dict:
    """Samlet vurdering før lille live-test."""
    state = _load() or reset()
    cash = _available_cash(state)
    eq = cash + _positions_value(state)
    risk = _risk_status(state, eq)
    limits = _test_limits()
    preflight = exchange.preflight()
    checks = [
        {"name": "Preflight", "ok": bool(preflight.get("ok")), "message": "Coinbase/API er klar" if preflight.get("ok") else "Kør preflight og ret røde punkter"},
        {"name": "Risikobremse", "ok": not risk["halted"], "message": "ikke stoppet" if not risk["halted"] else risk["halt_reason"]},
        {"name": "Dagligt tabsloft", "ok": risk["daily_loss_limit_pct"] >= -5.0, "message": f"{risk['daily_loss_limit_pct']}%"},
        {"name": "Samlet tabsloft", "ok": risk["total_loss_limit_pct"] >= -10.0, "message": f"{risk['total_loss_limit_pct']}%"},
        {"name": "Max handel", "ok": 0 < limits["max_live_stake"] <= 25, "message": f"{limits['max_live_stake']:.2f} {exchange.QUOTE} pr. ordre"},
        {"name": "Canary", "ok": limits["canary_mode"] and 0 < limits["canary_stake"] <= limits["max_live_stake"], "message": f"første køb maks {limits['canary_stake']:.2f} {exchange.QUOTE}" if limits["canary_mode"] else "canary er slået fra"},
        {"name": "Max køb pr. dag", "ok": 0 < limits["max_daily_buys"] <= 2, "message": str(limits["max_daily_buys"])},
        {"name": "Max åbne positioner", "ok": 0 < limits["max_open_positions"] <= 2, "message": str(limits["max_open_positions"])},
    ]
    ok = all(c["ok"] for c in checks)
    return {
        "ok": ok,
        "checks": checks,
        "preflight": preflight,
        "risk": risk,
        "test_limits": limits,
        "recommendation": (
            "Klar til en lille live-test med beløb du kan tåle at tabe."
            if ok else
            "Ikke klar endnu. Ret de røde punkter før live-test."
        ),
    }


def status() -> dict:
    state = _load() or reset()
    _ensure_trade_window(state)
    cash = _available_cash(state)
    eq = cash + _positions_value(state)
    risk = _risk_status(state, eq)
    _save(state)
    return {
        "live": exchange.live_enabled(),
        "live_requested": exchange.live_requested(),
        "live_armed": exchange.live_armed(),
        "exchange": exchange.EXCHANGE_ID,
        "quote": exchange.QUOTE,
        "cash": round(cash, 2),
        "equity": round(eq, 2),
        "risk": risk,
        "test_limits": {
            **_test_limits(),
            "daily_buy_count": int(state.get("daily_buy_count", 0)),
            "canary_done": bool(state.get("canary_done", False)),
        },
        "positions": [{
            "symbol": p["symbol"], "amount": p["amount"],
            "entry": p["entry"], "cost": p["cost"],
            "now": round(exchange.get_price(p["symbol"]), 6),
            "peak": round(p.get("peak", p["entry"]), 6),
        } for p in state["positions"]],
        "history": list(reversed(state["history"][-20:])),
        "strategy": {
            "stop_loss_pct": round(strategy.STOP_LOSS * 100, 1),
            "trail_pct": round(strategy.TRAIL_PCT * 100, 1),
            "arm_profit_pct": round(strategy.ARM_PROFIT * 100, 1),
            "trend_len": strategy.TREND_LEN,
            "fee_pct": round(strategy.FEE * 100, 2),
            "cooldown_hours": round(strategy.COOLDOWN_SECONDS / 3600, 1),
        },
    }


def _manage(state: dict, live: bool) -> list[str]:
    log = []
    keep = []
    state.setdefault("cooldowns", {})
    for p in state["positions"]:
        price = exchange.get_price(p["symbol"])
        if price <= 0:
            keep.append(p)
            continue
        p["peak"] = max(p.get("peak", p["entry"]), price)
        exit_now, reason = strategy.should_exit(p["entry"], p["peak"], price)
        if exit_now:
            if live:
                res = exchange.market_sell(p["symbol"], p["amount"])
                proceeds = res["proceeds"]
            else:
                proceeds = p["amount"] * price * (1 - strategy.FEE)
                state["paper_cash"] += proceeds
            pnl = proceeds - p["cost"]
            state["cooldowns"][p["symbol"]] = int(time.time()) + strategy.COOLDOWN_SECONDS
            state["history"].append({
                "symbol": p["symbol"], "cost": round(p["cost"], 2),
                "pnl": round(pnl, 2), "reason": reason,
                "live": live, "ts": int(time.time()),
            })
            log.append(f"Solgte {p['symbol']}: {reason}, {pnl:+.2f} {exchange.QUOTE}")
        else:
            keep.append(p)
    state["positions"] = keep
    return log


def _alert_if_action(log: list[str], live: bool) -> None:
    """Send mobil-besked ved køb/salg/risikobremse. Må aldrig stoppe handel."""
    try:
        interesting = [l for l in log if l.startswith(("Købte", "Solgte", "Lukkede", "Risikobremse"))]
        if interesting:
            notify.trade_alert(interesting, live)
    except Exception as e:
        print(f"[autotrader] besked fejlede: {e}")


def run_cycle() -> dict:
    with store.lock_for(STATE_PATH):
        result = _run_cycle_locked()
    _alert_if_action(result.get("log", []), result.get("live", False))
    return result


def _run_cycle_locked() -> dict:
    state = _load() or reset()
    live = exchange.live_enabled()
    log = []
    state.setdefault("cooldowns", {})
    _ensure_trade_window(state)

    # 1) styr åbne positioner
    log += _manage(state, live)

    # 2) signaler + 3) allokering på nuværende pulje
    cash = _available_cash(state)
    equity = cash + _positions_value(state)
    halt_reason = _apply_risk_guard(state, equity)
    if halt_reason:
        if AUTO_FLATTEN_ON_HALT and state["positions"]:
            log.append(f"Risikobremse: {halt_reason}. Lukker åbne positioner.")
            _save(state)
            flat = _flatten_locked()
            state = _load() or reset()
            return {
                "live": live,
                "log": log + flat["log"],
                "equity": round((_available_cash(state) + _positions_value(state)), 2),
                "halted": True,
            }
        state["equity_curve"].append({"ts": int(time.time()), "equity": round(equity, 2)})
        state["equity_curve"] = state["equity_curve"][-500:]
        _save(state)
        return {
            "live": live,
            "log": log or [f"Risikobremse aktiv: {halt_reason}. Ingen nye køb."],
            "equity": round(equity, 2),
            "halted": True,
        }

    held = {p["symbol"] for p in state["positions"]}
    now = int(time.time())
    state["cooldowns"] = {s: until for s, until in state.get("cooldowns", {}).items() if until > now}
    cooling = set(state["cooldowns"])
    opps = [o for o in exchange.fetch_signals() if o["id"] not in held and o["id"] not in cooling]
    actions = allocator.allocate(equity, opps)
    limits = _test_limits()

    # 4) køb
    for a in actions:
        if len(state["positions"]) >= limits["max_open_positions"]:
            log.append(f"Springer køb over: maks {limits['max_open_positions']} åbne positioner i testprofil.")
            break
        if int(state.get("daily_buy_count", 0)) >= limits["max_daily_buys"]:
            log.append(f"Springer køb over: maks {limits['max_daily_buys']} køb pr. dag i testprofil.")
            break
        stake = a["stake_dkk"]  # beløb i kvotevaluta (feltnavn genbrugt)
        if live:
            if limits["max_live_stake"] > 0:
                stake = min(stake, limits["max_live_stake"])
            if limits["canary_mode"] and not state.get("canary_done", False) and limits["canary_stake"] > 0:
                stake = min(stake, limits["canary_stake"])
        if stake > cash:
            continue
        if stake <= 0:
            continue
        try:
            if live:
                fill = exchange.market_buy(a["id"], stake)
                amount, price = fill["amount"], fill["price"]
            else:
                price = a["price"]
                amount = stake * (1 - strategy.FEE) / price if price else 0
                state["paper_cash"] -= stake
            state["positions"].append({
                "symbol": a["id"], "amount": amount, "entry": price,
                "peak": price, "cost": stake, "live": live, "ts": int(time.time()),
            })
            state["daily_buy_count"] = int(state.get("daily_buy_count", 0)) + 1
            if live and limits["canary_mode"]:
                state["canary_done"] = True
            cash -= stake
            log.append(f"Købte {a['id']}: {stake:.2f} {exchange.QUOTE} @ {price:.4f}")
        except Exception as e:
            log.append(f"Køb af {a['id']} fejlede: {e}")

    eq = _available_cash(state) + _positions_value(state)
    state["equity_curve"].append({"ts": int(time.time()), "equity": round(eq, 2)})
    state["equity_curve"] = state["equity_curve"][-500:]
    _save(state)
    return {
        "live": live,
        "log": log or ["Ingen handlinger (intet momentum-signal lige nu)."],
        "equity": round(eq, 2),
    }


def flatten() -> dict:
    """KILL SWITCH: sælg/luk alle positioner og stop."""
    with store.lock_for(STATE_PATH):
        return _flatten_locked()


def _flatten_locked() -> dict:
    state = _load() or reset()
    live = exchange.live_enabled()
    log = []
    for p in state["positions"]:
        price = exchange.get_price(p["symbol"])
        if live:
            try:
                res = exchange.market_sell(p["symbol"], p["amount"])
                proceeds = res["proceeds"]
            except Exception as e:
                log.append(f"Kunne ikke sælge {p['symbol']}: {e}")
                continue
        else:
            proceeds = p["amount"] * price * (1 - strategy.FEE)
            state["paper_cash"] += proceeds
        state["history"].append({
            "symbol": p["symbol"], "cost": round(p["cost"], 2),
            "pnl": round(proceeds - p["cost"], 2), "reason": "kill switch",
            "live": live, "ts": int(time.time()),
        })
        log.append(f"Lukkede {p['symbol']}: {proceeds - p['cost']:+.2f} {exchange.QUOTE}")
    state["positions"] = []
    _save(state)
    return {"log": log or ["Ingen åbne positioner at lukke."]}
