"""
Strategi-kerne — ÉT sted for handelslogikken, så live-handel og backtest bruger
præcis samme regler (ellers lyver backtesten om hvad der sker med rigtige penge).

Forbedringer over en naiv momentum-strategi:
  • TREND-FILTER: køb kun når prisen er over sit eget glidende gennemsnit (SMA).
    Momentum bløder i sidelæns/faldende markeder — dette undgår at handle uden trend.
  • TRAILING STOP: lad vinderne løbe og flyt stoppet op efter prisen, i stedet for
    at sælge ved et fast loft. Momentums edge ligger i de få store trends.
  • GEBYRER: realistisk handelsfriktion (Coinbase ~0,6%/handel) så tallene er ærlige.

Alle parametre kan overstyres med miljøvariabler, så du kan tune uden at røre kode.
"""
import os


def _env_value(name: str, default):
    """Read DDM_* first, then legacy SMARTSTAKE_* for backwards compatibility."""
    if name.startswith("SMARTSTAKE_"):
        ddm_name = "DDM_" + name.removeprefix("SMARTSTAKE_")
        return os.environ.get(ddm_name, os.environ.get(name, default))
    return os.environ.get(name, default)


def _envf(name: str, default: float) -> float:
    try:
        return float(_env_value(name, default))
    except (TypeError, ValueError):
        return default


def _envi(name: str, default: int) -> int:
    try:
        return int(_env_value(name, default))
    except (TypeError, ValueError):
        return default


STOP_LOSS = _envf("SMARTSTAKE_STOP_LOSS", -0.08)   # hård bund: sælg ved -8%
TRAIL_PCT = _envf("SMARTSTAKE_TRAIL", 0.12)        # trailing: sælg ved 12% fald fra top
ARM_PROFIT = _envf("SMARTSTAKE_ARM", 0.05)         # trailing armes først efter +5% gevinst
TREND_LEN = _envi("SMARTSTAKE_TREND_LEN", 50)      # SMA-længde til trend-filter (dage)
FEE = _envf("SMARTSTAKE_FEE", 0.006)               # gebyr pr. handel (Coinbase taker ~0,6%)
EXPECTED_HOLD_DAYS = _envi("SMARTSTAKE_HOLD_DAYS", 7)
MIN_NET_EDGE = _envf("SMARTSTAKE_MIN_NET_EDGE", 0.002)
COOLDOWN_SECONDS = _envi("SMARTSTAKE_COOLDOWN_SECONDS", 6 * 60 * 60)

# Hvor mange candles signalet kræver (SMA-vindue + lidt buffer til momentum).
LOOKBACK = TREND_LEN + 10


def momentum_signal(closes: list[float]) -> dict | None:
    """
    Byg et købssignal ud fra en liste lukkekurser (ældst→nyest).
    Returnerer None hvis trend-filteret eller momentum ikke er opfyldt.
    """
    if len(closes) < TREND_LEN + 1:
        return None
    price = closes[-1]
    sma = sum(closes[-TREND_LEN:]) / TREND_LEN
    if price <= sma:                       # TREND-FILTER: skal være over SMA
        return None
    ch_24h = price / closes[-2] - 1 if closes[-2] else 0
    ch_7d = price / closes[-8] - 1 if len(closes) >= 8 and closes[-8] else 0
    if ch_24h <= 0 or ch_7d <= 0:          # bekræftet positivt momentum
        return None
    momentum = 0.6 * ch_24h + 0.4 * (ch_7d / 7)
    expected_return = max(0.0, momentum * 0.5)
    net_expected = expected_return - (2 * FEE / max(1, EXPECTED_HOLD_DAYS))
    if net_expected < MIN_NET_EDGE:
        return None
    return {
        "expected_return": max(0.0, net_expected),
        "raw_expected_return": expected_return,
        "volatility": (abs(ch_24h) + abs(ch_7d) / 7) / 2 + 0.01,
        "ch_24h": ch_24h, "ch_7d": ch_7d, "sma": sma,
    }


def should_exit(entry: float, peak: float, price: float) -> tuple[bool, str | None]:
    """
    Afgør om en åben position skal lukkes.
      • hård stop-loss ved STOP_LOSS.
      • trailing stop: når positionen har været mindst ARM_PROFIT i plus, sælg hvis
        prisen falder TRAIL_PCT fra sin højeste top.
    """
    if entry <= 0:
        return False, None
    change = (price - entry) / entry
    if change <= STOP_LOSS:
        return True, f"stop-loss ({change*100:+.1f}%)"
    armed = peak >= entry * (1 + ARM_PROFIT)
    if armed and peak > 0 and (price - peak) / peak <= -TRAIL_PCT:
        return True, f"trailing-stop ({(price-entry)/entry*100:+.1f}%)"
    return False, None
