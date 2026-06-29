"""
Bankroll & regnskab — den simulerede pulje og alt bogholderi.

Alt her sker med PAPER-penge. Ingen rigtige kroner bevæger sig. Tilstanden gemmes
i data/state.json, så puljen overlever genstart.

Hvad det gør pr. cyklus:
  1. Værdisæt og styr åbne markeds-positioner (hard stop / trailing stop).
  2. Hent nye muligheder, lad allokatoren fordele puljen, og udfør:
       - markeds-positioner åbnes (køber 'units' til nuværende pris).
       - sports-bets afregnes med det samme via et simuleret udfald.
  3. Opdatér equity-kurven og en NAIV baseline (= bare gamble tilfældigt),
     så vi kan måle om AI-tilgangen rent faktisk er klogere.

Sports afregnes mod markedets fair sandsynlighed (det bedste neutrale bud på
sandheden). Pointe: hvis AI'en ikke har ÆGTE edge, æder bookmakerens margin puljen
langsomt — præcis den lærdom du skal kunne se sort på hvidt, før rigtige penge.
"""
import os
import json
import time
import random

from . import markets
from . import sports
from . import allocator
from . import store
from . import strategy

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "state.json")


# ---------- tilstand ----------

def _default_state(starting: float) -> dict:
    return {
        "starting_bankroll": starting,
        "cash": starting,
        "positions": [],          # åbne markeds-positioner
        "history": [],            # lukkede positioner/bets
        "equity_curve": [],       # [{ts, equity}]
        "naive_baseline": starting,  # 'bare gamble' sammenligningspulje
        "naive_curve": [],
        "created": int(time.time()),
        "use_ai": False,
    }


def load_state() -> dict | None:
    return store.load(STATE_PATH)


def save_state(state: dict) -> None:
    store.save(STATE_PATH, state)


def reset(starting: float = 200.0, use_ai: bool = False) -> dict:
    state = _default_state(starting)
    state["use_ai"] = use_ai
    save_state(state)
    return state


# ---------- værdisætning ----------

def market_value(state: dict) -> float:
    """Aktuel kroneværdi af alle åbne markeds-positioner."""
    ids = [p["asset_id"] for p in state["positions"]]
    prices = markets.current_prices(ids)
    total = 0.0
    for p in state["positions"]:
        price = prices.get(p["asset_id"], p["entry_price"])
        total += p["units"] * price * (1 - strategy.FEE)
    return total


def equity(state: dict) -> float:
    """Samlet pulje-værdi = kontant + værdi af åbne positioner."""
    return state["cash"] + market_value(state)


# ---------- styring af åbne positioner ----------

def _manage_positions(state: dict) -> list[str]:
    """Tjek hard stop / trailing stop på åbne markeds-positioner. Returnér log-linjer."""
    log = []
    ids = [p["asset_id"] for p in state["positions"]]
    prices = markets.current_prices(ids)
    still_open = []
    for p in state["positions"]:
        price = prices.get(p["asset_id"], p["entry_price"])
        p["peak"] = max(p.get("peak", p["entry_price"]), price)
        should_exit, reason = strategy.should_exit(p["entry_price"], p["peak"], price)
        if should_exit:
            proceeds = p["units"] * price * (1 - strategy.FEE)
            pnl = proceeds - p["stake_dkk"]
            state["cash"] += proceeds
            state["history"].append({
                "type": "market", "name": p["name"], "stake": p["stake_dkk"],
                "pnl": round(pnl, 2), "reason": reason,
                "ts": int(time.time()),
            })
            log.append(f"Lukkede {p['name']}: {reason}, {pnl:+.2f} kr")
        else:
            still_open.append(p)
    state["positions"] = still_open
    return log


# ---------- udførsel af nye handlinger ----------

def _open_market(state: dict, action: dict) -> str:
    units = action["stake_dkk"] * (1 - strategy.FEE) / action["price"] if action["price"] else 0
    state["cash"] -= action["stake_dkk"]
    state["positions"].append({
        "asset_id": action["id"], "name": action["name"],
        "entry_price": action["price"], "peak": action["price"], "units": units,
        "stake_dkk": action["stake_dkk"], "ts": int(time.time()),
    })
    return f"Åbnede {action['name']}: {action['stake_dkk']:.2f} kr @ {action['price']:.2f}"


def _settle_sport(state: dict, action: dict) -> str:
    """
    Afregn et sports-bet med det samme via et simuleret udfald trukket fra
    markedets fair sandsynlighed for netop dette udfald.
    """
    state["cash"] -= action["stake_dkk"]
    won = random.random() < action["p_market"]   # neutralt, ærligt udfald
    if won:
        proceeds = action["stake_dkk"] * action["odds"]
        state["cash"] += proceeds
        pnl = proceeds - action["stake_dkk"]
    else:
        pnl = -action["stake_dkk"]
    state["history"].append({
        "type": "sport", "name": action["name"], "stake": action["stake_dkk"],
        "pnl": round(pnl, 2), "reason": "vandt" if won else "tabte",
        "ts": int(time.time()),
    })
    return f"Bet afregnet {action['name']}: {'VANDT' if won else 'tabte'} {pnl:+.2f} kr"


def _run_naive_baseline(state: dict, total_staked: float, api_key) -> None:
    """
    Sammenligningsgrundlag: 'bare gamble'. Satser samme samlede beløb som AI'en
    gjorde, på et HELT TILFÆLDIGT udfald til markedsodds. Over tid viser denne kurve
    hvad ren gambling giver — så du kan se om AI-tilgangen faktisk er bedre.
    """
    if total_staked <= 0 or state["naive_baseline"] <= 0:
        return
    matches = sports.fetch_matches(api_key)
    if not matches:
        return
    m = random.choice(matches)
    label = random.choice(["home", "draw", "away"])
    odds = m["odds"][label]
    fair = dict(zip(["home", "draw", "away"], kelly_fair(m)))
    stake = min(total_staked, state["naive_baseline"])
    state["naive_baseline"] -= stake
    if random.random() < fair[label]:
        state["naive_baseline"] += stake * odds


def kelly_fair(match: dict):
    from . import kelly
    odds = [match["odds"][k] for k in ["home", "draw", "away"]]
    return kelly.remove_vig(odds)


def diagnostics() -> dict:
    """Vis hvad simulatoren scanner, uden at udføre handler eller bruge AI-tokens."""
    state = load_state() or reset()
    api_key = os.environ.get("ODDS_API_KEY")
    market_diag = markets.inspect_opportunities()
    sports_diag = sports.inspect_opportunities(api_key, use_ai=state.get("use_ai", False))
    opps = markets.find_opportunities()
    # Brug kun faktiske sports-opps hvis AI ikke er nødvendig; ellers undgå tokenforbrug i diagnose.
    if not state.get("use_ai", False):
        opps += sports.find_opportunities(api_key, use_ai=False)
    actions = allocator.allocate(equity(state), opps)
    return {
        "use_ai": state.get("use_ai", False),
        "market": market_diag,
        "sports": sports_diag,
        "opportunities": len(opps),
        "actions": len(actions),
        "summary": [
            f"Krypto: scannede {market_diag['scanned']} aktiver, {market_diag['accepted']} signaler godkendt.",
            f"Sport: scannede {sports_diag['scanned']} kampe, {sports_diag['accepted']} value-signaler uden AI-diagnose.",
            f"Allokator: {len(actions)} handlinger ville blive udført med nuværende pulje.",
        ],
    }


# ---------- hoved-cyklus ----------

def run_cycle() -> dict:
    """Kør én fuld beslutnings-cyklus. Returnér et resumé til dashboardet."""
    with store.lock_for(STATE_PATH):
        return _run_cycle_locked()


def _run_cycle_locked() -> dict:
    state = load_state() or reset()
    api_key = os.environ.get("ODDS_API_KEY")
    log = []

    # 1) styr eksisterende positioner
    log += _manage_positions(state)

    # 2) find muligheder
    opps = []
    opps += markets.find_opportunities()
    opps += sports.find_opportunities(api_key, use_ai=state.get("use_ai", False))

    # 3) allokér på den NUVÆRENDE samlede pulje
    pool = equity(state)
    actions = allocator.allocate(pool, opps)

    # 4) udfør
    total_staked = 0.0
    for a in actions:
        if a["stake_dkk"] > state["cash"]:
            continue  # ikke nok kontant tilbage til denne handling
        if a["type"] == "market":
            log.append(_open_market(state, a))
        else:
            log.append(_settle_sport(state, a))
        total_staked += a["stake_dkk"]

    # 5) naiv baseline til sammenligning
    _run_naive_baseline(state, total_staked, api_key)

    # 6) opdatér kurver
    now = int(time.time())
    eq = equity(state)
    state["equity_curve"].append({"ts": now, "equity": round(eq, 2)})
    state["naive_curve"].append({"ts": now, "equity": round(state["naive_baseline"], 2)})
    # behold de seneste 500 punkter
    state["equity_curve"] = state["equity_curve"][-500:]
    state["naive_curve"] = state["naive_curve"][-500:]

    save_state(state)
    if not log:
        diag = diagnostics()
        log = ["Ingen handlinger denne cyklus (ingen muligheder med edge)."] + diag["summary"]
    return {
        "log": log,
        "actions": actions,
        "equity": round(eq, 2),
        "naive": round(state["naive_baseline"], 2),
    }
