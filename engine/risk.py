"""Worst-case exposure caps; same-event bets never get independence credit."""
from dataclasses import dataclass, asdict
import math

from . import quant


@dataclass(frozen=True)
class Limits:
    kelly_fraction: float = .25
    per_bet: float = .01
    per_event: float = .02
    per_team: float = .03
    per_sport: float = .05
    per_league: float = .04
    daily: float = .05
    simultaneous: float = .10
    min_stake: float = .10
    min_ev: float = .02
    max_open_bets: int = 100

    def as_dict(self):
        return asdict(self)


PROFILES = {
    "conservative": Limits(),
    "balanced": Limits(kelly_fraction=.25, per_bet=.015, per_event=.025, daily=.075, simultaneous=.15),
    "aggressive": Limits(kelly_fraction=.5, per_bet=.02, per_event=.03, daily=.10, simultaneous=.20),
}


def propose(opportunity, account, bets, event_map, limits=None, now=None):
    import time
    limits = limits or PROFILES["conservative"]
    now = time.time() if now is None else now
    equity, cash = account["equity"], account["cash"]
    if account["halted"]:
        return 0.0, "Global handelsstop er aktivt"
    if equity <= 0 or cash <= 0:
        return 0.0, "Ingen disponibel pulje"
    event_id = opportunity["event_id"]
    current = event_map.get(event_id, {})
    teams = {current.get("home"), current.get("away")}-{None}
    opened = [b for b in bets if b["status"] == "OPEN"]
    if len(opened) >= limits.max_open_bets:
        return 0.0, "Maksimalt antal aabne vaeddemaal er naaet"
    day_start = math.floor(now/86400)*86400  # fixed UTC accounting day
    daily = sum(b["stake"] for b in bets if b["placed_at"] >= day_start)
    if any(b["event_id"] == event_id and b["selection"] == opportunity["selection"] and b["market"] == "h2h" for b in bets):
        return 0.0, "Dette kampudfald er allerede registreret"
    def exposure(predicate):
        return sum(b["stake"] for b in opened if predicate(b))
    raw = equity * quant.kelly(opportunity["p_lower"], opportunity["odds"], limits.kelly_fraction)
    caps = [raw, equity*limits.per_bet, cash,
            equity*limits.simultaneous-exposure(lambda b: True), equity*limits.daily-daily,
            equity*limits.per_event-exposure(lambda b: b["event_id"] == event_id),
            equity*limits.per_sport-exposure(lambda b: b["sport"] == opportunity["sport"]),
            equity*limits.per_league-exposure(lambda b: b["league"] == opportunity["league"])]
    for team in teams:
        caps.append(equity*limits.per_team-exposure(lambda b: team in {event_map.get(b["event_id"], {}).get("home"), event_map.get(b["event_id"], {}).get("away")}))
    stake = math.floor(max(0, min(caps))*100+1e-8)/100
    if stake < limits.min_stake:
        return 0.0, "Kelly eller eksponeringsloft giver indsats under minimum"
    return stake, "Fraktioneret Kelly paa konservativ p; kamp-, hold-, liga-, sport-, dags- og portefoljeloft"
