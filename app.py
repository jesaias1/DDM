"""
Den Danske Metode — lokal AI-handels- og beslutningsmotor.

Kør:  python app.py
Åbn:  http://localhost:5000  (log ind)

Auto-trader handler kun for rigtige penge når DDM_LIVE=1 + nøgler er sat.
Ellers kører alt i tør-kørsel/simulering.
"""
import os
import time
import secrets
import hmac
import threading
from collections import defaultdict, deque
from datetime import timedelta

from flask import (Flask, jsonify, request, render_template, session,
                   redirect, url_for)

from engine import (bankroll, research, markets, sports, allocator,
                    autotrader, scheduler, auth, exchange, settings, notify,
                    polymarket)
from engine import database, terminal_api

app = Flask(__name__)
app.secret_key = auth.secret_key()
app.permanent_session_lifetime = timedelta(days=30)
STARTED_AT = int(time.time())
settings.apply_to_env()
database.initialize()
app.register_blueprint(terminal_api.api)
app.config.update(MAX_CONTENT_LENGTH=5*1024*1024, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Strict")
_login_attempts = defaultdict(deque)
_login_lock = threading.Lock()


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(32)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def check_origin_and_csrf():
    if request.host.split(":")[0] not in {"127.0.0.1", "localhost"}:
        return jsonify({"error": "Kun lokale hostnavne er tilladt"}), 400
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return None
    expected = session.get("csrf", "")
    supplied = request.headers.get("X-CSRF-Token", "") or request.form.get("csrf_token", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        return jsonify({"error": "Session eller CSRF-token er ugyldig. Genindlaes siden."}), 403


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(ValueError)
def invalid_input(error):
    return jsonify({"error": str(error)}), 400


@app.errorhandler(413)
def upload_too_large(error):
    return jsonify({"error": "Importen overstiger 5 MB"}), 413


@app.errorhandler(Exception)
def server_error(error):
    from werkzeug.exceptions import HTTPException
    if isinstance(error, HTTPException):
        return error
    # Don't log exception text: provider errors may embed API credentials.
    from engine.observability import emit
    emit("request_failed", endpoint=request.endpoint, error_type=type(error).__name__)
    return jsonify({"error": "Handlingen kunne ikke gennemfoeres. Fejltype: "+type(error).__name__}), 503


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
        with _login_lock:
            attempts = _login_attempts[request.remote_addr]
            now = time.monotonic()
            while attempts and attempts[0] < now-300:
                attempts.popleft()
            if len(attempts) >= 10:
                return render_template("login.html", error="For mange forsoeg. Vent fem minutter."), 429
            attempts.append(now)
        if auth.check(request.form.get("username", ""), request.form.get("password", "")):
            session.clear()
            session.permanent = True
            session["user"] = request.form.get("username")
            return redirect(url_for("index"))
        error = "Forkert brugernavn eller adgangskode."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- dashboard ----------

@app.route("/")
def index():
    return render_template("dashboard.html", user=session.get("user"))


@app.route("/crypto")
def crypto():
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
    return jsonify({"error": "Syntetisk backtest er pensioneret. Brug Strategilab med dokumenteret historik.",
                    "replacement": "/api/terminal/lab/evaluate", "edge_proven": False}), 410


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
    use_ai = state.get("use_ai", False)
    cfg = settings.load()
    opps = markets.find_opportunities()
    opps += sports.find_opportunities(api_key, use_ai=use_ai)
    if cfg.get("polymarket_enabled", settings.PUBLIC_DEFAULTS["polymarket_enabled"]):
        opps += polymarket.find_opportunities(use_ai=use_ai)
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
    scheduler.stop()
    return jsonify(autotrader.flatten())


@app.route("/api/live/clear-halt", methods=["POST"])
def api_live_clear_halt():
    return jsonify(autotrader.clear_halt())


@app.route("/api/live/reset", methods=["POST"])
def api_live_reset():
    data = request.get_json(silent=True) or {}
    from engine import quant
    autotrader.reset(quant.number(data.get("starting", autotrader.PAPER_START_EUR), 0, 1e7))
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


@app.route("/api/notify/test", methods=["POST"])
def api_notify_test():
    """Send en testbesked til mobilen (Telegram)."""
    return jsonify(notify.test_message())


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
        run_sports=bool(data.get("run_sports", False)),
    ))


@app.route("/api/scheduler/stop", methods=["POST"])
def api_sched_stop():
    return jsonify(scheduler.stop())


if __name__ == "__main__":
    print("Den Danske Metode koerer paa http://localhost:5000")
    print(f"  Login: bruger '{auth.USERNAME}'")
    print(f"  Auto-trader live-handel: {'JA' if exchange.live_enabled() else 'nej (toer-koersel)'}")
    from waitress import create_server
    from engine import process_lock
    with process_lock.acquire():
        # Bind successfully before a persisted live scheduler can send any orders.
        server = create_server(app, host="127.0.0.1", port=int(os.environ.get("DDM_PORT", "5000")), threads=8)
        scheduler.resume_if_enabled()
        try:
            server.run()
        finally:
            scheduler.stop()
            server.close()
