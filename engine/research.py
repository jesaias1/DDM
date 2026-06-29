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


def estimate_probabilities(match: dict, market_probs: list[float],
                           outcomes: list[str] | None = None) -> list[float]:
    """
    AI'ens uafhængige sandsynlighedsbud efter research — for ENHVER sportsgren.
    Virker med 2 udfald (tennis, e-sport, basket) eller 3 (fodbold m. uafgjort).
    Returnerer en liste i SAMME rækkefølge som `outcomes`. Falder altid tilbage
    til markedet ved manglende nøgle, budget eller fejl, så motoren aldrig går i stå.
    """
    n = len(market_probs)
    if not outcomes or len(outcomes) != n:
        outcomes = (["Hjemmesejr", "Uafgjort", "Udesejr"] if n == 3
                    else [match.get("home", "Udfald 1"), match.get("away", "Udfald 2")])[:n]

    cfg = settings.load()
    usage = _load_usage()
    key = _cache_key(match, market_probs)
    cached = usage.get("cache", {}).get(key)
    if cached and len(cached) == n:
        return cached

    if not available() or not _budget_allows_call(usage, cfg):
        return market_probs

    client = anthropic.Anthropic()
    web_search = bool(cfg.get("ai_web_search_enabled", settings.PUBLIC_DEFAULTS["ai_web_search_enabled"]))
    max_tokens = int(cfg.get("ai_max_tokens_per_call", settings.PUBLIC_DEFAULTS["ai_max_tokens_per_call"]))
    sport = match.get("sport", "sport")
    out_lines = "\n".join(f"  {i+1}. {name}: marked {market_probs[i]:.3f}"
                          for i, name in enumerate(outcomes))
    example = "[" + ", ".join("0.xx" for _ in outcomes) + "]"
    prompt = (
        f"Du er en kvantitativ sportsanalytiker. Vurdér sandsynligheden for hvert "
        f"udfald i denne kamp med "
        f"{'web-søgning' if web_search else 'kort, konservativ analyse uden web-søgning'}.\n\n"
        f"Sport/turnering: {sport}\n"
        f"Kamp: {match.get('home', '?')} vs {match.get('away', '?')}\n\n"
        f"Udfald og markedets implicitte sandsynligheder (bookmaker-margin fjernet):\n"
        f"{out_lines}\n\n"
        f"Vægt relevant: form, skader/fravær, opstilling, indbyrdes opgør og nyheder. "
        f"Afvig kun fra markedet hvor din research giver en konkret grund — kopiér ikke tallene.\n\n"
        f"Afslut med PRÆCIS én linje ren JSON: en liste med {n} tal i SAMME rækkefølge "
        f"som udfaldene ovenfor, der summer til 1.0. Fx: {example}"
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
    """
    Læs AI'ens svar og normalisér til sum 1. Forventer en JSON-liste med samme
    antal tal som fallback (rækkefølge-baseret). Falder tilbage til 3-vejs objekt
    {home,draw,away} hvis modellen brugte det format.
    """
    n = len(fallback)
    # 1) rækkefølge-baseret liste: [p1, p2, ...]
    a, b = text.rfind("["), text.rfind("]") + 1
    if 0 <= a < b:
        try:
            arr = [float(x) for x in json.loads(text[a:b])]
            if len(arr) == n and sum(arr) > 0:
                t = sum(arr)
                return [p / t for p in arr]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    # 2) bagudkompatibelt 3-vejs objekt
    if n == 3:
        c, d = text.rfind("{"), text.rfind("}") + 1
        if 0 <= c < d:
            try:
                data = json.loads(text[c:d])
                probs = [float(data["home"]), float(data["draw"]), float(data["away"])]
                t = sum(probs)
                if t > 0:
                    return [p / t for p in probs]
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
    return fallback
