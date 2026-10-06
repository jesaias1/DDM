"""Chronological imports and frozen holdout evaluations. No synthetic backtest claims."""
import csv
import hashlib
import io
import json
import math
import statistics
import time

from . import database, feeds, intelligence, models, quant


def import_results(text):
    required = {"id", "league", "home", "away", "start", "available_at", "home_goals", "away_goals", "source"}
    reader = csv.DictReader(io.StringIO(text))
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("CSV mangler: "+", ".join(sorted(required-set(reader.fieldnames or []))))
    rows = []
    for i, r in enumerate(reader):
        if i >= 10000:
            raise ValueError("Maks 10.000 resultater pr. import")
        start, available = feeds.timestamp(r["start"]), feeds.timestamp(r["available_at"])
        hg, ag = quant.number(r["home_goals"], 0, 30), quant.number(r["away_goals"], 0, 30)
        if available <= start or hg != int(hg) or ag != int(ag):
            raise ValueError(f"Linje {i+2}: ugyldige maal eller resultat foer kampstart")
        if not all(str(r[k]).strip() for k in ("id", "league", "home", "away", "source")) or feeds.label(r["home"]) == feeds.label(r["away"]):
            raise ValueError(f"Linje {i+2}: manglende identitet/kilde")
        rows.append((r["id"], r["league"], r["home"], r["away"], start, available, int(hg), int(ag), r["source"]))
    with database.connection(write=True) as db:
        for row in rows:
            old = db.execute("SELECT * FROM historical_matches WHERE id=?", (row[0],)).fetchone()
            if old and tuple(old) != row:
                raise ValueError("Resultatet "+row[0]+" findes med andre vaerdier; historik er uforanderlig")
            db.execute("INSERT OR IGNORE INTO historical_matches VALUES(?,?,?,?,?,?,?,?,?)", row)
    return {"imported": len(rows)}


def import_odds(raw_events):
    if not isinstance(raw_events, list) or len(raw_events) > 2000:
        raise ValueError("Forventer en liste med maks 2.000 odds-snapshots")
    events = []
    for raw in raw_events:
        received = feeds.timestamp(raw.get("received_at"))
        event = feeds.normalize(raw, received, "PAPER")
        if received >= event["start"]:
            raise ValueError("Historisk odds-import maa kun indeholde observerede pre-match priser")
        events.append(event)
    with database.connection(write=True) as db:
        for event in events:
            db.execute("INSERT OR IGNORE INTO historical_odds VALUES(?,?,?,?)",
                       (feeds.digest(event), event["id"], event["received_at"], database.dumps(event)))
    return {"imported": len(events)}


def _multiclass(predictions):
    if not predictions:
        return {"events": 0, "brier": None, "log_loss": None, "selection_calibration": quant.calibration([])}
    obs = []
    brier = logloss = 0.0
    for row in predictions:
        brier += sum((p-(s == row["winner"]))**2 for s, p in row["p"].items())
        logloss -= math.log(max(1e-12, row["p"][row["winner"]]))
        obs.extend({"p": p, "y": s == row["winner"]} for s, p in row["p"].items())
    return {"events": len(predictions), "brier": brier/len(predictions), "log_loss": logloss/len(predictions),
            "selection_calibration": quant.calibration(obs)}


def evaluate_history():
    from sklearn.isotonic import IsotonicRegression
    with database.connection() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM historical_matches ORDER BY start,id")]
        odds_rows = [dict(r) for r in db.execute("SELECT * FROM historical_odds ORDER BY received_at")]
    if len(rows) < 300:
        raise ValueError("Kraever mindst 300 historiske kampe; import af resultater beviser ikke en betting-edge")
    data_hash = hashlib.sha256(database.dumps({"results": rows, "odds": odds_rows}).encode()).hexdigest()
    with database.connection() as db:
        old = db.execute("SELECT payload FROM evaluations WHERE dataset_hash=? AND model_version=?", (data_hash, models.VERSION)).fetchone()
        if old:
            return {**json.loads(old[0]), "frozen": True}
    cut1, cut2 = int(len(rows)*.6), int(len(rows)*.8)
    # Keep equal kickoff timestamps in the same partition.
    train_end, valid_end = rows[cut1]["start"], rows[cut2]["start"]
    sets = {"train": [], "validation": [], "holdout": []}
    by_league = {}
    for row in rows:
        by_league.setdefault(row["league"], []).append(row)
    for row in rows:
        partition = "train" if row["start"] < train_end else "validation" if row["start"] < valid_end else "holdout"
        prediction = models.football_probabilities(row["home"], row["away"], by_league[row["league"]], row["start"])
        if not prediction:
            continue
        sets[partition].append({"event_id": row["id"], "start": row["start"], "available_at": row["available_at"],
                                "p": prediction["probabilities"], "winner": "HOME" if row["home_goals"] > row["away_goals"] else "AWAY" if row["away_goals"] > row["home_goals"] else "DRAW",
                                "inputs": prediction["inputs"], "data_version": prediction["data_version"]})
    calibrated = []
    fitted = {}
    # Calibration is fit ONLY to chronological validation predictions, never holdout outcomes.
    if len(sets["validation"]) >= 100:
        for selection in ("HOME", "DRAW", "AWAY"):
            fitted[selection] = IsotonicRegression(out_of_bounds="clip").fit(
                [r["p"][selection] for r in sets["validation"]], [int(r["winner"] == selection) for r in sets["validation"]])
        for r in sets["holdout"]:
            ps = {s: float(model.predict([r["p"][s]])[0]) for s, model in fitted.items()}
            total = sum(ps.values())
            calibrated.append({**r, "p": {s: p/total for s, p in ps.items()} if total else r["p"]})
    # A predeclared 60-minute cutoff. Post-cutoff snapshots cannot be used as entry prices.
    by_event = {}
    for row in odds_rows:
        event = json.loads(row["payload"])
        if event["received_at"] <= event["start"]-3600:
            by_event[event["id"]] = event
    results_by_id = {r["id"]: r for r in rows}
    backtest = _replay(sorted(by_event.values(), key=lambda e: e["received_at"]), results_by_id, rows, train_end, valid_end)
    result = {"dataset_hash": data_hash, "model_version": models.VERSION, "feature_version": models.FEATURE_VERSION,
              "created_at": time.time(), "split": {"train_end": train_end, "validation_end": valid_end},
              "partitions": {name: _multiclass(values) for name, values in sets.items()},
              "calibrated_holdout": _multiclass(calibrated),
              "calibration_version": "isotonic-validation-1" if fitted else "none-insufficient-validation",
              "calibration_knots": {s: {"x": list(map(float, m.X_thresholds_)), "y": list(map(float, m.y_thresholds_))} for s, m in fitted.items()},
              "backtest": backtest, "frozen": False,
              "limitations": ["Poisson er en eksperimentel maalmodel; ingen skader/opstillinger eller Dixon-Coles korrektion",
                              "Resultater opdaterer historikken foerst ved available_at; ingen fremtidige resultater indgaar",
                              "Ukendt historisk univers: survivorship bias kan ikke udelukkes",
                              "Individuelle selektioner i kalibreringskurven er ikke uafhaengige kampe",
                              "Holdout fryses for samme dataset/model; nye modeller maa ikke tunes paa denne holdout",
                              "Isotonic er evalueret her og aktiveres ikke automatisk i produktion"],
              "predictions": sets["holdout"][:500]}
    with database.connection(write=True) as db:
        db.execute("INSERT INTO evaluations(created_at,dataset_hash,model_version,payload) VALUES(?,?,?,?)",
                   (result["created_at"], data_hash, models.VERSION, database.dumps(result)))
    return result


def _replay(events, results, history, train_end=0, valid_end=0):
    starting, cash, bets = 1000.0, 1000.0, []
    event_map = {e["id"]: e for e in events}
    for event in events:
        result = results.get(event["id"])
        if not result or result["home"] != event["home"] or result["away"] != event["away"] or result["start"] != event["start"]:
            continue
        now = event["received_at"]
        # Release funds only when historical result actually became available.
        for bet in bets:
            known = results[bet["event_id"]]
            if bet["status"] == "OPEN" and known["available_at"] <= now:
                won = bet["selection"] == ("HOME" if known["home_goals"] > known["away_goals"] else "AWAY" if known["away_goals"] > known["home_goals"] else "DRAW")
                bet.update(status="WON" if won else "LOST", pnl=bet["stake"]*(bet["odds"]-1) if won else -bet["stake"], settled_at=known["available_at"])
                cash += bet["stake"]+bet["pnl"]
        equity = cash+sum(b["stake"] for b in bets if b["status"] == "OPEN")
        account = {"equity": equity, "cash": cash, "halted": False}
        filtered_history = [r for r in history if r["league"] == event["league"]]
        opportunities = intelligence.evaluate(event, account, bets, event_map, {"state": "PAPER"}, filtered_history, now)
        for opp in sorted(opportunities, key=lambda o: -(o["robust_ev"] or -1)):
            # Recompute after every entry; event/correlation caps apply sequentially.
            from . import risk
            stake, _ = risk.propose(opp, {"equity": equity, "cash": cash, "halted": False}, bets, event_map, now=now)
            if opp["action"] != "BET" or stake <= 0:
                continue
            bet = {"id": len(bets)+1, "event_id": event["id"], "selection": opp["selection"], "sport": event["sport"], "league": event["league"],
                   "market": "h2h", "placed_at": now, "stake": stake, "odds": opp["odds"], "p": opp["p"], "market_p": opp["market_p"],
                   "ev": opp["ev"], "status": "OPEN", "pnl": 0, "closing_odds": None,
                   "model_version": opp["model_version"], "input_snapshot": event, "estimate": opp["estimate"]}
            bets.append(bet)
            cash -= stake
    # Settlement after all prediction/entry decisions. No result can affect past stake sizing.
    for bet in bets:
        if bet["status"] == "OPEN":
            known = results[bet["event_id"]]
            won = bet["selection"] == ("HOME" if known["home_goals"] > known["away_goals"] else "AWAY" if known["away_goals"] > known["home_goals"] else "DRAW")
            bet.update(status="WON" if won else "LOST", pnl=bet["stake"]*(bet["odds"]-1) if won else -bet["stake"], settled_at=known["available_at"])
    return {"mode": "BACKTEST", "starting": starting, "events_with_prices": len(events),
            "metrics": quant.performance(bets, starting), "bets": bets,
            "partitions": {name: quant.performance([b for b in bets if ("train" if results[b['event_id']]['start'] < train_end else "validation" if results[b['event_id']]['start'] < valid_end else "holdout") == name], starting)
                           for name in ("train", "validation", "holdout")},
            "discovery": discover(bets, results, train_end, valid_end),
            "price_cutoff_seconds": 3600, "closing_prices": "Ikke tilgaengelige i denne replay", "edge_proven": False}


def discover(bets, results, train_end, valid_end):
    """Predeclared EV buckets. Discover on train; report unseen partitions without tuning."""
    from scipy.stats import t
    candidates = []
    boundaries = [(.02,.05),(.05,.10),(.10,.20),(.20,1)]
    for low, high in boundaries:
        subset = [b for b in bets if low <= b['ev'] < high]
        partitions = {key: [b for b in subset if ('train' if results[b['event_id']]['start'] < train_end else 'validation' if results[b['event_id']]['start'] < valid_end else 'holdout') == key]
                      for key in ('train','validation','holdout')}
        stats = {key: quant.performance(group) for key, group in partitions.items()}
        # Approximate event-cluster t interval, with Bonferroni correction for four tests.
        clusters = {}
        for bet in partitions['train']:
            stake, pnl = clusters.get(bet['event_id'], (0,0))
            clusters[bet['event_id']] = (stake+bet['stake'],pnl+bet['pnl'])
        lower = None
        if len(clusters) >= 50:
            turnover = sum(v[0] for v in clusters.values())
            roi = sum(v[1] for v in clusters.values())/turnover
            residuals = [p-roi*s for s,p in clusters.values()]
            n = len(residuals)
            se = math.sqrt(n/(n-1)*sum(v*v for v in residuals))/turnover
            lower = roi-float(t.ppf(1-.05/(2*len(boundaries)), n-1))*se
        candidates.append({'name': f'EV {int(low*100)}-{int(high*100)}%', 'state':'EXPERIMENT',
                           'train_adjusted_roi_lower': lower,
                           'candidate': lower is not None and lower > 0,
                           'partitions': stats})
    return {'tests':len(boundaries), 'candidates': candidates,
            'method':'Forhaandsdefinerede EV-intervaller. Train-only udvaelgelse; fire Bonferroni-korrigerede omtrentlige event-cluster t-intervaller.',
            'limitation':'Undergrupper af en fast replay er exploratory, ikke nye eksekverbare backtests. Afhaengighed mellem kampe kan bryde intervaller. Ingen automatisk forfremmelse.'}


def status():
    with database.connection() as db:
        count = db.execute("SELECT COUNT(*) FROM historical_matches").fetchone()[0]
        odds = db.execute("SELECT COUNT(*) FROM historical_odds").fetchone()[0]
        last = db.execute("SELECT id,payload FROM evaluations ORDER BY id DESC LIMIT 1").fetchone()
        return {"historical_matches": count, "historical_odds": odds,
                "evaluation": {"id": last["id"], **json.loads(last["payload"])} if last else None}
