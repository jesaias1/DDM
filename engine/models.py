"""Versioned experimental football Poisson baseline; market reference elsewhere."""
import hashlib
import math
import statistics

from . import database, quant

VERSION = "poisson-shrink-1"
FEATURE_VERSION = "goals-home-away-decay180-prior20-1"


def football_probabilities(home, away, history, as_of):
    try:
        from scipy.stats import poisson
    except ImportError:
        return None
    rows = [r for r in history if r["available_at"] < as_of and r["start"] < as_of]
    home_rows = [r for r in rows if r["home"] == home]
    away_rows = [r for r in rows if r["away"] == away]
    if len(rows) < 100 or min(len(home_rows), len(away_rows)) < 15:
        return None
    weights = [math.exp(-math.log(2)*(as_of-r["start"])/(180*86400)) for r in rows]
    total = sum(weights)
    league_h = sum(r["home_goals"]*w for r, w in zip(rows, weights))/total
    league_a = sum(r["away_goals"]*w for r, w in zip(rows, weights))/total
    if min(league_h, league_a) <= 0:
        return None
    def average(subset, field, prior):
        ws = [math.exp(-math.log(2)*(as_of-r["start"])/(180*86400)) for r in subset]
        return (sum(r[field]*w for r, w in zip(subset, ws))+20*prior)/(sum(ws)+20)
    lambda_h = average(home_rows, "home_goals", league_h)*average(away_rows, "home_goals", league_h)/league_h
    lambda_a = average(away_rows, "away_goals", league_a)*average(home_rows, "away_goals", league_a)/league_a
    # scipy supplies the PMF; extend the grid until omitted tail mass is negligible.
    top = max(12, int(poisson.ppf(1-1e-10, max(lambda_h, lambda_a))))
    hp, ap = poisson.pmf(range(top+1), lambda_h), poisson.pmf(range(top+1), lambda_a)
    probs = {"HOME": 0.0, "DRAW": 0.0, "AWAY": 0.0}
    for h in range(top+1):
        for a in range(top+1):
            probs["HOME" if h > a else "AWAY" if a > h else "DRAW"] += float(hp[h]*ap[a])
    norm = sum(probs.values())
    probs = {key: value/norm for key, value in probs.items()}
    return {"probabilities": probs, "sample": len(rows), "team_sample": min(len(home_rows), len(away_rows)),
            "model_version": VERSION, "feature_version": FEATURE_VERSION,
            "data_version": hashlib.sha256(database.dumps(rows).encode()).hexdigest(),
            "calibration_version": "none", "validated": False,
            "inputs": {"home_lambda": lambda_h, "away_lambda": lambda_a, "as_of": as_of,
                       "last_result_available": max(r["available_at"] for r in rows)}}


def estimate(event, reference_books, history):
    selections = event["selections"]
    vectors, sensitivity = [], []
    for book in reference_books:
        odds = [book["prices"][s] for s in selections]
        vectors.append(quant.no_vig(odds, "power"))
        for method in ("power", "proportional", "shin"):
            try:
                sensitivity.append(quant.no_vig(odds, method))
            except ValueError:
                pass
    if not vectors:
        return None
    means = [statistics.mean(v[i] for v in vectors) for i in range(len(selections))]
    independent = football_probabilities(event["home"], event["away"], history, event["received_at"]) if event["sport"].startswith("soccer_") else None
    if independent:
        predicted = [independent["probabilities"][s] for s in selections]
        version = independent["model_version"]
    else:
        predicted = means
        version = "leave-book-out-power-1"
    outputs = {}
    for i, s in enumerate(selections):
        # A sensitivity buffer, NOT a statistical confidence interval.
        spread = max(abs(v[i]-means[i]) for v in sensitivity)
        uncertainty = max(.025, spread, abs(predicted[i]-means[i])*.5 if independent else 0)
        outputs[s] = {"p": predicted[i], "market_p": means[i],
                      "p_lower": max(0.001, predicted[i]-uncertainty), "uncertainty": uncertainty}
    return {"outputs": outputs, "model_version": version, "feature_version": FEATURE_VERSION if independent else "complete-h2h-1",
            "calibration_version": "none", "validated": False,
            "sample": independent["sample"] if independent else 0,
            "data_version": independent["data_version"] if independent else hashlib.sha256(database.dumps(reference_books).encode()).hexdigest(),
            "inputs": independent["inputs"] if independent else {"reference_books": [b["key"] for b in reference_books], "method": "power"},
            "basis": "Poisson paa historiske maal" if independent else "Markedskonsensus uden den tilbudsgivende bookmaker"}
