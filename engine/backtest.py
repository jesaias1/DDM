"""
Backtest — kør strategien over mange simulerede dage på sekunder.

Hvorfor: på live-data sker der ofte ingenting i en enkelt cyklus (intet edge =
intet bet — som det skal være). Men så kan du ikke SE om tilgangen virker. Backtesten
genererer realistiske syntetiske prisforløb (momentum + støj) og kører PRÆCIS samme
logik — momentum-signal → kontinuert Kelly → allokering — dag for dag, side om side
med en naiv "bare gamble"-baseline.

Det er den ærligste test du har: over hundredvis af dage ser du om momentum-Kelly
faktisk ligger over ren gambling, eller om begge bare driver nedad. Husk: syntetiske
data beviser ikke noget om de RIGTIGE markeder — det viser strategiens opførsel og
risikoprofil, ikke en garanti for fremtidigt afkast.
"""
import random
import statistics
from . import allocator, strategy


# Handelsfriktion pr. handel (spread + gebyr), én vej.
TRADE_COST = strategy.FEE


def _gen_price_path(days: int, drift: float, vol: float, rng: random.Random) -> list[float]:
    """
    Geometrisk random walk. Bevidst tæt på en 'martingale': drift er nær nul og
    momentum-hukommelsen er SVAG (0.15), så der kun er en tynd, ustabil edge at
    fange — som i virkelige markeder. Ingen indbygget gevinst-bias.
    """
    price = 100.0
    path = [price]
    shock = 0.0
    for _ in range(days):
        shock = 0.15 * shock + rng.gauss(drift, vol)  # kun svag autokorrelation
        price *= (1 + shock)
        path.append(max(price, 0.01))
    return path


def run(days: int = 200, n_assets: int = 5, seed: int | None = None,
        starting: float = 200.0) -> dict:
    rng = random.Random(seed)
    # blanding af aktiver: nogle med ægte trend, nogle ren støj — som virkeligheden
    assets = []
    for i in range(n_assets):
        drift = rng.uniform(-0.0015, 0.0015)  # centreret om nul: ingen gratis medvind
        vol = rng.uniform(0.03, 0.08)
        assets.append({"name": f"A{i+1}", "path": _gen_price_path(days, drift, vol, rng)})

    cash = starting
    positions = []          # {name, idx, entry, peak, units, stake}
    cooldowns = {}
    ai_curve, naive_curve = [], []
    naive = starting

    for d in range(1, days):
        # --- styr åbne positioner (hard stop / trailing stop) ---
        still = []
        for p in positions:
            price = assets[p["idx"]]["path"][d]
            p["peak"] = max(p.get("peak", p["entry"]), price)
            should_exit, _ = strategy.should_exit(p["entry"], p["peak"], price)
            if should_exit:
                cash += p["units"] * price * (1 - TRADE_COST)  # salgs-friktion
                cooldowns[p["name"]] = d + max(1, strategy.COOLDOWN_SECONDS // (24 * 60 * 60))
            else:
                still.append(p)
        positions = still
        cooldowns = {name: until for name, until in cooldowns.items() if until > d}
        held = {p["name"] for p in positions}

        # --- byg muligheder fra de seneste prisbevægelser ---
        opps = []
        for idx, a in enumerate(assets):
            if a["name"] in held or a["name"] in cooldowns or d < strategy.TREND_LEN:
                continue
            sig = strategy.momentum_signal(a["path"][:d + 1])
            if not sig:
                continue
            opps.append({"type": "market", "id": a["name"], "name": a["name"],
                         "price": a["path"][d], "expected_return": sig["expected_return"],
                         "volatility": sig["volatility"]})

        equity = cash + sum(p["units"] * assets[p["idx"]]["path"][d] for p in positions)
        for act in allocator.allocate(equity, opps):
            if act["stake_dkk"] > cash:
                continue
            idx = next(i for i, a in enumerate(assets) if a["name"] == act["id"])
            units = act["stake_dkk"] * (1 - TRADE_COST) / act["price"]  # købs-friktion
            cash -= act["stake_dkk"]
            positions.append({"name": act["name"], "idx": idx, "entry": act["price"],
                              "peak": act["price"], "units": units, "stake": act["stake_dkk"]})

        equity = cash + sum(p["units"] * assets[p["idx"]]["path"][d] for p in positions)
        ai_curve.append(round(equity, 2))

        # --- naiv baseline: gamble 10% af puljen på et udfald til odds med 6% margin ---
        if naive > 5:
            stake = naive * 0.10
            # fair p ~ 0.5, men bookmaker betaler kun som om p=0.53 (margin) -> negativ EV
            naive -= stake
            if rng.random() < 0.50:
                naive += stake * (1 / 0.53)   # odds ~1.89
        naive_curve.append(round(naive, 2))

    return {
        "days": days,
        "ai_curve": ai_curve,
        "naive_curve": naive_curve,
        "ai_final": ai_curve[-1] if ai_curve else starting,
        "naive_final": naive_curve[-1] if naive_curve else starting,
        "ai_return_pct": round((ai_curve[-1] / starting - 1) * 100, 1) if ai_curve else 0.0,
        "naive_return_pct": round((naive_curve[-1] / starting - 1) * 100, 1) if naive_curve else 0.0,
        "starting": starting,
    }


def run_many(days: int = 200, runs: int = 200, starting: float = 200.0) -> dict:
    """
    Kør MANGE simulationer (faste seeds 0..runs-1) og returnér FORDELINGEN.

    Hvorfor: én enkelt backtest bruger tilfældige priser, så den skifter hver gang
    og ligner "random tal". Ved at køre fx 200 forløb med faste seeds får vi et
    STABILT, meningsfuldt billede — samme resultat hver gang — der viser hvor ofte
    strategien kommer i plus, medianen, og hvor slemt/godt det kan gå.

    Vi viser også ét repræsentativt forløb (det tættest på medianen), så grafen
    matcher overskriftstallet.
    """
    results = []  # (ai_return_pct, naive_return_pct, run_dict)
    for seed in range(max(1, runs)):
        r = run(days=days, seed=seed, starting=starting)
        results.append((r["ai_return_pct"], r["naive_return_pct"], r))

    ai_returns = [x[0] for x in results]
    naive_returns = [x[1] for x in results]
    ai_median = statistics.median(ai_returns)
    # repræsentativt forløb: det hvis AI-afkast er tættest på medianen
    representative = min(results, key=lambda x: abs(x[0] - ai_median))[2]

    return {
        "runs": len(results),
        "days": days,
        "starting": starting,
        "ai_median_pct": round(ai_median, 1),
        "ai_win_rate": round(sum(1 for x in ai_returns if x > 0) / len(ai_returns) * 100),
        "ai_best_pct": round(max(ai_returns), 1),
        "ai_worst_pct": round(min(ai_returns), 1),
        "naive_median_pct": round(statistics.median(naive_returns), 1),
        "naive_win_rate": round(sum(1 for x in naive_returns if x > 0) / len(naive_returns) * 100),
        # ét repræsentativt forløb til grafen
        "ai_curve": representative["ai_curve"],
        "naive_curve": representative["naive_curve"],
    }
