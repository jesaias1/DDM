"""Optional explanations only. LLM output never enters probability or staking."""
import hashlib
import json
import os
import time

from . import settings, store

try:
    import anthropic
except ImportError:
    anthropic = None

DEFAULT_MODEL = "claude-haiku-4-5"
USAGE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ai_usage.json")


def available():
    return bool(anthropic and os.environ.get("ANTHROPIC_API_KEY") and settings.load().get("ai_research_enabled", False))


def model():
    return os.environ.get("SMARTSTAKE_MODEL", DEFAULT_MODEL)


def _load_usage():
    day = time.strftime("%Y-%m-%d", time.gmtime())
    usage = store.load(USAGE_PATH) or {}
    if usage.get("version") != 2 or usage.get("day") != day:
        usage = {"version": 2, "day": day, "calls": 0, "input_tokens": 0, "output_tokens": 0, "reserved_tokens": 0, "cache": {}}
    return usage


def usage_status():
    with store.lock_for(USAGE_PATH):
        usage, cfg = _load_usage(), settings.load()
        return {"day": usage["day"], "calls": usage["calls"], "tokens": usage["input_tokens"]+usage["output_tokens"],
                "reserved_tokens": usage["reserved_tokens"], "call_limit": cfg.get("ai_daily_call_limit", 3),
                "token_budget": cfg.get("ai_daily_token_budget", 12000), "enabled": available(),
                "web_search_enabled": False, "cache_entries": len(usage["cache"]),
                "purpose": "Forklaring af registrerede data; ingen AI-sandsynligheder"}


def estimate_probabilities(match, market_probs, outcomes=None):
    """Legacy compatibility. An unvalidated language model cannot supply an edge."""
    return list(market_probs)


def explain(decision):
    cfg = settings.load()
    facts = {k: decision.get(k) for k in ("home", "away", "name", "odds", "p", "market_p", "robust_ev", "action", "reasons", "counterarguments")}
    prompt = ("Forklar paa dansk de vedlagte DDM-data i hoejst 120 ord. Brug kun de vedlagte fakta. "
              "Ingen egne tal, nyheder, skader, sandsynligheder eller nye anbefalinger. "
              "Usikkerhedsbufferen er ikke et konfidensinterval. Output er kommentar, ikke handelsinput.\n"+json.dumps(facts, ensure_ascii=True))
    key = hashlib.sha256((model()+prompt).encode()).hexdigest()
    max_tokens = min(800, max(100, int(cfg.get("ai_max_tokens_per_call", 800))))
    # Reserve worst-case input bound plus output before billing can begin.
    reservation = len(prompt.encode("utf-8"))+512+max_tokens
    with store.lock_for(USAGE_PATH):
        usage = _load_usage()
        if key in usage["cache"]:
            return {"text": usage["cache"][key], "cached": True, "quantitative_source": False}
        if not available():
            return {"text": " ".join(decision["reasons"]+decision["counterarguments"]), "cached": True, "ai": False}
        if usage["calls"] >= int(cfg.get("ai_daily_call_limit", 3)) or usage["reserved_tokens"]+reservation > int(cfg.get("ai_daily_token_budget", 12000)):
            raise ValueError("AI-budget er opbrugt; ingen forespoergsel sendt")
        usage["calls"] += 1
        usage["reserved_tokens"] += reservation
        store.save(USAGE_PATH, usage)
    try:
        client = anthropic.Anthropic(timeout=20, max_retries=0)
        resp = client.messages.create(model=model(), max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in resp.content if b.type == "text")
        with store.lock_for(USAGE_PATH):
            current = _load_usage()
            if current["day"] == usage["day"]:
                current["input_tokens"] += resp.usage.input_tokens
                current["output_tokens"] += resp.usage.output_tokens
                current["cache"][key] = text
                current["cache"] = dict(list(current["cache"].items())[-100:])
                store.save(USAGE_PATH, current)
        return {"text": text, "cached": False, "ai": True, "quantitative_source": False}
    except Exception as error:
        # An ambiguous timeout can be billed; never retry it automatically.
        raise ValueError("AI-forklaring fejlede: "+type(error).__name__+". Budgetreservation beholdes.") from None
