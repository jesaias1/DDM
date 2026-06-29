"""
Research-modul: AI'ens informationsfordel.

Dette er kernen i din idé — "lad AI læse alt om hver spiller og kamp i stedet for
at gætte". Modulet bruger Claude med web-søgning til at researche en konkret kamp
(form, skader, opstillinger, h2h, nyheder) og give sit eget sandsynlighedsbud, som
sports-modulet sammenligner med oddsene for at finde value.

Ærligt forbehold (vigtigt): bookmakernes odds indregner allerede offentlige nyheder
lynhurtigt. At læse de samme artikler gør dig BEDRE end et blindt gæt, men det giver
ikke en garanteret kant mod en skarp bookmaker. Brug det som et kvalificeret bud,
ikke et orakel — derfor paper-trading først.

Kræver:
  - pip install anthropic
  - miljøvariabel ANTHROPIC_API_KEY (din egen API-nøgle — koster penge pr. kald)

Model: som standard claude-opus-4-8 (mest kapabel). Sæt SMARTSTAKE_MODEL for at
skifte til en billigere model, fx claude-haiku-4-5, hvis du laver mange kald.
"""
import os
import json
import time
import hashlib

try:
    import anthropic
except ImportError:
    anthropic = None

from . import settings, store

DEFAULT_MODEL = "claude-haiku-4-5"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}
USAGE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ai_usage.json")


def available() -> bool:
    """Kan vi køre AI-research? (SDK + nøgle + settings-budget)"""
    cfg = settings.load()
    return (
        anthropic is not None
        and bool(os.environ.get("ANTHROPIC_API_KEY"))
        and bool(cfg.get("ai_research_enabled", settings.PUBLIC_DEFAULTS["ai_research_enabled"]))
    )


def model() -> str:
    return os.environ.get("SMARTSTAKE_MODEL", DEFAULT_MODEL)


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _default_usage() -> dict:
    return {"day": _today(), "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache": {}}


def _load_usage() -> dict:
    usage = store.load(USAGE_PATH) or _default_usage()
    if usage.get("day") != _today():
        usage = _default_usage()
    usage.setdefault("cache", {})
    usage.setdefault("calls", 0)
    usage.setdefault("input_tokens", 0)
    usage.setdefault("output_tokens", 0)
    return usage


def usage_status() -> dict:
    usage = _load_usage()
    cfg = settings.load()
    total_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    call_limit = int(cfg.get("ai_daily_call_limit", settings.PUBLIC_DEFAULTS["ai_daily_call_limit"]))
    token_budget = int(cfg.get("ai_daily_token_budget", settings.PUBLIC_DEFAULTS["ai_daily_token_budget"]))
    return {
        "day": usage["day"],
        "calls": int(usage["calls"]),
        "call_limit": call_limit,
        "tokens": total_tokens,
        "token_budget": token_budget,
        "cache_entries": len(usage.get("cache", {})),
        "enabled": bool(cfg.get("ai_research_enabled", settings.PUBLIC_DEFAULTS["ai_research_enabled"])),
        "web_search_enabled": bool(cfg.get("ai_web_search_enabled", settings.PUBLIC_DEFAULTS["ai_web_search_enabled"])),
    }


def _cache_key(match: dict, market_probs: list[float]) -> str:
    raw = json.dumps({
        "day": _today(),
        "id": match.get("id"),
        "home": match.get("home"),
        "away": match.get("away"),
        "market": [round(p, 4) for p in market_probs],
        "model": model(),
    }, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _budget_allows_call(usage: dict, cfg: dict) -> bool:
    calls = int(usage.get("calls", 0))
    tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    call_limit = int(cfg.get("ai_daily_call_limit", settings.PUBLIC_DEFAULTS["ai_daily_call_limit"]))
    token_budget = int(cfg.get("ai_daily_token_budget", settings.PUBLIC_DEFAULTS["ai_daily_token_budget"]))
    return calls < call_limit and tokens < token_budget


def estimate_probabilities(match: dict, market_probs: list[float]) -> list[float]:
    """
    Returnér [p_home, p_draw, p_away] — AI'ens uafhængige bud efter web-research.
    Falder altid tilbage til markedet ved manglende nøgle eller fejl, så motoren
    aldrig går i stå.
    """
    cfg = settings.load()
    usage = _load_usage()
    key = _cache_key(match, market_probs)
    cached = usage.get("cache", {}).get(key)
    if cached:
        return cached

    if not available() or not _budget_allows_call(usage, cfg):
        return market_probs

    client = anthropic.Anthropic()
    web_search = bool(cfg.get("ai_web_search_enabled", settings.PUBLIC_DEFAULTS["ai_web_search_enabled"]))
    max_tokens = int(cfg.get("ai_max_tokens_per_call", settings.PUBLIC_DEFAULTS["ai_max_tokens_per_call"]))
    prompt = (
        f"Du er en kvantitativ fodboldanalytiker. Research denne kamp grundigt med "
        f"{'web-søgning' if web_search else 'kort, konservativ analyse uden web-søgning'} "
        f"og giv dit eget bud på sandsynligheden for hvert udfald.\n\n"
        f"Kamp: {match['home']} (hjemme) vs {match['away']} (ude)\n\n"
        f"Søg efter og vægt: aktuel form, skader/karantæner, forventede opstillinger, "
        f"indbyrdes opgør, hjemmebanefordel og relevante nyheder.\n\n"
        f"Til reference er markedets implicitte sandsynligheder (bookmaker-margin "
        f"fjernet): hjemme {market_probs[0]:.3f}, uafgjort {market_probs[1]:.3f}, "
        f"ude {market_probs[2]:.3f}. Afvig kun fra markedet hvor din research giver "
        f"en konkret grund — kopiér ikke bare tallene.\n\n"
        f"Afslut dit svar med PRÆCIS én linje ren JSON og intet andet på den linje:\n"
        f'{{"home": x, "draw": y, "away": z}}  (x+y+z skal være 1.0)'
    )

    try:
        messages = [{"role": "user", "content": prompt}]
        # Begrænset til få runder; web-søgning er slukket som standard for at spare tokens.
        rounds = 2 if web_search else 1
        for _ in range(rounds):
            kwargs = {
                "model": model(),
                "max_tokens": max(100, min(max_tokens, 1200)),
                "messages": messages,
            }
            if web_search:
                kwargs["tools"] = [WEB_SEARCH_TOOL]
            resp = client.messages.create(
                **kwargs
            )
            usage["calls"] = int(usage.get("calls", 0)) + 1
            resp_usage = getattr(resp, "usage", None)
            usage["input_tokens"] = int(usage.get("input_tokens", 0)) + int(getattr(resp_usage, "input_tokens", 0) or 0)
            usage["output_tokens"] = int(usage.get("output_tokens", 0)) + int(getattr(resp_usage, "output_tokens", 0) or 0)
            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                if not _budget_allows_call(usage, cfg):
                    break
                continue
            break

        text = "".join(b.text for b in resp.content if b.type == "text")
        probs = _parse_probs(text, market_probs)
        usage["cache"][key] = probs
        # Hold cachen lille og daglig.
        if len(usage["cache"]) > 100:
            usage["cache"] = dict(list(usage["cache"].items())[-100:])
        store.save(USAGE_PATH, usage)
        return probs
    except Exception as e:
        store.save(USAGE_PATH, usage)
        print(f"[research] AI-estimat fejlede, bruger marked: {e}")
        return market_probs


def _parse_probs(text: str, fallback: list[float]) -> list[float]:
    """Træk det sidste JSON-objekt ud af svaret og normalisér til sum 1."""
    start, end = text.rfind("{"), text.rfind("}") + 1
    if start < 0 or end <= start:
        return fallback
    try:
        data = json.loads(text[start:end])
        probs = [float(data["home"]), float(data["draw"]), float(data["away"])]
    except (json.JSONDecodeError, KeyError, ValueError):
        return fallback
    total = sum(probs)
    if total <= 0:
        return fallback
    return [p / total for p in probs]
