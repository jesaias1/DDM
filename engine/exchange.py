"""
Børs-modul: forbindelsen til en RIGTIG krypto-børs (via ccxt).

Dette er det der gør "indbetal → AI styrer → hæv ud" muligt og LOVLIGT — krypto-børser
tilbyder officielle trading-API'er (i modsætning til bettingsider). Du beholder fuld
kontrol over pengene.

SIKKERHED — læs dette:
  • Opret din API-nøgle med KUN "trade"-rettigheder. ALDRIG "withdraw"/udbetaling.
    Så kan hverken denne kode, en fejl, eller en angriber trække penge ud af din konto.
  • Nøgler læses kun fra miljøvariabler (EXCHANGE_ID, EXCHANGE_API_KEY,
    EXCHANGE_API_SECRET) — de gemmes aldrig i en fil.
  • Uden de to kontakter (DDM_LIVE=1 OG nøgler sat) kører ALT i tør-kørsel:
    rigtige live-priser, men ingen rigtige ordrer sendes.

Standard: børs = coinbase, kvotevaluta = EUR.
"""
import os

from . import strategy

try:
    import ccxt
except ImportError:
    ccxt = None

EXCHANGE_ID = os.environ.get("EXCHANGE_ID", os.environ.get("DDM_EXCHANGE_ID", "coinbase"))
QUOTE = os.environ.get("DDM_QUOTE", os.environ.get("SMARTSTAKE_QUOTE", "EUR"))
LIVE_ARM_PHRASE = "JEG_FORSTAAR_RISIKOEN"

_DEFAULT_UNIVERSE = "BTC/EUR,ETH/EUR,SOL/EUR,ADA/EUR,LINK/EUR"
UNIVERSE = [
    s.strip().upper()
    for s in os.environ.get("DDM_UNIVERSE", os.environ.get("SMARTSTAKE_UNIVERSE", _DEFAULT_UNIVERSE)).split(",")
    if s.strip()
]


def live_enabled() -> bool:
    """
    Er rigtig handel slået til? Kræver BEGGE: den eksplicitte kontakt OG nøgler.
    Alt andet = tør-kørsel (paper), uanset hvad.
    """
    return (
        ccxt is not None
        and os.environ.get("DDM_LIVE", os.environ.get("SMARTSTAKE_LIVE")) == "1"
        and os.environ.get("DDM_LIVE_ARMED") == LIVE_ARM_PHRASE
        and bool(os.environ.get("EXCHANGE_API_KEY"))
        and bool(os.environ.get("EXCHANGE_API_SECRET"))
    )


def live_requested() -> bool:
    return os.environ.get("DDM_LIVE", os.environ.get("SMARTSTAKE_LIVE")) == "1"


def live_armed() -> bool:
    return os.environ.get("DDM_LIVE_ARMED") == LIVE_ARM_PHRASE


def keys_present() -> bool:
    return bool(os.environ.get("EXCHANGE_API_KEY")) and bool(os.environ.get("EXCHANGE_API_SECRET"))


def _client(with_keys: bool):
    """Byg en ccxt-børsinstans. with_keys=False = kun offentlige data (priser)."""
    if ccxt is None:
        raise RuntimeError("ccxt er ikke installeret (pip install ccxt)")
    klass = getattr(ccxt, EXCHANGE_ID)
    cfg = {"enableRateLimit": True}
    if with_keys:
        cfg["apiKey"] = os.environ["EXCHANGE_API_KEY"]
        cfg["secret"] = os.environ["EXCHANGE_API_SECRET"]
        password = os.environ.get("EXCHANGE_API_PASSWORD") or os.environ.get("EXCHANGE_API_PASSPHRASE")
        if password:
            cfg["password"] = password
    return klass(cfg)


def preflight() -> dict:
    """
    Tjek om maskinen er klar til autonom krypto-handel.
    Sender ingen ordrer. Læser kun public markets og evt. privat saldo.
    """
    checks = []

    def add(name: str, ok: bool, message: str):
        checks.append({"name": name, "ok": bool(ok), "message": message})

    add("ccxt", ccxt is not None, "ccxt installeret" if ccxt is not None else "ccxt mangler")
    add("live-kontakt", live_requested(), "DDM_LIVE=1" if live_requested() else "DDM_LIVE er ikke slået til")
    add("live-arming", live_armed(), "DDM_LIVE_ARMED er sat" if live_armed() else f"kræver DDM_LIVE_ARMED={LIVE_ARM_PHRASE}")
    add("api-nøgler", keys_present(), "API key/secret fundet" if keys_present() else "EXCHANGE_API_KEY/SECRET mangler")

    public_ok = False
    supported = []
    missing = list(UNIVERSE)
    if ccxt is not None:
        try:
            ex = _client(with_keys=False)
            markets = ex.load_markets()
            supported = [s for s in UNIVERSE if s in markets]
            missing = [s for s in UNIVERSE if s not in markets]
            public_ok = bool(supported)
            msg = f"{len(supported)}/{len(UNIVERSE)} par fundet"
            if missing:
                msg += f"; mangler: {', '.join(missing[:5])}"
            add("markeder", public_ok, msg)
        except Exception as e:
            add("markeder", False, f"kunne ikke hente markeder: {e}")

    balance_ok = False
    balance = None
    if ccxt is not None and keys_present():
        try:
            balance = get_quote_balance()
            balance_ok = True
            add("saldo", True, f"kunne læse fri saldo: {balance:.2f} {QUOTE}")
        except Exception as e:
            add("saldo", False, f"kunne ikke læse saldo med nøgler: {e}")
    else:
        add("saldo", False, "springes over indtil API-nøgler er sat")

    can_trade = live_enabled() and public_ok and balance_ok
    return {
        "ok": can_trade,
        "can_trade": can_trade,
        "exchange": EXCHANGE_ID,
        "quote": QUOTE,
        "live_requested": live_requested(),
        "live_armed": live_armed(),
        "keys_present": keys_present(),
        "universe": UNIVERSE,
        "supported_symbols": supported,
        "missing_symbols": missing,
        "balance": balance,
        "checks": checks,
        "arm_phrase": LIVE_ARM_PHRASE,
        "note": "Preflight sender ingen ordrer.",
    }


# ---------- offentlige data (ingen nøgle nødvendig) ----------

def fetch_signals() -> list[dict]:
    """
    Byg momentum-signaler fra ægte daglige candles med samme strategi-kerne som
    live exits/backtest: trend-filter, momentum og gebyrjusteret edge.
    """
    if ccxt is None:
        return []
    ex = _client(with_keys=False)
    opps = []
    for symbol in UNIVERSE:
        try:
            ohlcv = ex.fetch_ohlcv(symbol, timeframe="1d", limit=strategy.LOOKBACK)
        except Exception as e:
            print(f"[exchange] {symbol}: kunne ikke hente candles: {e}")
            continue
        if len(ohlcv) < strategy.TREND_LEN + 1:
            continue
        closes = [c[4] for c in ohlcv]
        sig = strategy.momentum_signal(closes)
        if not sig:
            continue
        opps.append({
            "type": "market", "id": symbol, "name": symbol, "price": closes[-1],
            "expected_return": sig["expected_return"], "volatility": sig["volatility"],
            "reason": (f"Trend over {strategy.TREND_LEN}d SMA. Momentum "
                       f"{sig['ch_24h']*100:+.1f}% (24t), {sig['ch_7d']*100:+.1f}% (7d). "
                       f"Netto-edge ca. {sig['expected_return']*100:.2f}%/dag efter gebyrbuffer."),
        })
    return opps


def get_price(symbol: str) -> float:
    """Aktuel pris for ét par (offentlig)."""
    if ccxt is None:
        return 0.0
    try:
        return _client(with_keys=False).fetch_ticker(symbol)["last"]
    except Exception as e:
        print(f"[exchange] pris {symbol} fejlede: {e}")
        return 0.0


# ---------- konto + ordrer (kræver nøgler; kun i live) ----------

def get_quote_balance() -> float:
    """Fri saldo i kvotevaluta (fx EUR) på den rigtige konto."""
    ex = _client(with_keys=True)
    bal = ex.fetch_balance()
    return float(bal.get("free", {}).get(QUOTE, 0.0))


def market_buy(symbol: str, quote_amount: float) -> dict:
    """
    Køb for et beløb i kvotevaluta. Returnerer {amount (base), price}.
    Sendes KUN i live; kaldes aldrig i tør-kørsel.

    Respekterer børsens minimums-ordrestørrelse, så ordren ikke afvises.
    """
    ex = _client(with_keys=True)
    ex.load_markets()
    price = get_price(symbol)
    if price <= 0:
        raise RuntimeError(f"ugyldig pris for {symbol}")
    amount = quote_amount / price

    # Tjek børsens minimums-grænser (mængde og kostpris) hvis de findes.
    limits = (ex.markets.get(symbol) or {}).get("limits", {})
    min_amt = (limits.get("amount") or {}).get("min")
    min_cost = (limits.get("cost") or {}).get("min")
    if min_amt and amount < min_amt:
        raise RuntimeError(f"{symbol}: beløb under børsens minimum ({min_amt} {symbol.split('/')[0]})")
    if min_cost and quote_amount < min_cost:
        raise RuntimeError(f"{symbol}: {quote_amount:.2f} under børsens min. kostpris ({min_cost} {QUOTE})")

    amount = float(ex.amount_to_precision(symbol, amount))  # afrund til børsens præcision
    order = ex.create_market_buy_order(symbol, amount)
    filled = float(order.get("filled") or amount)
    avg = float(order.get("average") or price)
    return {"amount": filled, "price": avg}


def deposit_address(currency: str) -> dict:
    """
    Hent din RIGTIGE indbetalingsadresse på børsen for en valuta (fx BTC, ETH, USDT).
    Det er sådan du "sender krypto til siden": du sender til din egen børskonto, og
    auto-traderen handler så med saldoen. Kræver en nøgle med funding/deposit-adgang
    (stadig IKKE udbetaling). Returnerer {address, tag, network} eller {error}.
    """
    if ccxt is None:
        return {"error": "ccxt ikke installeret"}
    try:
        ex = _client(with_keys=True)
        info = ex.fetch_deposit_address(currency)
        return {
            "address": info.get("address"),
            "tag": info.get("tag"),
            "network": info.get("network") or (info.get("info", {}) or {}).get("network"),
            "currency": currency,
        }
    except Exception as e:
        return {"error": str(e)}


def market_sell(symbol: str, amount: float) -> dict:
    """Sælg en base-mængde til markedspris. Returnerer {proceeds, price}."""
    ex = _client(with_keys=True)
    order = ex.create_market_sell_order(symbol, amount)
    price = float(order.get("average") or get_price(symbol))
    proceeds = float(order.get("cost") or amount * price)
    return {"proceeds": proceeds, "price": price}
