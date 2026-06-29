"""
Den Danske Metode — lokal AI-handels- og beslutningsmotor.

Kør:  python app.py
Åbn:  http://localhost:5000  (log ind)

Auto-trader handler kun for rigtige penge når DDM_LIVE=1 + nøgler er sat.
Ellers kører alt i tør-kørsel/simulering.
"""
import os
import time
from datetime import timedelta

from flask import (Flask, jsonify, request, render_template, session,
                   redirect, url_for)

from engine import (bankroll, backtest, research, markets, sports, allocator,
                    autotrader, scheduler, auth, exchange, settings)

app = Flask(__name__)
app.secret_key = auth.secret_key()
app.permanent_session_lifetime = timedelta(days=30)
STARTED_AT = int(time.time())
settings.apply_to_env()


# ---------- login ----------

@app.before_request
def require_login():
    if request.endpoint in ("login", "static") or session.get("user"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "ikke logget ind"}), 401
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if auth.check(request.form.get("username", ""), request.form.get("password", "")):
            session.permanent = True
            session["user"] = request.form.get("username")
            return redirect(url_for("index"))
        error = "Forkert brugernavn eller adgangskode."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- dashboard ----------

@app.route("/")
def index():
    return render_template("dashboard.html", user=session.get("user"))


@app.route("/api/health")
def api_health():
    now = int(time.time())
    return jsonify({
        "ok": True,
        "server_time": now,
        "uptime_seconds": now - STARTED_AT,
        "live": exchange.live_enabled(),
        "scheduler": scheduler.status(),
    })


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        status = settings.save(data)
    else:
        status = settings.status()
    status["ai_usage"] = research.usage_status()
    return jsonify(status)


# ---------- simulator ----------

@app.route("/api/state")
def api_state():
    state = bankroll.load_state() or bankroll.reset()
    return jsonify({
        "starting": state["starting_bankroll"],
        "cash": round(state["cash"], 2),
        "equity": round(bankroll.equity(state), 2),
        "naive": round(state["naive_baseline"], 2),
        "positions": state["positions"],
        "history": list(reversed(state["history"][-30:])),
        "equity_curve": state["equity_curve"],
        "naive_curve": state["naive_curve"],
        "use_ai": state.get("use_ai", False),
    })


@app.route("/api/cycle", methods=["POST"])
def api_cycle():
    return jsonify(bankroll.run_cycle())


@app.route("/api/diagnostics")
def api_diagnostics():
    return jsonify(bankroll.diagnostics())


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    data = request.get_json(silent=True) or {}
    starting = max(1.0, float(data.get("starting", 100)))
    return jsonify(backtest.run(
        days=int(data.get("days", 200)),
        starting=starting,
    ))


@app.route("/api/ai", methods=["POST"])
def api_ai():
    data = request.get_json(silent=True) or {}
    state = bankroll.load_state() or bankroll.reset()
    state["use_ai"] = bool(data.get("use_ai", False))
    bankroll.save_state(state)
    return jsonify({"use_ai": state["use_ai"], "ai_available": research.available()})


@app.route("/api/signals", methods=["POST"])
def api_signals():
    """Konkrete anbefalinger (hvad + hvor meget) for en saldo du selv indtaster."""
    data = request.get_json(silent=True) or {}
    balance = float(data.get("balance", 0))
    state = bankroll.load_state() or bankroll.reset()
    api_key = os.environ.get("ODDS_API_KEY")
    opps = markets.find_opportunities()
    opps += sports.find_opportunities(api_key, use_ai=state.get("use_ai", False))
    actions = allocator.allocate(balance, opps)
    return jsonify({
        "balance": balance,
        "actions": [{
            "type": a["type"], "name": a["name"], "stake": a["stake_dkk"],
            "andel_pct": round(a["kelly_fraction"] * 100, 1),
            "sport": a.get("sport", ""),
            "odds": a.get("odds"),
            "win_pct": round(a["p_ours"] * 100, 1) if a.get("p_ours") is not None else None,
            "value_pct": round(a["value"] * 100, 1) if a.get("value") is not None else None,
            "reason": a.get("reason", ""),
        } for a in actions],
    })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    data = request.get_json(silent=True) or {}
    bankroll.reset(max(1.0, float(data.get("starting", 100))), bool(data.get("use_ai", False)))
    return jsonify({"ok": True})


# ---------- auto-trader ----------

@app.route("/api/live/status")
def api_live_status():
    return jsonify(autotrader.status())


@app.route("/api/live/preflight")
def api_live_preflight():
    return jsonify(exchange.preflight())


@app.route("/api/live/readiness")
def api_live_readiness():
    return jsonify(autotrader.readiness())


@app.route("/api/live/cycle", methods=["POST"])
def api_live_cycle():
    return jsonify(autotrader.run_cycle())


@app.route("/api/live/flatten", methods=["POST"])
def api_live_flatten():
    return jsonify(autotrader.flatten())


@app.route("/api/live/clear-halt", methods=["POST"])
def api_live_clear_halt():
    return jsonify(autotrader.clear_halt())


@app.route("/api/live/reset", methods=["POST"])
def api_live_reset():
    data = request.get_json(silent=True) or {}
    autotrader.reset(max(1.0, float(data.get("starting", autotrader.PAPER_START_EUR))))
    return jsonify({"ok": True})


@app.route("/api/deposit", methods=["POST"])
def api_deposit():
    """Hent din rigtige indbetalingsadresse på børsen (kræver live + funding-nøgle)."""
    data = request.get_json(silent=True) or {}
    currency = (data.get("currency") or "BTC").upper()
    if not exchange.live_enabled():
        return jsonify({
            "live": False,
            "message": ("Indbetalingsadresse kræver live-tilstand med nøgler. Du kan "
                        "altid finde adressen direkte på din børs: Funding → Indbetal "
                        "→ vælg coin → kopiér adressen."),
            "exchange": exchange.EXCHANGE_ID,
        })
    res = exchange.deposit_address(currency)
    res["live"] = True
    res["exchange"] = exchange.EXCHANGE_ID
    return jsonify(res)


# ---------- scheduler ----------

@app.route("/api/scheduler/status")
def api_sched_status():
    return jsonify(scheduler.status())


@app.route("/api/scheduler/start", methods=["POST"])
def api_sched_start():
    data = request.get_json(silent=True) or {}
    return jsonify(scheduler.start(
        interval=int(data.get("interval", 60)),
        run_live=bool(data.get("run_live", True)),
        run_sim=bool(data.get("run_sim", False)),
    ))


@app.route("/api/scheduler/stop", methods=["POST"])
def api_sched_stop():
    return jsonify(scheduler.stop())


if __name__ == "__main__":
    print("Den Danske Metode koerer paa http://localhost:5000")
    print(f"  Login: bruger '{auth.USERNAME}'")
    print(f"  Auto-trader live-handel: {'JA' if exchange.live_enabled() else 'nej (toer-koersel)'}")
    scheduler.resume_if_enabled()
    app.run(host="127.0.0.1", port=5000, debug=False)
