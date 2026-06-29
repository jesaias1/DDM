"""
Sports-modul: value-betting delen.

Idéen om "AI klogere end at gamble" lever og dør her, så lad os være ærlige om
hvordan det virker:

1. Bookmakeren tilbyder odds. De implicitte sandsynligheder summer til MERE end
   100% — overskuddet er deres margin ('vig'), typisk 5-8%. Det er huset-fordelen.
2. Vi fjerner margin og får markedets 'fair' sandsynligheder.
3. For at finde VALUE skal vi have et UAFHÆNGIGT estimat af sandsynligheden, der
   afviger fra markedet. Hvis vores estimat bare kopierer markedet, er edge = 0.

Den ærlige sandhed: at slå bookmakerne konsekvent kræver en rigtig prædiktiv model
(skader, form, xG, line-bevægelser ...). Dette modul giver RAMMEN og en plads til
den model (`estimate_probabilities`). Som standard bruger den en gennemsigtig
baseline der IKKE foregiver at have edge, så du ikke bliver narret.

Med en gratis nøgle fra the-odds-api.com henter den ægte live-odds. Uden nøgle
kører den på demo-kampe, så hele maskineriet kan testes.
"""
import requests
from . import kelly
from . import research

ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"

# Demo-kampe så modulet virker uden API-nøgle. Realistiske odds med ~6% margin.
DEMO_MATCHES = [
    {"id": "demo-1", "home": "FC København", "away": "Brøndby",
     "odds": {"home": 2.10, "draw": 3.40, "away": 3.60}},
    {"id": "demo-2", "home": "Manchester City", "away": "Arsenal",
     "odds": {"home": 1.85, "draw": 3.70, "away": 4.20}},
    {"id": "demo-3", "home": "Real Madrid", "away": "Barcelona",
     "odds": {"home": 2.40, "draw": 3.50, "away": 2.90}},
]


def fetch_matches(api_key: str | None, sport: str = "soccer_epl") -> list[dict]:
    """Hent live-kampe med odds, eller demo-kampe hvis ingen nøgle er sat."""
    if not api_key:
        return DEMO_MATCHES
    try:
        params = {"apiKey": api_key, "regions": "eu", "markets": "h2h",
                  "oddsFormat": "decimal"}
        r = requests.get(ODDS_API_URL.format(sport=sport), params=params, timeout=15)
        r.raise_for_status()
        matches = []
        for ev in r.json():
            if not ev.get("bookmakers"):
                continue
            outcomes = ev["bookmakers"][0]["markets"][0]["outcomes"]
            by_name = {o["name"]: o["price"] for o in outcomes}
            home, away = ev["home_team"], ev["away_team"]
            matches.append({
                "id": ev["id"], "home": home, "away": away,
                "odds": {"home": by_name.get(home, 0),
                         "draw": by_name.get("Draw", 0),
                         "away": by_name.get(away, 0)},
            })
        return matches
    except Exception as e:
        print(f"[sports] kunne ikke hente odds, bruger demo: {e}")
        return DEMO_MATCHES


def find_opportunities(api_key: str | None = None,
                       use_ai: bool = False) -> list[dict]:
    """
    Find value-bets på tværs af kampe. For hvert udfald:
      - markedets fair sandsynlighed (vig fjernet)
      - VORES estimerede sandsynlighed (baseline = marked; eller AI hvis aktiveret)
      - Kelly-andel ud fra forskellen
    Kun udfald med positiv Kelly (ægte value) returneres.
    """
    opps = []
    for m in fetch_matches(api_key):
        labels = ["home", "draw", "away"]
        odds = [m["odds"][k] for k in labels]
        if any(o <= 0 for o in odds):
            continue
        fair = kelly.remove_vig(odds)  # markedets bedste bud på sandhed

        # VORES sandsynlighed. Baseline = marked (=> ingen falsk edge).
        # Med AI-research slået til får vi et uafhængigt, web-researchet estimat.
        our_probs = research.estimate_probabilities(m, fair) if use_ai else fair

        for label, p_market, p_ours, o in zip(labels, fair, our_probs, odds):
            frac = kelly.binary_kelly(p_ours, o)
            if frac <= 0:
                continue
            pick = {"home": m["home"], "draw": "Uafgjort", "away": m["away"]}[label]
            opps.append({
                "type": "sport",
                "id": f"{m['id']}:{label}",
                "name": f"{m['home']} vs {m['away']} — {pick}",
                "odds": o,
                "p_market": p_market,
                "p_ours": p_ours,
                "kelly_fraction": frac,
                "reason": (f"Marked: {p_market*100:.1f}% | Vores: {p_ours*100:.1f}% "
                           f"@ odds {o:.2f}. Value = "
                           f"{(p_ours*o - 1)*100:+.1f}%."),
            })
    return opps


def inspect_opportunities(api_key: str | None = None,
                          use_ai: bool = False) -> dict:
    """
    Diagnostik uden at bruge AI-tokens. Viser hvorfor sport typisk giver 0 edge
    uden AI: baseline bruger markedets fair sandsynligheder, så Kelly bliver 0.
    """
    matches = fetch_matches(api_key)
    items = []
    for m in matches:
        labels = ["home", "draw", "away"]
        odds = [m["odds"][k] for k in labels]
        if any(o <= 0 for o in odds):
            items.append({
                "name": f"{m['home']} vs {m['away']}",
                "accepted": False,
                "reason": "afvist: mangler komplette odds",
            })
            continue
        fair = kelly.remove_vig(odds)
        items.append({
            "name": f"{m['home']} vs {m['away']}",
            "accepted": False,
            "reason": ("ingen value uden uafhængigt estimat: baseline bruger markedets fair "
                       f"sandsynligheder ({fair[0]*100:.1f}%/{fair[1]*100:.1f}%/{fair[2]*100:.1f}%)"),
        })
    return {
        "source": "The Odds API" if api_key else "demo-odds",
        "scanned": len(matches),
        "accepted": 0,
        "ai_enabled": bool(use_ai),
        "note": "AI-scouting kan skabe et uafhængigt estimat, men denne diagnose bruger ingen AI-tokens.",
        "items": items,
    }
