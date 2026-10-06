"""Stateless, authenticated, read-only demo. No DB, secrets storage or exchange SDK."""
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from engine import feeds, intelligence, quant, risk, settings

ROOT = Path(__file__).resolve().parents[1]


def demonstration():
    now = time.time()
    events = feeds.demo_events(now)
    account = {"equity": 0, "cash": 0, "exposure": 0, "deposits": 0, "halted": False}
    strategy = {"state": "EXPERIMENT", "config": {}}
    event_map = {e["id"]: e for e in events}
    opportunities = []
    for event in events:
        opportunities.extend(intelligence.evaluate(event, account, [], event_map, strategy, [], now))
    for i, item in enumerate(opportunities, 1):
        item["id"] = i
    opportunities.sort(key=lambda item: -(item["robust_ev"] or -1))
    calibration = {**quant.calibration([]), "events": 0, "model_version": "leave-book-out-power-1"}
    return {"mode": "DEMO", "deployment": "READ_ONLY_DEMO", "account": account,
            "metrics": quant.performance([], 0), "opportunities": opportunities,
            "opportunity_count": len(opportunities), "bets": [], "open_bets": [], "open_count": 0,
            "total_bets": 0, "versions": [], "strategy": strategy, "model_health": "AFVENTER DATA",
            "model_calibration": calibration, "model_baseline": quant.calibration([]), "drift": None,
            "alerts": [], "providers": [], "server_time": now, "limits": risk.Limits().as_dict(),
            "edge_status": "INGEN DOKUMENTERET EDGE", "execution": "Online-demo; ingen ordreudfoerelse",
            "brain": {"markets": len(events), "bet": 0,
                      "watch": sum(o["action"] == "WATCH" for o in opportunities),
                      "pass": sum(o["action"] == "PASS" for o in opportunities),
                      "stale": sum(o["expires_at"] <= now for o in opportunities),
                      "largest_ev": max((o["ev"] or 0 for o in opportunities), default=None)},
            "scheduler": {"running": False, "run_live": False, "run_sports": False, "run_sim": False,
                          "interval": 900, "last_run": None, "last_log": [], "error": None}}


def create_app():
    password = os.environ.get("DDM_CLOUD_PASS", "").strip()
    session_secret = os.environ.get("DDM_CLOUD_SESSION_SECRET", "").strip()
    username = os.environ.get("DDM_CLOUD_USER", "jesaias").strip()
    if len(password) < 20 or len(session_secret) < 32:
        raise RuntimeError("Separate strong cloud credentials are required; no default login")
    password_hash = generate_password_hash(password)
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"), static_url_path="/static")
    app.config.update(SECRET_KEY=session_secret, SESSION_COOKIE_SECURE=True,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict", MAX_CONTENT_LENGTH=16384)
    attempts, lock = defaultdict(deque), threading.Lock()

    def csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(32)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf

    @app.before_request
    def authenticate():
        if request.method not in {"GET", "HEAD", "POST", "OPTIONS"}:
            return jsonify(error="Online-demo er skrivebeskyttet"), 403
        if request.method == "POST":
            expected = session.get("csrf", "")
            supplied = request.headers.get("X-CSRF-Token", "") or request.form.get("csrf_token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                return jsonify(error="Ugyldigt CSRF-token"), 403
        if request.endpoint not in {"login", "static"} and not session.get("user"):
            if request.path.startswith("/api/"):
                return jsonify(error="Ikke logget ind"), 401
            return redirect("/login")
        if request.method == "POST" and request.path not in {"/login", "/logout", "/api/terminal/scan"}:
            return jsonify(error="Online-demo er skrivebeskyttet. Bot og journal koerer kun lokalt."), 403

    @app.after_request
    def headers(response):
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
                                 "Strict-Transport-Security": "max-age=31536000"})
        return response

    @app.errorhandler(Exception)
    def failed(error):
        if isinstance(error, HTTPException):
            return error
        return jsonify(error="Online-demo kunne ikke indlaeses"), 503

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            # Instance-local throttling supplements a high-entropy credential; not a distributed limiter.
            with lock:
                ip, now = request.remote_addr, time.monotonic()
                while attempts[ip] and attempts[ip][0] < now-300:
                    attempts[ip].popleft()
                if len(attempts[ip]) >= 10:
                    return render_template("login.html", error="Vent fem minutter.", cloud_readonly=True), 429
                attempts[ip].append(now)
            valid_password = check_password_hash(password_hash, request.form.get("password", ""))
            if hmac.compare_digest(request.form.get("username", ""), username) and valid_password:
                session.clear()
                session["user"] = username
                return redirect("/")
            error = "Forkert brugernavn eller adgangskode."
        return render_template("login.html", error=error, cloud_readonly=True)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect("/login")

    @app.get("/")
    def index():
        return render_template("dashboard.html", user=session["user"], cloud_readonly=True)

    @app.get("/api/terminal/overview")
    def overview():
        if request.args.get("mode", "DEMO") != "DEMO":
            return jsonify(error="Online-versionen viser kun DEMO; ingen lokal synkronisering"), 400
        return jsonify(demonstration())

    @app.post("/api/terminal/scan")
    def scan():
        if (request.get_json(silent=True) or {}).get("mode", "DEMO") != "DEMO":
            return jsonify(error="Kun DEMO er tilgaengelig"), 400
        return jsonify(scanned=5, cached=False, message="Illustrative demo-priser opdateret; ingen provider-kald")

    @app.get("/api/terminal/decisions/<int:decision_id>")
    def decision(decision_id):
        demo = demonstration()
        item = next((o for o in demo["opportunities"] if o["id"] == decision_id), None)
        if not item:
            return jsonify(error="Demo-signalet findes ikke"), 404
        event = next(e for e in feeds.demo_events() if e["id"] == item["event_id"])
        return jsonify(decision=item, recorded_decision=item, snapshot={"payload": event, "demo_only": True})

    @app.get("/api/terminal/history")
    def history():
        return jsonify(bets=[], page=1, pages=1, total=0)

    @app.get("/api/terminal/lab")
    def lab():
        return jsonify(historical_matches=0, historical_odds=0, evaluation=None)

    @app.get("/api/settings")
    def configuration():
        return jsonify({**settings.PUBLIC_DEFAULTS, "ai_daily_call_limit": 0, "ai_daily_token_budget": 0,
                        "odds_daily_request_limit": 0, "ai_usage": {"calls": 0, "reserved_tokens": 0},
                        "providers": [{**meta, "id": key, "configured": False, "masked": None, "active": False,
                                       "package_ok": False, "used_for": "Kun lokal version"}
                                      for key, meta in settings.KEYS.items()]})

    @app.route("/crypto")
    def crypto():
        return redirect("/")

    return app


app = create_app()
