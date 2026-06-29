"""
Sports-modul: value-betting på tværs af ALLE sportsgrene (fodbold, tennis,
basket, e-sport ...). Placerer ALDRIG et væddemål — det giver kun anbefalinger.

Sådan virker value:
1. Bookmakeren tilbyder odds. De implicitte sandsynligheder summer til MERE end
   100% — overskuddet er deres margin ('vig'). Det er huset-fordelen.
2. Vi fjerner margin og får markedets 'fair' sandsynligheder.
3. For at finde VALUE skal vi have et UAFHÆNGIGT estimat (AI-research) der afviger
   fra markedet. Uden AI = baseline = marked = ingen value (med vilje, så du ikke
   bliver narret).

Kampe kan have 2 udfald (tennis/e-sport/basket) eller 3 (fodbold m. uafgjort) —
begge håndteres. Anbefalinger sorteres efter bedste value (kombination af odds og
vind-%).

DDM_SPORT styrer hvad der scannes:
  "all"                      -> alle aktive sportsgrene fra the-odds-api
  "soccer_epl,tennis_atp"    -> en komma-liste af konkrete keys
  "soccer_fifa_world_cup"    -> én enkelt key
Standard: "all".
"""
import os
import requests
from . import kelly
from . import research

ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
SPORTS_LIST_URL = "https://api.the-odds-api.com/v4/sports"
DEFAULT_SPORT = os.environ.get("DDM_SPORT", "all")

# Lofter (beskytter din the-odds-api kvote og dit AI-tokenbudget).
MAX_SPORTS = int(os.environ.get("DDM_MAX_SPORTS", "40"))
MAX_MATCHES = int(os.environ.get("DDM_MAX_MATCHES", "60"))
MAX_AI_MATCHES = int(os.environ.get("DDM_MAX_AI_MATCHES", "15"))

# Demo-kampe (uden API-nøgle): viser med vilje flere sportsgrene, inkl. 2-vejs.
DEMO_MATCHES = [
    {"id": "demo-1", "sport": "fodbold (demo)", "home": "FC København", "away": "Brøndby",
     "outcomes": [{"name": "FC København", "price": 2.10}, {"name": "Uafgjort", "price": 3.40},
                  {"name": "Brøndby", "price": 3.60}]},
    {"id": "demo-2", "sport": "e-sport (demo)", "home": "Team Liquid", "away": "FaZe",
     "outcomes": [{"name": "Team Liquid", "price": 1.75}, {"name": "FaZe", "price": 2.05}]},
    {"id": "demo-3", "sport": "tennis (demo)", "home": "Alcaraz", "away": "Sinner",
     "outcomes": [{"name": "Alcaraz", "price": 1.90}, {"name": "Sinner", "price": 1.90}]},
]


def list_sports(api_key: str) -> list[str]:
    """Hent aktive sport-keys fra the-odds-api."""
    try:
        r = requests.get(SPORTS_LIST_URL, params={"apiKey": api_key}, timeout=15)
        r.raise_for_status()
        return [s["key"] for s in r.json() if s.get("active")]
    except Exception as e:
        print(f"[sports] kunne ikke hente sportsliste: {e}")
        return [DEFAULT_SPORT if DEFAULT_SPORT != "all" else "soccer_epl"]


def _sport_keys(api_key: str | None) -> list[str]:
    raw = (os.environ.get("DDM_SPORT", DEFAULT_SPORT) or "all").strip()
    if not api_key:
        return ["demo"]
    if raw.lower() == "all":
        return list_sports(api_key)[:MAX_SPORTS]
    return [s.strip() for s in raw.split(",") if s.strip()]


def fetch_matches(api_key: str | None, sport: str) -> list[dict]:
    """Hent kampe for ÉN sport-key. Udfald gemmes generisk (2 eller 3)."""
    try:
        params = {"apiKey": api_key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"}
        r = requests.get(ODDS_API_URL.format(sport=sport), params=params, timeout=15)
        r.raise_for_status()
        matches = []
        for ev in r.json():
            if not ev.get("bookmakers"):
                continue
            try:
                raw = ev["bookmakers"][0]["markets"][0]["outcomes"]
            except (KeyError, IndexError):
                continue
            outcomes = [{"name": o.get("name", "?"), "price": float(o.get("price", 0) or 0)} for o in raw]
            if len(outcomes) < 2:
                continue
            matches.append({
                "id": ev.get("id", ""), "sport": sport,
                "home": ev.get("home_team", outcomes[0]["name"]),
                "away": ev.get("away_team", outcomes[-1]["name"]),
                "outcomes": outcomes,
            })
        return matches
    except Exception as e:
        print(f"[sports] {sport}: kunne ikke hente odds: {e}")
        return []


def fetch_all_matches(api_key: str | None) -> list[dict]:
    """Saml kampe på tværs af alle valgte sportsgrene (op til MAX_MATCHES)."""
    if not api_key:
        return DEMO_MATCHES
    out = []
    for key in _sport_keys(api_key):
        for m in fetch_matches(api_key, key):
            out.append(m)
            if len(out) >= MAX_MATCHES:
                return out
    return out


def find_opportunities(api_key: str | None = None, use_ai: bool = False) -> list[dict]:
    """
    Scan alle kampe og returnér value-bets, sorteret efter bedste value (kombination
    af odds og vind-%). Uden AI = baseline = marked = ingen value (med vilje).
    """
    opps = []
    ai_used = 0
    for m in fetch_all_matches(api_key):
        outcomes = m.get("outcomes", [])
        prices = [o["price"] for o in outcomes]
        if len(prices) < 2 or any(p <= 0 for p in prices):
            continue
        fair = kelly.remove_vig(prices)

        if use_ai and ai_used < MAX_AI_MATCHES:
            our = research.estimate_probabilities(m, fair, [o["name"] for o in outcomes])
            ai_used += 1
        else:
            our = fair

        for o, p_market, p_ours in zip(outcomes, fair, our):
            frac = kelly.binary_kelly(p_ours, o["price"])
            if frac <= 0:
                continue
            value = p_ours * o["price"] - 1
            opps.append({
                "type": "sport",
                "id": f"{m['id']}:{o['name']}",
                "sport": m.get("sport", ""),
                "name": f"{m['home']} vs {m['away']} — {o['name']}",
                "odds": o["price"],
                "p_market": p_market,
                "p_ours": p_ours,
                "kelly_fraction": frac,
                "value": value,
                "reason": (f"Vind {p_ours*100:.1f}% (marked {p_market*100:.1f}%) "
                           f"@ odds {o['price']:.2f} · value {value*100:+.1f}%"),
            })
    opps.sort(key=lambda x: x["value"], reverse=True)
    return opps


def inspect_opportunities(api_key: str | None = None, use_ai: bool = False) -> dict:
    """Diagnostik uden AI-tokens: viser hvorfor sport giver 0 value uden AI."""
    matches = fetch_all_matches(api_key)
    items = []
    for m in matches[:20]:
        prices = [o["price"] for o in m.get("outcomes", [])]
        if len(prices) < 2 or any(p <= 0 for p in prices):
            items.append({"name": f"{m['home']} vs {m['away']}", "accepted": False,
                          "reason": "afvist: mangler komplette odds"})
            continue
        fair = kelly.remove_vig(prices)
        items.append({
            "name": f"{m['home']} vs {m['away']} ({m.get('sport','')})",
            "accepted": False,
            "reason": ("ingen value uden uafhængigt estimat: baseline = marked "
                       f"({'/'.join(f'{p*100:.0f}%' for p in fair)})"),
        })
    return {
        "source": "The Odds API" if api_key else "demo-odds",
        "scanned": len(matches),
        "accepted": 0,
        "ai_enabled": bool(use_ai),
        "note": "AI-scouting kan skabe et uafhængigt estimat; denne diagnose bruger ingen AI-tokens.",
        "items": items,
    }
