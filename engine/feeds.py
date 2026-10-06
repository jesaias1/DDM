"""Validated h2h ingestion. No silent demo fallback on live provider failures."""
import hashlib
import time
import unicodedata
from datetime import datetime, timezone

import requests

from . import quant, database

BASE = "https://api.the-odds-api.com/v4/sports"
MAX_AGE = 300
EXCHANGE_BOOKS = {"betfair_ex_eu", "betfair_ex_uk", "betfair_ex_au", "matchbook", "betfair"}


def timestamp(value):
    if isinstance(value, (int, float)):
        return quant.number(value, 1)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Tidszone mangler")
        return dt.astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        raise ValueError("Et UTC-tidspunkt med tidszone er paakraevet") from None


def label(value):
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def normalize(raw, received_at, mode):
    if mode not in ("DEMO", "PAPER", "REAL"):
        raise ValueError("Ugyldig datatilstand")
    event_id = str(raw.get("id", "")).strip()
    home, away = str(raw.get("home_team", "")).strip(), str(raw.get("away_team", "")).strip()
    if not event_id or not home or not away or label(home) == label(away):
        raise ValueError("Ugyldig kampidentitet")
    sport = str(raw.get("sport_key", ""))
    if not sport:
        raise ValueError("Sport mangler")
    start = timestamp(raw.get("commence_time"))
    expected = {"HOME", "AWAY", "DRAW"} if sport.startswith("soccer_") else {"HOME", "AWAY"}
    mapping = {label(home): "HOME", label(away): "AWAY", "draw": "DRAW"}
    books, rejected, seen = [], [], set()
    for book in raw.get("bookmakers", []):
        key = str(book.get("key", ""))
        if not key or key in seen:
            rejected.append({"book": key, "reason": "Dubleret eller manglende bookmaker"})
            continue
        seen.add(key)
        if key in EXCHANGE_BOOKS:
            rejected.append({"book": key, "reason": "Exchange-kommission og likviditet er ikke modelleret"})
            continue
        h2h = [m for m in book.get("markets", []) if m.get("key") == "h2h"]
        if len(h2h) != 1:
            rejected.append({"book": key, "reason": "Mangler entydigt h2h-marked"})
            continue
        market = h2h[0]
        try:
            updated = timestamp(market.get("last_update") or book.get("last_update"))
            if updated > received_at+5:
                raise ValueError("Odds er tidsstemplet i fremtiden")
            prices = {}
            for outcome in market.get("outcomes", []):
                selection = mapping.get(label(outcome.get("name", "")))
                if selection not in expected or selection in prices or "point" in outcome:
                    raise ValueError("Ukendt eller dubleret udfald")
                prices[selection] = quant.decimal(outcome.get("price"))
            if set(prices) != expected:
                raise ValueError("Ukomplet marked")
            margin = sum(1/o for o in prices.values())-1
            if not -0.001 <= margin <= .25:
                raise ValueError("Mistaenkelig margin; markedet saettes i karantaene")
            books.append({"key": key, "title": str(book.get("title", key)), "updated_at": updated,
                          "prices": prices, "margin": margin, "status": "FRESH" if received_at-updated <= MAX_AGE else "STALE"})
        except ValueError as error:
            rejected.append({"book": key, "reason": str(error)})
    if not books:
        raise ValueError("Ingen komplette, gyldige h2h-priser")
    return {"id": event_id, "sport": sport, "league": str(raw.get("sport_title", sport)),
            "home": home, "away": away, "start": start, "mode": mode,
            "received_at": received_at, "source": "deterministic-demo" if mode == "DEMO" else "the-odds-api",
            "market": "h2h", "selections": sorted(expected), "books": books, "rejected": rejected}


def demo_events(now=None):
    now = time.time() if now is None else now
    day = int(now//86400)
    fixtures = [
        ("soccer_denmark_superliga", "Superliga", "FC København", "Brøndby", [2.02, 3.55, 3.8], 2.38),
        ("soccer_epl", "Premier League", "Arsenal", "Liverpool", [2.1, 3.6, 3.5], 2.14),
        ("tennis_atp", "ATP", "Alcaraz", "Sinner", [1.88, 1.96], 2.17),
        ("soccer_spain_la_liga", "La Liga", "Real Madrid", "Barcelona", [2.0, 3.8, 3.65], 2.03),
        ("basketball_nba", "NBA", "Boston Celtics", "Denver Nuggets", [1.85, 2.02], 2.07),
    ]
    result = []
    for i, (sport, league, home, away, prices, offered) in enumerate(fixtures):
        names = [home, "Draw", away] if len(prices) == 3 else [home, away]
        books = []
        for j, key in enumerate(["reference_a", "reference_b", "reference_c", "demo_book"]):
            values = [round(p*(1+(j-1)*.003), 2) for p in prices]
            if j == 3:
                values[0] = offered
                # Preserve a complete positive-margin market even when one price is generous.
                values[-1] = round(values[-1]*.83, 2)
            books.append({"key": key, "title": ["Reference A", "Reference B", "Reference C", "Demo Book"][j],
                          "last_update": now-25-j*4 if i != 4 else now-800,
                          "markets": [{"key": "h2h", "outcomes": [{"name": n, "price": p} for n, p in zip(names, values)]}]})
        result.append(normalize({"id": f"demo-{day}-{i+1}", "home_team": home, "away_team": away,
                                 "sport_key": sport, "sport_title": league, "commence_time": (day+1)*86400+3600*(i+2),
                                 "bookmakers": books}, now, "DEMO"))
    return result


def _status(ok, now, message, latency, remaining=None):
    from .observability import emit
    emit("odds_feed", ok=ok, latency_ms=round(latency), remaining=remaining)
    with database.connection(write=True) as db:
        db.execute("""INSERT INTO provider_status(provider,ok,last_attempt,last_success,message,remaining,latency_ms)
                      VALUES('odds',?,?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET
                      ok=excluded.ok,last_attempt=excluded.last_attempt,
                      last_success=COALESCE(excluded.last_success,provider_status.last_success),
                      message=excluded.message,remaining=excluded.remaining,latency_ms=excluded.latency_ms""",
                   (int(ok), now, now if ok else None, message, remaining, latency))
        if not ok:
            database.alert(db, "PAPER", "provider-failure", message, "error", now)


def fetch_live(api_key, sport_keys):
    if not api_key:
        raise ValueError("The Odds API-noegle mangler. Vaelg DEMO eller tilfoej en noegle.")
    now, timer, out, rejected = time.time(), time.monotonic(), [], []
    remaining = None
    try:
        for sport in sport_keys:
            reserve_request()
            response = requests.get(f"{BASE}/{sport}/odds", params={"apiKey": api_key,
                                    "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"}, timeout=(5, 15))
            if response.status_code != 200:
                raise ValueError(f"Odds-feed svarede HTTP {response.status_code}; tjek noegle/kvote")
            value = response.headers.get("x-requests-remaining")
            remaining = int(value) if value and value.isdigit() else None
            raw_events = response.json()
            if not isinstance(raw_events, list):
                raise ValueError("Odds-feed returnerede et ugyldigt format")
            received = time.time()
            for raw in raw_events[:100]:
                try:
                    out.append(normalize(raw, received, "PAPER"))
                except (ValueError, TypeError, AttributeError) as error:
                    rejected.append({"event_id": str(raw.get("id", "?")), "reason": str(error)})
        _status(True, now, f"{len(out)} kampe; {len(rejected)} i karantaene", (time.monotonic()-timer)*1000, remaining)
    except (requests.RequestException, ValueError) as error:
        # requests exceptions can contain the API key in the URL.
        message = str(error) if isinstance(error, ValueError) else f"Netvaerksfejl: {type(error).__name__}"
        _status(False, now, message, (time.monotonic()-timer)*1000, remaining)
        raise ValueError(message) from None
    return out, rejected


def reserve_request():
    from . import settings
    day = time.strftime("%Y-%m-%d", time.gmtime())
    limit = int(settings.load().get("odds_daily_request_limit", 24))
    with database.connection(write=True) as db:
        db.execute("INSERT OR IGNORE INTO provider_usage(day) VALUES(?)", (day,))
        used = db.execute("SELECT calls FROM provider_usage WHERE day=?", (day,)).fetchone()[0]
        if used >= limit:
            raise ValueError("Dagligt odds-requestbudget er opbrugt; intet API-kald sendt")
        db.execute("UPDATE provider_usage SET calls=calls+1 WHERE day=?", (day,))


def completed_scores(api_key, sport):
    # h2h regulation-time settlement is only unambiguous for these regular leagues.
    supported = {"soccer_epl", "soccer_denmark_superliga", "soccer_spain_la_liga", "soccer_germany_bundesliga", "soccer_italy_serie_a", "soccer_france_ligue_one"}
    if sport not in supported:
        return []
    reserve_request()
    try:
        response = requests.get(f"{BASE}/{sport}/scores", params={"apiKey": api_key, "daysFrom": 3}, timeout=(5,15))
        if response.status_code != 200:
            raise ValueError(f"Resultat-feed svarede HTTP {response.status_code}")
        scores = response.json()
        if not isinstance(scores, list):
            raise ValueError("Ugyldigt resultat-feed")
        return [s for s in scores if s.get("completed") is True]
    except requests.RequestException as error:
        raise ValueError("Resultat-feed fejlede: "+type(error).__name__) from None


def digest(event):
    return hashlib.sha256(database.dumps(event).encode()).hexdigest()
