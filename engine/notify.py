"""
Mobil-beskeder via Telegram.

Hvorfor Telegram og ikke WhatsApp: WhatsApp kræver en godkendt Meta Business
API-konto (tungt og delvist betalt). Telegram er gratis, privat og sat op på
5 minutter: opret en bot hos @BotFather, gem tokenen, skriv til botten og hent
dit chat-id. Se MOBIL_BESKED_GUIDE.txt.

To slags beskeder (styres i Settings-fanen):
  • Daglig status kl. `notify_daily_hour` — pulje, positioner, dagens handler.
  • Handels-beskeder med det samme ved køb/salg/risikobremse.

Design-regel: en fejlet besked må ALDRIG stoppe handel. Alt her er pakket ind i
try/except og returnerer bare False ved fejl.
"""
import os
import time

import requests

from . import settings, store

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "notify.json")
API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _cfg() -> dict:
    cfg = settings.load()
    d = settings.PUBLIC_DEFAULTS
    return {
        "token": (cfg.get("telegram_bot_token") or os.environ.get("DDM_TELEGRAM_TOKEN") or "").strip(),
        "chat_id": str(cfg.get("telegram_chat_id", d["telegram_chat_id"])).strip(),
        "enabled": bool(cfg.get("notify_enabled", d["notify_enabled"])),
        "trades": bool(cfg.get("notify_trades", d["notify_trades"])),
        "hour": min(23, max(0, int(cfg.get("notify_daily_hour", d["notify_daily_hour"])))),
    }


def configured() -> bool:
    c = _cfg()
    return bool(c["token"] and c["chat_id"])


def send(text: str) -> bool:
    """Send én besked. Fejler stille (returnerer False) — stopper aldrig motoren."""
    c = _cfg()
    if not (c["token"] and c["chat_id"]):
        return False
    try:
        r = requests.post(
            API_URL.format(token=c["token"]),
            json={"chat_id": c["chat_id"], "text": text},
            timeout=10,
        )
        return bool(r.ok and r.json().get("ok"))
    except Exception as e:
        print(f"[notify] kunne ikke sende Telegram-besked: {e}")
        return False


def trade_alert(lines: list[str], live: bool) -> bool:
    """Straks-besked ved køb/salg/risikobremse. Kun hvis slået til i Settings."""
    c = _cfg()
    if not (c["enabled"] and c["trades"] and lines):
        return False
    tag = "LIVE — RIGTIGE PENGE" if live else "TØR-KØRSEL"
    return send(f"🤖 DDM [{tag}]\n" + "\n".join(lines))


def build_daily_report() -> str:
    """Byg dagens statusbesked ud fra auto-traderens tilstand."""
    from . import autotrader  # lazy: undgår cirkulær import
    s = autotrader.status()
    tag = "LIVE — RIGTIGE PENGE" if s["live"] else "TØR-KØRSEL"
    lines = [f"📊 DDM daglig status [{tag}]",
             f"Pulje: {s['equity']:.2f} {s['quote']} · kontant {s['cash']:.2f} {s['quote']}"]
    if s["positions"]:
        lines.append(f"Åbne positioner ({len(s['positions'])}):")
        for p in s["positions"]:
            chg = (p["now"] - p["entry"]) / p["entry"] * 100 if p["entry"] else 0.0
            lines.append(f"  • {p['symbol']}: {chg:+.1f}% (kost {p['cost']:.2f})")
    else:
        lines.append("Ingen åbne positioner (venter på momentum-signal).")
    cutoff = time.time() - 24 * 3600
    recent = [h for h in s["history"] if h.get("ts", 0) >= cutoff]
    if recent:
        lines.append(f"Handler seneste 24t ({len(recent)}):")
        for h in recent[:6]:
            lines.append(f"  • {h['symbol']}: {h['pnl']:+.2f} ({h['reason']})")
    else:
        lines.append("Ingen handler seneste 24t.")
    risk = s.get("risk", {})
    if risk.get("halted"):
        lines.append(f"⛔ Risikobremse aktiv: {risk.get('halt_reason')}")
    else:
        lines.append(f"Dag: {risk.get('daily_return_pct', 0):+.2f}% · total: {risk.get('total_return_pct', 0):+.2f}%")
    return "\n".join(lines)


def maybe_daily_report() -> bool:
    """
    Kaldes af scheduleren hver runde: send dagens rapport én gang, når klokken
    har passeret `notify_daily_hour`. Husker sidste afsendelse i data/notify.json.
    """
    c = _cfg()
    if not (c["enabled"] and c["token"] and c["chat_id"]):
        return False
    now = time.localtime()
    if now.tm_hour < c["hour"]:
        return False
    today = time.strftime("%Y-%m-%d", now)
    with store.lock_for(STATE_PATH):
        state = store.load(STATE_PATH) or {}
        if state.get("last_daily") == today:
            return False
        try:
            ok = send(build_daily_report())
        except Exception as e:
            print(f"[notify] daglig rapport fejlede: {e}")
            return False
        if ok:
            state["last_daily"] = today
            store.save(STATE_PATH, state)
        return ok


def test_message() -> dict:
    """Til 'Send test'-knappen i Settings."""
    if not configured():
        return {"ok": False, "message": "Udfyld Telegram bot-token og chat-id først (se MOBIL_BESKED_GUIDE.txt)."}
    ok = send("✅ DDM test: beskeder til mobilen virker!")
    return {"ok": ok, "message": "Testbesked sendt — tjek din Telegram!" if ok
            else "Kunne ikke sende. Tjek token/chat-id (og at du har skrevet /start til botten)."}
