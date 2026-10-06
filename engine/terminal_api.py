"""Authenticated terminal endpoints. POST mutations are CSRF protected by app.py."""
import csv
import io
import json

from flask import Blueprint, jsonify, request, Response

from . import intelligence, lab, research, quant

api = Blueprint("terminal", __name__, url_prefix="/api/terminal")


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("En JSON-genstand er paakraevet")
    return data


@api.get("/overview")
def overview():
    return jsonify(intelligence.overview(request.args.get("mode", "DEMO"), request.args.get("q", ""),
                                        request.args.get("action", ""), request.args.get("model", ""),
                                        request.args.get("sport", ""), int(quant.number(request.args.get("days", 0), 0, 3650))))


@api.post("/scan")
def scan():
    return jsonify(intelligence.scan(body().get("mode", "DEMO")))


@api.post("/deposit")
def deposit():
    data = body()
    return jsonify(intelligence.deposit(data.get("mode"), data.get("amount")))


@api.post("/halt")
def halt():
    data = body()
    return jsonify(intelligence.set_halt(data.get("mode"), data.get("halted")))


@api.post("/strategy")
def strategy():
    data = body()
    return jsonify(intelligence.update_strategy(data.get("mode"), data.get("state")))


@api.get("/decisions/<int:decision_id>")
def decision(decision_id):
    return jsonify(intelligence.decision_detail(decision_id, request.args.get("mode", "DEMO")))


@api.post("/bets")
def place():
    data = body()
    decision_id = int(quant.number(data.get("decision_id"), 1))
    return jsonify(intelligence.place(decision_id, data.get("mode"), data.get("idempotency_key"), data.get("odds"), data.get("stake")))


@api.post("/settle")
def settle():
    data = body()
    return jsonify(intelligence.settle(data.get("mode"), data.get("event_id"), data.get("winner"), data.get("void", False)))


@api.post("/settle-feed")
def settle_feed():
    return jsonify(intelligence.settle_from_feed(body().get("mode")))


@api.post("/explain")
def explain():
    data = body()
    detail = intelligence.decision_detail(int(quant.number(data.get("decision_id"), 1)), data.get("mode"))
    return jsonify(research.explain(detail["decision"]))


@api.get("/history/export")
def export():
    mode = request.args.get("mode", "DEMO")
    with intelligence.database.connection() as db:
        bets = intelligence._bets(db, intelligence.mode(mode))
    fields = ["id", "mode", "event_id", "sport", "league", "selection", "bookmaker", "odds", "closing_odds", "p", "market_p", "ev", "stake", "status", "pnl", "placed_at", "settled_at", "model_version", "strategy_version"]
    text = io.StringIO()
    writer = csv.DictWriter(text, fields, extrasaction="ignore")
    writer.writeheader()
    for bet in bets:
        writer.writerow({key: "'"+value if isinstance(value,str) and value[:1] in {"=", "+", "-", "@", "\t", "\r"} else value for key,value in bet.items()})
    return Response(text.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="DDM_{mode}_history.csv"'})


@api.get("/history")
def history():
    current_mode = intelligence.mode(request.args.get("mode", "DEMO"))
    page = int(quant.number(request.args.get("page", 1), 1, 100000))
    status = request.args.get("status", "")
    if status and status not in {"OPEN", "WON", "LOST", "VOID"}:
        raise ValueError("Ugyldigt resultatfilter")
    query = request.args.get("q", "")[:200].casefold()
    sorts = {"time": "b.placed_at DESC,b.id DESC", "odds": "b.odds DESC,b.id DESC", "pnl": "b.pnl DESC,b.id DESC"}
    order = sorts.get(request.args.get("sort", "time"), sorts["time"])
    where, params = "b.mode=?", [current_mode]
    if status:
        where += " AND b.status=?"
        params.append(status)
    if query:
        where += " AND ddm_casefold(e.home||' '||e.away||' '||b.selection||' '||b.bookmaker) LIKE ?"
        params.append("%"+query+"%")
    join = " FROM bets b JOIN events e ON e.id=b.event_id AND e.mode=b.mode WHERE "+where
    with intelligence.database.connection() as db:
        count = db.execute("SELECT COUNT(*)"+join, params).fetchone()[0]
        rows = db.execute("SELECT b.*,e.home,e.away,e.start"+join+" ORDER BY "+order+" LIMIT 50 OFFSET ?", params+[(page-1)*50]).fetchall()
    bets = []
    for row in rows:
        bet = dict(row)
        bet["event"] = {"home": bet.pop("home"), "away": bet.pop("away"), "start": bet.pop("start")}
        bet["clv"] = quant.clv(bet["odds"], bet["closing_odds"]) if bet["closing_odds"] else None
        bets.append(bet)
    return jsonify({"bets": bets, "total": count, "page": page, "pages": max(1,(count+49)//50)})


@api.get("/lab")
def lab_status():
    return jsonify(lab.status())


@api.post("/lab/results")
def results_import():
    data = body()
    text = data.get("csv")
    if not isinstance(text, str):
        raise ValueError("CSV-tekst er paakraevet")
    return jsonify(lab.import_results(text))


@api.post("/lab/odds")
def odds_import():
    return jsonify(lab.import_odds(body().get("events")))


@api.post("/lab/evaluate")
def evaluate():
    return jsonify(lab.evaluate_history())


@api.post("/monte-carlo")
def monte_carlo():
    data = body()
    current_mode = intelligence.mode(data.get("mode", "DEMO"))
    with intelligence.database.connection() as db:
        bets = intelligence._bets(db, current_mode)
        starting = intelligence._account(db, current_mode)["deposits"]
    # One entry per event-selection. Cap workload and don't accidentally combine versions/modes.
    return jsonify(quant.monte_carlo(bets[-300:], starting, int(quant.number(data.get("runs", 2000), 100, 5000))))
