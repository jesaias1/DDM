"""
Polymarket-scanner — KUN LÆSNING. Ingen wallet, ingen nøgler, ingen penge.

Polymarket er et prediction market med et offentligt API hvor bots er tilladt
(modsat bookmakere). Men auto-handel dér kræver en selv-forvaltet krypto-wallet
uden "trade-only"-adskillelse, og platformen har ingen dansk licens — derfor
bygger vi bevidst kun en SCANNER: den læser markedspriserne og lader AI-researchen
give sit eget sandsynlighedsbud. Ser du value og selv vil handle, gør du det
manuelt på polymarket.com. Samme filosofi som sport: motoren tænker, du trykker.

Value-logik: prisen på et udfald (0-1) ER markedets sandsynlighed. Decimal-odds
= 1/pris. AI-bud p vs markedspris -> value = p/pris - 1. Kelly som ved sport.
"""
import json

import requests

from . import kelly, research

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
MAX_MARKETS = 8          # top-N mest omsatte markeder (skåner AI-budgettet)
MIN_VOLUME_24H = 10000   # USD — kun likvide markeder (tynde priser = falsk value)
MIN_PRICE = 0.03         # udfald prissat <3% / >97% springes over (gebyr/støj æder alt)


def _parse_list(value) -> list:
    """Gamma-API'et sender lister som JSON-strenge ('["Yes","No"]')."""
    if isinstance(value, list):
        return value
    try:
        out = json.loads(value or "[]")
        return out if isinstance(out, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def fetch_markets() -> list[dict]:
    """Hent åbne, likvide markeder sorteret efter 24t-volumen. Tom liste ved fejl."""
    try:
        r = requests.get(GAMMA_URL, params={
            "closed": "false", "active": "true",
            "order": "volume24hr", "ascending": "false", "limit": 40,
        }, timeout=15)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        print(f"[polymarket] kunne ikke hente markeder: {e}")
        return []

    markets = []
    for m in raw if isinstance(raw, list) else []:
        outcomes = [str(o) for o in _parse_list(m.get("outcomes"))]
        prices = []
        for p in _parse_list(m.get("outcomePrices")):
            try:
                prices.append(float(p))
            except (TypeError, ValueError):
                prices.append(0.0)
        try:
            volume = float(m.get("volume24hr") or 0)
        except (TypeError, ValueError):
            volume = 0.0
        if (len(outcomes) < 2 or len(outcomes) != len(prices)
                or volume < MIN_VOLUME_24H
                or not 0.9 <= sum(prices) <= 1.1):
            continue
        markets.append({
            "id": str(m.get("id", "")),
            "question": str(m.get("question", "?")),
            "outcomes": outcomes,
            "prices": prices,
            "volume24h": volume,
        })
        if len(markets) >= MAX_MARKETS:
            break
    return markets


def find_opportunities(use_ai: bool = False) -> list[dict]:
    """
    Value-muligheder på tværs af de mest likvide markeder. Uden AI = markedets
    egne priser = ingen value (ærligt, som ved sport). AI-kald deler samme
    dagsbudget som sport-researchen.
    """
    opps = []
    for m in fetch_markets():
        total = sum(m["prices"])
        fair = [p / total for p in m["prices"]]  # normalisér spread væk
        if use_ai:
            our = research.estimate_probabilities({
                "id": f"pm-{m['id']}", "home": m["question"],
                "away": "(prediction market)", "sport": "Polymarket",
            }, fair, m["outcomes"])
        else:
            our = fair
        for name, p_market, p_ours in zip(m["outcomes"], fair, our):
            if not MIN_PRICE <= p_market <= 1 - MIN_PRICE:
                continue
            odds = 1.0 / p_market
            frac = kelly.binary_kelly(p_ours, odds)
            value = p_ours * odds - 1
            if frac <= 0 or value <= 1e-6:   # 1e-6: filtrér floating point-støj fra nul-edge
                continue
            opps.append({
                "type": "polymarket",
                "id": f"pm-{m['id']}:{name}",
                "sport": "Polymarket",
                "name": f"{m['question']} — {name}",
                "odds": round(odds, 2),
                "p_market": p_market,
                "p_ours": p_ours,
                "kelly_fraction": frac,
                "value": value,
                "reason": (f"Vind {p_ours*100:.1f}% (marked {p_market*100:.1f}%) "
                           f"@ {odds:.2f} · value {value*100:+.1f}% · vol ${m['volume24h']:,.0f}"),
            })
    opps.sort(key=lambda x: x["value"], reverse=True)
    return opps
