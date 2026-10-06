"""Sports lifecycle: immutable inputs -> decision -> paper ledger -> evaluation."""
import hashlib
import json
import os
import statistics
import threading
import time

from . import database, feeds, models, quant, risk

STRATEGY_VERSION = "price-divergence-1"
_scan_lock = threading.Lock()
_last_scan = {}
VALID_MODES = {"DEMO", "PAPER", "REAL"}
STRATEGY_STATES = {"EXPERIMENT", "PAPER", "LIVE", "PAUSED", "REJECTED"}


def mode(value):
    if value not in VALID_MODES:
        raise ValueError("Vaelg DEMO, PAPER eller REAL")
    return value


def _account(db, current_mode):
    acc = dict(db.execute("SELECT * FROM accounts WHERE mode=?", (current_mode,)).fetchone())
    pnl = db.execute("SELECT COALESCE(SUM(pnl),0) FROM bets WHERE mode=?", (current_mode,)).fetchone()[0]
    opened = db.execute("SELECT COALESCE(SUM(stake),0) FROM bets WHERE mode=? AND status='OPEN'", (current_mode,)).fetchone()[0]
    return {**acc, "equity": acc["deposits"]+pnl, "cash": acc["deposits"]+pnl-opened, "exposure": opened, "currency": "EUR"}


def deposit(current_mode, amount):
    mode(current_mode)
    amount = quant.number(amount, .01, 1e7)
    with database.connection(write=True) as db:
        db.execute("UPDATE accounts SET deposits=deposits+? WHERE mode=?", (amount, current_mode))
        db.execute("INSERT INTO deposits(mode,amount,created_at) VALUES(?,?,?)", (current_mode, amount, time.time()))
        return _account(db, current_mode)


def set_halt(current_mode, halted):
    mode(current_mode)
    if not isinstance(halted, bool):
        raise ValueError("Handelsstop skal vaere true/false")
    with database.connection(write=True) as db:
        db.execute("UPDATE accounts SET halted=? WHERE mode=?", (int(halted), current_mode))
        database.alert(db, current_mode, "kill-switch", "Globalt stop aktivt" if halted else "Globalt stop ophaevet", "warning" if halted else "info")
    return {"halted": halted}


def _events(db, current_mode):
    return {r["id"]: dict(r) for r in db.execute("SELECT * FROM events WHERE mode=?", (current_mode,))}


def _bets(db, current_mode):
    return [dict(r) for r in db.execute("SELECT * FROM bets WHERE mode=? ORDER BY placed_at,id", (current_mode,))]


def _strategy(db, current_mode):
    s = dict(db.execute("SELECT * FROM strategies WHERE mode=?", (current_mode,)).fetchone())
    s["config"] = json.loads(s["config"])
    return s


def evaluate(event, account, bets, event_map, strategy, history=(), now=None):
    now = time.time() if now is None else now
    fresh = [b for b in event["books"] if 0 <= now-b["updated_at"] <= feeds.MAX_AGE]
    decisions = []
    for selection in event["selections"]:
        offered = max(fresh or event["books"], key=lambda b: b["prices"][selection])
        references = [b for b in fresh if b["key"] != offered["key"]]
        estimate = models.estimate(event, references, history)
        odds = offered["prices"][selection]
        reasons, action = [], "PASS"
        estimate_row = estimate["outputs"][selection] if estimate else {"p": None, "p_lower": None, "uncertainty": None, "market_p": None}
        p, lower = estimate_row["p"], estimate_row["p_lower"]
        ev = quant.ev(p, odds) if p is not None else None
        robust_ev = quant.ev(lower, odds) if lower is not None else None
        # Coverage grade describes data, not actual liquidity, which this feed does not report.
        quality = "A" if len(references) >= 4 else "B" if len(references) >= 3 else "C" if len(references) >= 2 else "D"
        expires = min(now+120, offered["updated_at"]+feeds.MAX_AGE, event["start"])
        if event["start"] <= now:
            reasons.append("Kampen er startet; in-play understottes ikke")
        elif not fresh or now-offered["updated_at"] > feeds.MAX_AGE:
            reasons.append("For gamle priser")
        elif len(references) < 3:
            reasons.append("Faerre end tre uafhaengige reference-bookmakere")
        elif estimate and abs(p-estimate_row["market_p"]) > .15:
            reasons.append("Stor model/marked-konflikt; kraever manuel datakontrol")
        elif robust_ev is None or robust_ev < risk.Limits().min_ev:
            reasons.append("Ingen tilstraekkelig EV efter usikkerhedsbuffer")
        else:
            action = "WATCH"
            reasons.append("Prisfordel mod uafhaengige referencepriser")
            if strategy["state"] in ("PAUSED", "REJECTED"):
                action = "PASS"
                reasons.append("Strategien er sat paa pause eller afvist")
            elif strategy["state"] == "EXPERIMENT":
                reasons.append("Eksperiment: edge og kalibrering er ikke valideret")
            elif event["mode"] == "REAL" and strategy["state"] != "LIVE":
                reasons.append("REAL kraever en valideret LIVE-strategi")
            elif event["mode"] == "REAL" and estimate["model_version"] != "leave-book-out-power-1":
                reasons.append("Denne modelversion er ikke godkendt til REAL")
            elif strategy["state"] in ("PAPER", "LIVE"):
                action = "BET"
        item = {"event_id": event["id"], "sport": event["sport"], "league": event["league"],
                "home": event["home"], "away": event["away"], "start": event["start"],
                "name": event["home"] if selection == "HOME" else event["away"] if selection == "AWAY" else "Uafgjort",
                "selection": selection, "bookmaker": offered["key"], "book_title": offered["title"],
                "odds": odds, "implied_p": 1/odds, "margin": offered["margin"], **estimate_row,
                "fair_odds": 1/p if p else None, "ev": ev, "robust_ev": robust_ev,
                "probability_edge": p-1/odds if p else None,
                "min_odds": quant.min_odds(lower) if lower else None,
                "score": min(100, quant.kelly(lower, odds, .5)*200) if lower else 0,
                "score_definition": "100 x fuld Kelly ved konservativ p; ikke sandsynlighed for profit",
                "quality": quality, "reference_count": len(references), "liquidity": "UNKNOWN",
                "action": action, "reasons": reasons, "stake": 0.0, "created_at": now, "expires_at": expires,
                "updated_at": offered["updated_at"], "model_version": estimate["model_version"] if estimate else "none",
                "strategy_version": STRATEGY_VERSION, "estimate": estimate,
                "counterarguments": ["Markedsreference er ikke dokumenteret sand sandsynlighed",
                                      "Buffer er metodefoelsomhed, ikke et statistisk konfidensinterval",
                                      "Limit/likviditet og bookmakerens kontoadgang er ukendt"],
                "books": [{"book": b["title"], "key": b["key"], "odds": b["prices"][selection],
                           "updated_at": b["updated_at"], "margin": b["margin"],
                           "status": "FRESH" if now-b["updated_at"] <= feeds.MAX_AGE else "STALE",
                           "ev": quant.ev(p, b["prices"][selection]) if p else None} for b in event["books"]]}
        if action == "BET":
            stake, reason = risk.propose(item, account, bets, event_map, now=now)
            item["stake"] = stake
            item["reasons"].append(reason)
            if stake <= 0:
                item["action"] = "PASS"
        decisions.append(item)
    return decisions


def ingest(events, current_mode, now=None):
    mode(current_mode)
    now = time.time() if now is None else now
    result = []
    with database.connection(write=True) as db:
        account, bets = _account(db, current_mode), _bets(db, current_mode)
        strat = _strategy(db, current_mode)
        for event in events:
            if event["mode"] != current_mode:
                raise ValueError("DEMO og live data maa ikke blandes")
            old = db.execute("SELECT * FROM events WHERE id=? AND mode=?", (event["id"], current_mode)).fetchone()
            if old and (old["home"] != event["home"] or old["away"] != event["away"] or old["sport"] != event["sport"] or old["start"] != event["start"]):
                database.alert(db, current_mode, f"identity:{event['id']}", "Kampidentitet/tid har aendret sig; nye priser er i karantaene", "error", now)
                continue
            db.execute("""INSERT INTO events VALUES(?,?,?,?,?,?,?) ON CONFLICT(id,mode) DO UPDATE SET
                          sport=excluded.sport,league=excluded.league,home=excluded.home,away=excluded.away,start=excluded.start""",
                       (event["id"], current_mode, event["sport"], event["league"], event["home"], event["away"], event["start"]))
            db.execute("INSERT OR IGNORE INTO snapshots(event_id,mode,received_at,payload,digest) VALUES(?,?,?,?,?)",
                       (event["id"], current_mode, event["received_at"], database.dumps(event), feeds.digest(event)))
            sid = db.execute("SELECT id FROM snapshots WHERE mode=? AND event_id=? AND digest=?", (current_mode, event["id"], feeds.digest(event))).fetchone()[0]
            history = [dict(r) for r in db.execute("SELECT * FROM historical_matches WHERE league=? ORDER BY start,id", (event["league"],))]
            decisions = evaluate(event, account, bets, _events(db, current_mode), strat, history, now)
            for item in decisions:
                item["snapshot_id"] = sid
                db.execute("""INSERT OR IGNORE INTO decisions(snapshot_id,event_id,mode,selection,bookmaker,created_at,
                              expires_at,action,model_version,strategy_version,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                           (sid, event["id"], current_mode, item["selection"], item["bookmaker"], now, item["expires_at"],
                            item["action"], item["model_version"], STRATEGY_VERSION, database.dumps(item)))
                row = db.execute("SELECT id,payload FROM decisions WHERE snapshot_id=? AND selection=? AND bookmaker=? AND model_version=? AND strategy_version=?",
                                 (sid, item["selection"], item["bookmaker"], item["model_version"], STRATEGY_VERSION)).fetchone()
                item = {**json.loads(row["payload"]), "id": row["id"]}
                result.append(item)
                if item["action"] == "BET":
                    database.alert(db, current_mode, f"opportunity:{event['id']}:{item['selection']}", f"Prisfordel: {event['home']} / {item['name']} @ {item['odds']:.2f}", "info", now)
        _close_prices(db, current_mode, now)
    return result


def scan(current_mode="DEMO"):
    mode(current_mode)
    with _scan_lock:
        now = time.time()
        previous = _last_scan.get(current_mode)
        if previous and now-previous < (15 if current_mode == "DEMO" else 300):
            return {"cached": True, "message": "Scan er allerede opdateret; provider-kvote spares"}
        if current_mode == "DEMO":
            events, rejected = feeds.demo_events(now), []
        else:
            from . import settings
            cfg = settings.load()
            keys = cfg.get("sports_keys", "soccer_epl").split(",")
            keys = [k.strip() for k in keys if k.strip()][:3]
            if not keys or any(not k.replace("_", "").isalnum() for k in keys):
                raise ValueError("Vaelg op til tre konkrete sport-keys")
            events, rejected = feeds.fetch_live(os.environ.get("ODDS_API_KEY"), keys)
            for event in events:
                event["mode"] = current_mode
        items = ingest(events, current_mode, now)
        _last_scan[current_mode] = now
        return {"scanned": len(events), "decisions": len(items), "rejected": rejected, "cached": False, "message": "Scan afsluttet"}


def _close_prices(db, current_mode, now):
    for bet in db.execute("SELECT b.*,e.start FROM bets b JOIN events e ON e.id=b.event_id AND e.mode=b.mode WHERE b.mode=? AND b.closing_odds IS NULL AND e.start<=?", (current_mode, now)).fetchall():
        # Must have been actually observed before kickoff; a late API fetch cannot become a close.
        snapshots = db.execute("SELECT payload,received_at FROM snapshots WHERE mode=? AND event_id=? AND received_at<=? ORDER BY received_at DESC",
                               (current_mode, bet["event_id"], bet["start"])).fetchall()
        for row in snapshots:
            event = json.loads(row["payload"])
            book = next((b for b in event["books"] if b["key"] == bet["bookmaker"]), None)
            if book and bet["start"]-feeds.MAX_AGE <= book["updated_at"] <= bet["start"] and row["received_at"] >= bet["placed_at"]:
                db.execute("UPDATE bets SET closing_odds=?,closing_at=? WHERE id=?", (book["prices"][bet["selection"]], book["updated_at"], bet["id"]))
                break


def place(decision_id, current_mode, idempotency_key, actual_odds=None, actual_stake=None):
    mode(current_mode)
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 100:
        raise ValueError("Gyldig idempotency key er paakraevet")
    now = time.time()
    with database.connection(write=True) as db:
        existing = db.execute("SELECT * FROM bets WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing:
            if existing["mode"] != current_mode or existing["decision_id"] != decision_id:
                raise ValueError("Idempotency key er allerede brugt til en anden beslutning")
            return {"bet": dict(existing), "duplicate": True}
        row = db.execute("SELECT * FROM decisions WHERE id=? AND mode=?", (decision_id, current_mode)).fetchone()
        if not row:
            raise ValueError("Beslutningen findes ikke i denne tilstand")
        latest = db.execute("SELECT id FROM snapshots WHERE mode=? AND event_id=? ORDER BY received_at DESC,id DESC LIMIT 1", (current_mode, row["event_id"])).fetchone()
        if row["snapshot_id"] != latest[0]:
            raise ValueError("En nyere pris findes. Aabn den nyeste analyse.")
        event = json.loads(db.execute("SELECT payload FROM snapshots WHERE id=?", (row["snapshot_id"],)).fetchone()[0])
        history = [dict(r) for r in db.execute("SELECT * FROM historical_matches WHERE league=? ORDER BY start,id", (event["league"],))]
        choices = evaluate(event, _account(db, current_mode), _bets(db, current_mode), _events(db, current_mode), _strategy(db, current_mode), history, now)
        fresh = next((c for c in choices if c["selection"] == row["selection"] and c["bookmaker"] == row["bookmaker"]), None)
        if row["action"] != "BET" or not fresh or fresh["action"] != "BET" or now >= row["expires_at"]:
            raise ValueError("Beslutningen er udloebet eller opfylder ikke laengere risiko/priskrav")
        if current_mode == "REAL":
            # Bookkeeping for a manually placed bet only. No sportsbook execution adapter.
            odds = quant.decimal(actual_odds)
            stake = quant.number(actual_stake, .01, fresh["stake"])
            if odds < fresh["min_odds"] or odds > fresh["odds"]:
                raise ValueError("Registreret pris ligger uden for godkendt prisinterval")
        else:
            odds, stake = fresh["odds"], fresh["stake"]
        if db.execute("SELECT 1 FROM bets WHERE mode=? AND event_id=? AND market='h2h' AND selection=?", (current_mode, event["id"], row["selection"])).fetchone():
            raise ValueError("Kampudfald er allerede registreret")
        cur = db.execute("""INSERT INTO bets(decision_id,mode,event_id,sport,league,selection,bookmaker,market,odds,p,
                           market_p,ev,stake,status,placed_at,model_version,strategy_version,idempotency_key)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?,?,?,?)""",
                         (decision_id, current_mode, event["id"], event["sport"], event["league"], row["selection"], row["bookmaker"], "h2h",
                          odds, fresh["p"], fresh["market_p"], quant.ev(fresh["p"], odds), stake, now, row["model_version"], STRATEGY_VERSION, idempotency_key))
        return {"bet": dict(db.execute("SELECT * FROM bets WHERE id=?", (cur.lastrowid,)).fetchone()), "duplicate": False}


def settle(current_mode, event_id, winner=None, void=False, source="manual", now=None):
    mode(current_mode)
    if not isinstance(void, bool) or (not void and winner not in {"HOME", "DRAW", "AWAY"}):
        raise ValueError("Vaelg gyldigt udfald eller annullering")
    now = time.time() if now is None else now
    with database.connection(write=True) as db:
        event = db.execute("SELECT * FROM events WHERE mode=? AND id=?", (current_mode, event_id)).fetchone()
        if not event or event["start"] >= now:
            raise ValueError("Kamp mangler eller er ikke startet")
        if winner == "DRAW" and not event["sport"].startswith("soccer_"):
            raise ValueError("Uafgjort findes ikke i dette 2-vejs marked")
        old = db.execute("SELECT * FROM results WHERE mode=? AND event_id=?", (current_mode, event_id)).fetchone()
        if old:
            if old["winner"] != winner or bool(old["void"]) != void:
                raise ValueError("Resultat findes allerede; historik maa ikke overskrives")
            return {"settled": 0, "duplicate": True}
        db.execute("INSERT INTO results VALUES(?,?,?,?,?,?)", (current_mode, event_id, winner, int(void), now, source))
        _close_prices(db, current_mode, now)
        opened = db.execute("SELECT * FROM bets WHERE mode=? AND event_id=? AND status='OPEN'", (current_mode, event_id)).fetchall()
        for bet in opened:
            status = "VOID" if void else "WON" if bet["selection"] == winner else "LOST"
            pnl = 0 if void else bet["stake"]*(bet["odds"]-1) if status == "WON" else -bet["stake"]
            db.execute("UPDATE bets SET status=?,pnl=?,settled_at=? WHERE id=?", (status, pnl, now, bet["id"]))
        return {"settled": len(opened), "duplicate": False}


def settle_from_feed(current_mode):
    mode(current_mode)
    if current_mode == "DEMO":
        return {"settled": 0}
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise ValueError("Odds API-noegle mangler")
    with database.connection() as db:
        opened = _bets(db, current_mode)
        events = _events(db, current_mode)
    now = time.time()
    with database.connection() as db:
        missing = {r[0] for r in db.execute("SELECT e.id FROM events e LEFT JOIN results r ON r.event_id=e.id AND r.mode=e.mode WHERE e.mode=? AND r.event_id IS NULL AND e.start<? AND e.start>?", (current_mode, now, now-3*86400))}
    due = [e for e in events.values() if e["id"] in missing]
    total = 0
    for sport in sorted({e["sport"] for e in due}):
        for result in feeds.completed_scores(key, sport):
            event = events.get(str(result.get("id")))
            if not event or event["home"] != result.get("home_team") or event["away"] != result.get("away_team"):
                continue
            values = {r.get("name"): r.get("score") for r in result.get("scores", [])}
            try:
                home = quant.number(values.get(event["home"]), 0, 30)
                away = quant.number(values.get(event["away"]), 0, 30)
                if home != int(home) or away != int(away):
                    raise ValueError("Ugyldigt maalresultat")
            except ValueError:
                continue
            winner = "HOME" if home > away else "AWAY" if away > home else "DRAW"
            total += settle(current_mode, event["id"], winner, source="the-odds-api-completed-league")['settled']
    return {"settled": total}


def paper_cycle():
    scan("PAPER")
    settle_from_feed("PAPER")
    snapshot = overview("PAPER")
    placed = 0
    for decision in snapshot["opportunities"]:
        if decision["action"] != "BET":
            continue
        try:
            placed += not place(decision["id"], "PAPER", f"paper-cycle:{decision['id']}")["duplicate"]
        except ValueError:
            # Other entries may have consumed event/team exposure; risk is rechecked transactionally.
            continue
    return {"placed": placed, "scanned": snapshot["brain"]["markets"]}


def update_strategy(current_mode, state):
    mode(current_mode)
    if state not in STRATEGY_STATES:
        raise ValueError("Ukendt strategitilstand")
    with database.connection(write=True) as db:
        if state == "LIVE":
            if current_mode != "REAL":
                raise ValueError("LIVE er kun til REAL")
            verified = [dict(r) for r in db.execute("""SELECT b.* FROM bets b JOIN results r ON r.mode=b.mode AND r.event_id=b.event_id
                         WHERE b.mode='PAPER' AND r.source='the-odds-api-completed-league'
                         AND b.model_version='leave-book-out-power-1' AND b.strategy_version=? ORDER BY placed_at,id""", (STRATEGY_VERSION,))]
            evidence = quant.performance(verified, _account(db, "PAPER")["deposits"])
            if (evidence["decisive"] < 500 or evidence["clv_n"] < 100 or (evidence["clv"] or 0) <= 0
                    or not evidence["roi_ci"] or evidence["roi_ci"][0] <= 0):
                raise ValueError("LIVE er laast: kraever >=500 provider-afgjorte PAPER-bets i denne modelversion, >=100 CLV-observationer, positiv CLV og positiv nedre ROI-graense")
            if evidence["calibration"]["brier"] > evidence["baseline"]["brier"]:
                raise ValueError("LIVE er laast: model skal mindst matche markedsbaselinens Brier")
            # Results must belong to the active version, not earlier lucky models.
            active = verified
            if len([b for b in active if b["status"] in ("WON", "LOST")]) < 500:
                raise ValueError("Utilstraekkelig versionsspecifik dokumentation")
        if current_mode == "REAL" and state == "PAPER":
            raise ValueError("Vaelg PAPER-kontoen til papirhandel")
        db.execute("UPDATE strategies SET state=? WHERE mode=?", (state, current_mode))
    return {"state": state}


def _current_availability(item, account, bets, events, strategy, now, current_mode):
    if item["expires_at"] <= now or item["start"] <= now:
        item.update(action="PASS", stake=0, reasons=["Pris/beslutning er udloebet; scan igen"])
    elif item["action"] == "BET":
        if strategy["state"] not in ("PAPER", "LIVE") or current_mode == "REAL" and strategy["state"] != "LIVE":
            item.update(action="WATCH", stake=0, reasons=["Strategi er ikke aktiveret til registrering"])
        else:
            stake, reason = risk.propose(item, account, bets, events, now=now)
            item["stake"] = stake
            if stake <= 0:
                item.update(action="PASS", reasons=[reason])
    return item


def overview(current_mode="DEMO", query="", action="", model_version="", sport="", period_days=0):
    mode(current_mode)
    now = time.time()
    with database.connection() as db:
        account, bets, events = _account(db, current_mode), _bets(db, current_mode), _events(db, current_mode)
        rows = db.execute("""SELECT d.* FROM decisions d JOIN (SELECT event_id,MAX(id) id FROM snapshots WHERE mode=? GROUP BY event_id) s
                             ON s.id=d.snapshot_id WHERE d.mode=? ORDER BY d.created_at DESC,d.id DESC LIMIT 900""", (current_mode, current_mode)).fetchall()
        opportunities, unique = [], set()
        for r in rows:
            item = {**json.loads(r["payload"]), "id": r["id"]}
            key = (item["event_id"], item["selection"])
            if key in unique:
                continue
            unique.add(key)
            if item["start"] <= now:
                continue
            item = _current_availability(item, account, bets, events, _strategy(db, current_mode), now, current_mode)
            if action and item["action"] != action:
                continue
            if query and query.casefold() not in (item["home"]+item["away"]+item["name"]).casefold():
                continue
            if model_version and item["model_version"] != model_version or sport and item["sport"] != sport:
                continue
            opportunities.append(item)
        opportunities.sort(key=lambda x: ({"BET": 0, "WATCH": 1, "PASS": 2}[x["action"]], -(x["robust_ev"] or -1)))
        filtered = [b for b in bets if (not model_version or b["model_version"] == model_version) and (not sport or b["sport"] == sport)
                    and (not period_days or b["placed_at"] >= now-period_days*86400)]
        metrics = quant.performance(filtered, account["deposits"])
        deposits = [dict(r) for r in db.execute("SELECT * FROM deposits WHERE mode=? ORDER BY created_at,id", (current_mode,))]
        ledger_curve = quant.cashflow_curve(bets, deposits)
        metrics["curve"] = ledger_curve["curve"]
        metrics["drawdown"] = ledger_curve["drawdown"]
        # First pre-match prediction per event/selection/version, including WATCH and PASS.
        observed = db.execute("""SELECT d.payload,d.event_id,d.selection,d.model_version,r.winner,r.void
                                 FROM decisions d JOIN results r ON r.event_id=d.event_id AND r.mode=d.mode
                                 JOIN events e ON e.id=d.event_id AND e.mode=d.mode
                                 WHERE d.mode=? AND d.created_at<e.start AND d.created_at<r.received_at
                                 ORDER BY d.created_at,d.id LIMIT 50000""", (current_mode,)).fetchall()
        selected_calibration_version = model_version or "leave-book-out-power-1"
        observations, baseline_observations, seen = [], [], set()
        for row in observed:
            identity = (row["event_id"], row["selection"], row["model_version"])
            item = json.loads(row["payload"])
            if row["void"] or identity in seen or item["p"] is None:
                continue
            if row["model_version"] != selected_calibration_version or sport and item["sport"] != sport:
                continue
            seen.add(identity)
            observations.append({"p": item["p"], "y": int(row["winner"] == row["selection"]), "event_id": row["event_id"], "version": row["model_version"]})
            baseline_observations.append({"p": item["market_p"], "y": int(row["winner"] == row["selection"])})
        all_calibration = quant.calibration(observations)
        all_calibration["events"] = len({r["event_id"] for r in observations})
        all_calibration["model_version"] = selected_calibration_version
        groups = {}
        for b in filtered:
            groups.setdefault(b["model_version"], []).append(b)
        strategy = _strategy(db, current_mode)
        health = "AFVENTER DATA" if metrics["decisive"] < 100 else "EKSPERIMENTEL"
        drift = None
        decisive = [b for b in filtered if b["status"] in ("WON", "LOST")]
        if len(decisive) >= 200:
            recent, earlier = quant.performance(decisive[-100:]), quant.performance(decisive[:-100])
            if (recent["calibration"]["brier"] > earlier["calibration"]["brier"]+.05
                    or recent["clv_n"] >= 30 and recent["clv"] < 0):
                health, drift = "KRAVER REVALIDERING", "Seneste 100: Brier forvaerret eller negativ CLV. Reducer eksponering og revalider."
        from . import scheduler
        return {"mode": current_mode, "account": account, "metrics": metrics, "strategy": strategy,
                "opportunities": opportunities[:200], "opportunity_count": len(opportunities),
                "bets": [{**b, "event": events.get(b["event_id"], {}),
                          "clv": quant.clv(b["odds"], b["closing_odds"]) if b["closing_odds"] else None,
                          "review": "Afventer resultat" if b["status"] == "OPEN" else "Annulleret" if b["status"] == "VOID" else
                          "Resultat alene kan ikke skelne modelfejl fra varians; vurder kalibrering og CLV"} for b in reversed(filtered[-200:])],
                "open_bets": [{**b, "event": events.get(b["event_id"], {}), "clv": None} for b in filtered if b["status"] == "OPEN"],
                "total_bets": len(filtered), "open_count": sum(b["status"] == "OPEN" for b in filtered),
                "versions": [{"version": key, "metrics": quant.performance(group, account["deposits"])} for key, group in groups.items()],
                "model_health": health, "drift": drift, "model_calibration": all_calibration,
                "model_baseline": quant.calibration(baseline_observations), "scheduler": scheduler.status(),
                "alerts": [dict(r) for r in db.execute("SELECT * FROM alerts WHERE mode=? ORDER BY updated_at DESC LIMIT 15", (current_mode,))],
                "providers": [dict(r) for r in db.execute("SELECT * FROM provider_status")],
                "brain": {"markets": len({o['event_id'] for o in opportunities}), "bet": sum(o["action"] == "BET" for o in opportunities),
                          "watch": sum(o["action"] == "WATCH" for o in opportunities), "pass": sum(o["action"] == "PASS" for o in opportunities),
                          "stale": sum(o["expires_at"] <= now for o in opportunities), "largest_ev": max((o["ev"] or 0 for o in opportunities), default=None)},
                "server_time": now, "limits": risk.Limits().as_dict(),
                "edge_status": "INGEN DOKUMENTERET EDGE", "execution": "PAPER ledger" if current_mode != "REAL" else "Manuel registrering; ingen bookmaker-ordrer"}


def decision_detail(decision_id, current_mode):
    mode(current_mode)
    with database.connection() as db:
        row = db.execute("SELECT * FROM decisions WHERE id=? AND mode=?", (decision_id, current_mode)).fetchone()
        if not row:
            raise ValueError("Beslutningen findes ikke")
        snapshot = db.execute("SELECT * FROM snapshots WHERE id=?", (row["snapshot_id"],)).fetchone()
        original = {**json.loads(row["payload"]), "id": row["id"]}
        current = _current_availability(dict(original), _account(db, current_mode), _bets(db, current_mode), _events(db, current_mode), _strategy(db, current_mode), time.time(), current_mode)
        return {"decision": current, "recorded_decision": original,
                "snapshot": {**dict(snapshot), "payload": json.loads(snapshot["payload"])}}
