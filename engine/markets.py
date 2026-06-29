"""
Markeds-modul: høj-risiko investeringsdelen.

Henter ÆGTE krypto-priser i danske kroner fra CoinGecko (gratis, ingen API-nøgle).
Krypto er valgt fordi det er højrisiko (matcher ønsket), handles 24/7, og — i
modsætning til bookmakere — ikke lukker din konto når du tjener penge.

Strategi: momentum. Aktiver der er steget med stigende fart har historisk en svag
tendens til at fortsætte kort tid. Vi omsætter momentum-styrken til et estimeret
forventet afkast + volatilitet, som Kelly-motoren bruger til at størrelse positionen.

VIGTIGT: momentum giver en SVAG, ustabil edge. Den forsvinder i perioder og kan
vende til tab. Derfor paper-trading først, og derfor fraktioneret Kelly.
"""
import requests

from . import strategy

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"

# Aktiver vi overvåger. Tilføj/fjern frit (brug CoinGecko's id'er).
UNIVERSE = ["bitcoin", "ethereum", "solana", "cardano", "chainlink"]

# Legacy aliases for older callers/tests. New exits live in engine.strategy.
TAKE_PROFIT = 0.15
STOP_LOSS = strategy.STOP_LOSS


def fetch_market_data() -> list[dict]:
    """
    Hent live-priser og prisændringer i DKK. Returnerer en liste af aktiver, eller
    en tom liste hvis nettet/API'et fejler (motoren springer så markeder over).
    """
    params = {
        "vs_currency": "dkk",
        "ids": ",".join(UNIVERSE),
        "price_change_percentage": "1h,24h,7d",
    }
    try:
        r = requests.get(COINGECKO_URL, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[markets] kunne ikke hente data: {e}")
        return []


def _signal_from(asset: dict) -> dict | None:
    """
    Omsæt rå prisdata til et handels-signal med estimeret afkast + volatilitet.

    Logik (bevidst simpel og gennemskuelig):
      - momentum = vægtet sum af 24t- og 7d-ændring.
      - kræver POSITIVT momentum på begge horisonter (trend bekræftet).
      - forventet afkast skaleres af momentum-styrken, men holdes konservativt.
      - volatilitet estimeres groft fra størrelsen af de seneste udsving.
    """
    ch_1h = (asset.get("price_change_percentage_1h_in_currency") or 0) / 100
    ch_24h = (asset.get("price_change_percentage_24h_in_currency") or 0) / 100
    ch_7d = (asset.get("price_change_percentage_7d_in_currency") or 0) / 100

    # Trend skal være bekræftet på både kort og mellem sigt.
    if ch_24h <= 0 or ch_7d <= 0:
        return None

    momentum = 0.6 * ch_24h + 0.4 * (ch_7d / 7)  # daglig-ækvivalent momentum
    # Konservativt estimat: vi forventer kun at en BRØKDEL af momentum fortsætter.
    expected_return = max(0.0, momentum * 0.5)
    expected_return -= 2 * strategy.FEE / max(1, strategy.EXPECTED_HOLD_DAYS)
    if expected_return < strategy.MIN_NET_EDGE:
        return None
    # Volatilitet: brug spændet i de observerede ændringer som proxy.
    volatility = (abs(ch_1h) + abs(ch_24h) + abs(ch_7d) / 7) / 3 + 0.01

    return {
        "expected_return": expected_return,
        "volatility": volatility,
        "momentum_24h": ch_24h,
        "momentum_7d": ch_7d,
    }


def explain_asset(asset: dict) -> dict:
    """Forklar om et aktiv blev godkendt eller afvist som signal."""
    ch_1h = (asset.get("price_change_percentage_1h_in_currency") or 0) / 100
    ch_24h = (asset.get("price_change_percentage_24h_in_currency") or 0) / 100
    ch_7d = (asset.get("price_change_percentage_7d_in_currency") or 0) / 100
    name = asset.get("symbol", asset.get("id", "?")).upper()
    price = asset.get("current_price", 0.0)

    if ch_24h <= 0 or ch_7d <= 0:
        return {
            "id": asset.get("id"),
            "name": name,
            "price": price,
            "accepted": False,
            "reason": f"afvist: momentum ikke positivt på både 24t ({ch_24h*100:+.1f}%) og 7d ({ch_7d*100:+.1f}%)",
        }

    momentum = 0.6 * ch_24h + 0.4 * (ch_7d / 7)
    gross_expected = max(0.0, momentum * 0.5)
    fee_drag = 2 * strategy.FEE / max(1, strategy.EXPECTED_HOLD_DAYS)
    net_expected = gross_expected - fee_drag
    if net_expected < strategy.MIN_NET_EDGE:
        return {
            "id": asset.get("id"),
            "name": name,
            "price": price,
            "accepted": False,
            "reason": f"afvist: netto-edge {net_expected*100:.2f}%/dag er under minimum {strategy.MIN_NET_EDGE*100:.2f}% efter gebyrbuffer",
        }

    volatility = (abs(ch_1h) + abs(ch_24h) + abs(ch_7d) / 7) / 3 + 0.01
    return {
        "id": asset.get("id"),
        "name": name,
        "price": price,
        "accepted": True,
        "expected_return": net_expected,
        "volatility": volatility,
        "reason": f"godkendt: 24t {ch_24h*100:+.1f}%, 7d {ch_7d*100:+.1f}%, netto-edge {net_expected*100:.2f}%/dag",
    }


def inspect_opportunities() -> dict:
    """Diagnostik til UI: hvad blev scannet, og hvorfor blev det afvist/godkendt."""
    assets = fetch_market_data()
    inspected = [explain_asset(asset) for asset in assets]
    return {
        "source": "CoinGecko",
        "scanned": len(assets),
        "accepted": sum(1 for item in inspected if item["accepted"]),
        "items": inspected,
    }


def find_opportunities() -> list[dict]:
    """
    Returnér en liste af investeringsmuligheder klar til allokatoren. Hver mulighed:
      { type, id, name, price, expected_return, volatility, reason }
    """
    opps = []
    for asset in fetch_market_data():
        sig = _signal_from(asset)
        if not sig:
            continue
        opps.append({
            "type": "market",
            "id": asset["id"],
            "name": asset.get("symbol", asset["id"]).upper(),
            "price": asset.get("current_price", 0.0),
            "expected_return": sig["expected_return"],
            "volatility": sig["volatility"],
            "reason": (f"Momentum bekræftet: +{sig['momentum_24h']*100:.1f}% (24t), "
                       f"+{sig['momentum_7d']*100:.1f}% (7d). "
                       f"Forventet edge {sig['expected_return']*100:.2f}%/dag."),
        })
    return opps


def current_prices(ids: list[str]) -> dict[str, float]:
    """Hent nuværende pris (DKK) for en liste aktiver — bruges til at værdisætte åbne positioner."""
    if not ids:
        return {}
    try:
        params = {"vs_currency": "dkk", "ids": ",".join(ids)}
        r = requests.get(COINGECKO_URL, params=params, timeout=15)
        r.raise_for_status()
        return {a["id"]: a.get("current_price", 0.0) for a in r.json()}
    except Exception as e:
        print(f"[markets] kunne ikke hente priser: {e}")
        return {}
