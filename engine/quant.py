"""Deterministic decimal-odds mathematics. All returns are per unit staked."""
import math
import random
import statistics
from functools import lru_cache
import copy
import json


def number(value, low=None, high=None):
    if isinstance(value, bool):
        raise ValueError("Et tal er paakraevet")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError("Et gyldigt tal er paakraevet") from None
    if not math.isfinite(x) or (low is not None and x < low) or (high is not None and x > high):
        raise ValueError("Tallet er uden for det tilladte interval")
    return x


def probability(p):
    return number(p, 0, 1)


def decimal(odds):
    x = number(odds, 1.000001, 10000)
    return x


def american_to_decimal(odds):
    x = number(odds)
    if abs(x) < 100:
        raise ValueError("Amerikanske odds skal vaere >=100 eller <=-100")
    return 1 + (x / 100 if x > 0 else 100 / -x)


def no_vig(odds, method="power"):
    q = [1 / decimal(o) for o in odds]
    if not 2 <= len(q) <= 3:
        raise ValueError("Kun komplette 2- og 3-vejs markeder understottes")
    total = sum(q)
    if method == "proportional":
        return [p / total for p in q]
    if method == "power":
        lo, hi = 0.01, 100.0
        for _ in range(100):
            exponent = (lo + hi) / 2
            if sum(p ** exponent for p in q) > 1:
                lo = exponent
            else:
                hi = exponent
        return [p ** ((lo + hi) / 2) for p in q]
    if method == "shin":
        if total < 1 - 1e-9:
            raise ValueError("Shin kraever ikke-negativ bookmaker-margin")
        if abs(total - 1) < 1e-9:
            return q
        def probs(z):
            return [(math.sqrt(z*z + 4*(1-z)*p*p/total) - z) / (2*(1-z)) for p in q]
        lo, hi = 0.0, 0.999999
        for _ in range(100):
            mid = (lo + hi) / 2
            if sum(probs(mid)) > 1:
                lo = mid
            else:
                hi = mid
        return probs((lo + hi) / 2)
    raise ValueError("Ukendt metode til marginfjernelse")


def effective_odds(odds, commission=0):
    return 1 + (decimal(odds) - 1) * (1 - number(commission, 0, 0.99))


def ev(p, odds, commission=0):
    return probability(p) * effective_odds(odds, commission) - 1


def min_odds(p, required_ev=0.02, commission=0):
    p = number(p, 0.000001, 1)
    return 1 + (((1 + number(required_ev, 0, 1)) / p) - 1) / (1 - number(commission, 0, 0.99))


def kelly(p, odds, fraction=0.25):
    b = effective_odds(odds) - 1
    return max(0, ev(p, odds) / b) * number(fraction, 0, 0.5)


def clv(taken_odds, closing_odds):
    """Price CLV = taken / same-book closing - 1; not no-vig expected value."""
    return decimal(taken_odds) / decimal(closing_odds) - 1


def calibration(rows, bins=10):
    """Binary selection-level metrics; callers deduplicate correlated predictions."""
    if not rows:
        return {"n": 0, "brier": None, "log_loss": None, "ece": None, "bins": []}
    groups = [[] for _ in range(bins)]
    brier, loss = 0.0, 0.0
    for row in rows:
        p, y = probability(row["p"]), int(number(int(row["y"]) if isinstance(row["y"], bool) else row["y"], 0, 1))
        if row["y"] not in (0, 1):
            raise ValueError("Udfald skal vaere 0 eller 1")
        pc = min(1 - 1e-12, max(1e-12, p))
        brier += (p-y)**2
        loss -= y*math.log(pc) + (1-y)*math.log(1-pc)
        groups[min(bins-1, int(p*bins))].append((p, y))
    curve, ece = [], 0.0
    for i, group in enumerate(groups):
        if not group:
            continue
        pred = statistics.mean(x[0] for x in group)
        actual = statistics.mean(x[1] for x in group)
        ece += len(group) / len(rows) * abs(pred-actual)
        curve.append({"lo": i/bins, "hi": (i+1)/bins, "n": len(group), "predicted": pred, "actual": actual})
    return {"n": len(rows), "brier": brier/len(rows), "log_loss": loss/len(rows), "ece": ece, "bins": curve}


def performance(bets, starting=0):
    compact = [{k: b.get(k) for k in ("id", "event_id", "status", "stake", "pnl", "p", "market_p", "ev", "odds", "closing_odds", "settled_at")} for b in bets]
    return copy.deepcopy(_cached_performance(json.dumps(compact, sort_keys=True), starting))


@lru_cache(maxsize=12)
def _cached_performance(encoded, starting):
    bets = json.loads(encoded)
    settled = [b for b in bets if b.get("status") in ("WON", "LOST", "VOID")]
    decisive = [b for b in settled if b["status"] != "VOID"]
    turnover = sum(b["stake"] for b in decisive)
    profit = sum(b["pnl"] for b in settled)
    equity, peak, drawdown = starting, starting, 0.0
    curve = [{"ts": None, "equity": starting, "expected": starting}]
    expected = starting
    for b in sorted(settled, key=lambda b: (b["settled_at"], b["id"])):
        equity += b["pnl"]
        if b["status"] != "VOID":
            expected += b["stake"] * b["ev"]
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak-equity)/peak if peak > 0 else 0)
        curve.append({"ts": b["settled_at"], "equity": equity, "expected": expected})
    paired = [b for b in decisive if b.get("closing_odds")]
    obs = [{"p": b["p"], "y": b["status"] == "WON"} for b in decisive]
    baseline = [{"p": b["market_p"], "y": b["status"] == "WON"} for b in decisive]
    roi_ci = None
    # Cluster bootstrap by event, not by correlated selections.
    if len({b["event_id"] for b in decisive}) >= 30:
        clusters = {}
        for b in decisive:
            t, v = clusters.get(b["event_id"], (0, 0))
            clusters[b["event_id"]] = (t+b["stake"], v+b["pnl"])
        vals, rng = list(clusters.values()), random.Random(421)
        sims = []
        for _ in range(1000):
            sampled = [rng.choice(vals) for _ in vals]
            sims.append(sum(v for _, v in sampled)/sum(t for t, _ in sampled))
        sims.sort()
        roi_ci = [sims[25], sims[974]]
    return {"bets": len(bets), "settled": len(settled), "decisive": len(decisive), "turnover": turnover,
            "profit": profit, "roi": profit/turnover if turnover else None, "roi_ci": roi_ci,
            "win_rate": sum(b["status"] == "WON" for b in decisive)/len(decisive) if decisive else None,
            "expected_win_rate": statistics.mean(b["p"] for b in decisive) if decisive else None,
            "average_ev": statistics.mean(b["ev"] for b in decisive) if decisive else None,
            "clv_n": len(paired), "clv": statistics.mean(clv(b["odds"], b["closing_odds"]) for b in paired) if paired else None,
            "drawdown": drawdown, "curve": curve, "calibration": calibration(obs), "baseline": calibration(baseline)}


def cashflow_curve(bets, deposits):
    events = [(d["created_at"], 0, d["amount"], 0, 0) for d in deposits]
    events += [(b["settled_at"], 1, 0, b["pnl"], b["stake"]*b["ev"] if b["status"] != "VOID" else 0)
               for b in bets if b["status"] in ("WON", "LOST", "VOID")]
    equity = expected = 0.0
    index = peak = 1.0
    dd = 0.0
    curve = []
    for ts, kind, flow, pnl, exp in sorted(events):
        if equity > 0 and pnl:
            index *= (equity+pnl)/equity
        equity += flow+pnl
        expected += flow+exp
        peak = max(peak,index)
        dd = max(dd,1-index/peak)
        curve.append({"ts": ts, "equity": equity, "expected": expected, "cashflow": flow})
    return {"curve": curve, "drawdown": dd}


def monte_carlo(bets, starting, runs=2000, seed=721):
    """Conditional scenario, not proof of edge. Event outcomes are mutually exclusive."""
    starting = number(starting, 0.01, 1e9)
    runs = int(number(runs, 100, 5000))
    if not bets:
        raise ValueError("Ingen registrerede vaeddemaal at simulere")
    groups = {}
    for b in bets:
        decimal(b["odds"])
        probability(b["p"])
        number(b["stake"], 0.01, starting)
        groups.setdefault(b["event_id"], []).append(b)
    for group in groups.values():
        if len({b["selection"] for b in group}) != len(group) or sum(b["p"] for b in group) > 1+1e-9:
            raise ValueError("Uforenelige sandsynligheder eller dublerede udfald i samme kamp")
    rng = random.Random(seed)
    finals, dds, streaks, paths = [], [], [], []
    for _ in range(runs):
        equity = peak = starting
        dd = losing = max_losing = 0
        path = [equity]
        for group in groups.values():
            total = sum(b["stake"] for b in group)
            scale = min(1, equity/total)
            x, accumulated, payout = rng.random(), 0.0, 0.0
            for b in group:
                previous = accumulated
                accumulated += b["p"]
                if previous <= x < accumulated:
                    payout = b["stake"]*scale*b["odds"]
            pnl = payout-total*scale
            equity = max(0, equity+pnl)
            peak = max(peak, equity)
            dd = max(dd, 1-equity/peak)
            losing = losing+1 if pnl < 0 else 0
            max_losing = max(max_losing, losing)
            path.append(equity)
        finals.append(equity)
        dds.append(dd)
        streaks.append(max_losing)
        paths.append(path)
    def percentile(values, p):
        return sorted(values)[int((len(values)-1)*p)]
    bands = [{"step": i, "p05": percentile([p[i] for p in paths], .05),
              "p50": percentile([p[i] for p in paths], .5), "p95": percentile([p[i] for p in paths], .95)}
             for i in range(len(groups)+1)]
    return {"runs": runs, "events": len(groups), "starting": starting,
            "median": percentile(finals, .5), "p05": percentile(finals, .05), "p95": percentile(finals, .95),
            "negative_probability": sum(v < starting for v in finals)/runs,
            "ruin_probability": sum(v < starting*.1 for v in finals)/runs,
            "drawdown_p95": percentile(dds, .95), "losing_streak_p95": percentile(streaks, .95),
            "bands": bands, "assumptions": "Faste indsatser; uafhaengige kampe; gensidigt udelukkende h2h-udfald. Ruin = under 10% af start. Modelfejl er ikke inkluderet."}
