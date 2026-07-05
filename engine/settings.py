"""
Lokale indstillinger og API-nøgler.

Nøgler gemmes kun lokalt i data/settings.json. Filen er git-ignoreret og kommer ikke
med i stationær-pakken. Det er ikke en cloud-secret-manager, men det er praktisk til
en lokal maskine der kører botten.
"""
import importlib.util
import os

from . import store

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "settings.json")

KEYS = {
    "anthropic_api_key": {
        "env": "ANTHROPIC_API_KEY",
        "label": "Claude / Anthropic",
        "used_for": "AI-research på sport",
        "active": True,
        "package": "anthropic",
    },
    "openai_api_key": {
        "env": "OPENAI_API_KEY",
        "label": "OpenAI",
        "used_for": "Gemt til senere AI-udvidelser",
        "active": False,
        "package": None,
    },
    "gemini_api_key": {
        "env": "GEMINI_API_KEY",
        "label": "Gemini",
        "used_for": "Gemt til senere AI-udvidelser",
        "active": False,
        "package": None,
    },
    "odds_api_key": {
        "env": "ODDS_API_KEY",
        "label": "The Odds API",
        "used_for": "Live sports-odds",
        "active": True,
        "package": None,
    },
    "telegram_bot_token": {
        "env": "DDM_TELEGRAM_TOKEN",
        "label": "Telegram bot",
        "used_for": "Daglig status + handels-beskeder til mobilen",
        "active": True,
        "package": None,
    },
}

PUBLIC_DEFAULTS = {
    "ai_provider": "anthropic",
    "anthropic_model": "claude-haiku-4-5",
    "ai_research_enabled": False,
    "ai_web_search_enabled": False,
    "ai_daily_call_limit": 3,
    "ai_daily_token_budget": 12000,
    "ai_max_tokens_per_call": 800,
    "max_live_stake": 25.0,
    "max_daily_buys": 2,
    "max_open_positions": 2,
    "canary_mode": True,
    "canary_stake": 10.0,
    "telegram_chat_id": "",
    "notify_enabled": False,
    "notify_trades": True,
    "notify_daily_hour": 19,
    "polymarket_enabled": True,
}


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}...{value[-4:]}"


def _package_installed(name: str | None) -> bool:
    return True if not name else importlib.util.find_spec(name) is not None


def load() -> dict:
    return store.load(SETTINGS_PATH) or {}


def save(updates: dict) -> dict:
    with store.lock_for(SETTINGS_PATH):
        current = load()
        for key in KEYS:
            if updates.get(f"clear_{key}"):
                current.pop(key, None)
                continue
            if key not in updates:
                continue
            value = str(updates.get(key) or "").strip()
            if value:
                current[key] = value
        for key in PUBLIC_DEFAULTS:
            if key in updates:
                default = PUBLIC_DEFAULTS[key]
                if isinstance(default, bool):
                    current[key] = bool(updates.get(key))
                elif isinstance(default, int) and not isinstance(default, bool):
                    try:
                        current[key] = max(0, int(updates.get(key)))
                    except (TypeError, ValueError):
                        current[key] = default
                elif isinstance(default, float):
                    try:
                        current[key] = max(0.0, float(updates.get(key)))
                    except (TypeError, ValueError):
                        current[key] = default
                else:
                    value = str(updates.get(key) or "").strip()
                    current[key] = value or default
        store.save(SETTINGS_PATH, current)
    apply_to_env()
    return status()


def apply_to_env() -> None:
    current = load()
    for key, meta in KEYS.items():
        value = current.get(key)
        if value:
            os.environ[meta["env"]] = value
    model = current.get("anthropic_model")
    if model:
        os.environ["SMARTSTAKE_MODEL"] = model


def status() -> dict:
    current = load()
    providers = []
    for key, meta in KEYS.items():
        from_file = bool(current.get(key))
        from_env = bool(os.environ.get(meta["env"]))
        providers.append({
            "id": key,
            "label": meta["label"],
            "env": meta["env"],
            "used_for": meta["used_for"],
            "active": meta["active"],
            "configured": from_file or from_env,
            "source": "settings" if from_file else "environment" if from_env else None,
            "masked": _mask(current.get(key) or os.environ.get(meta["env"])),
            "package_ok": _package_installed(meta["package"]),
        })
    return {
        "providers": providers,
        "ai_provider": current.get("ai_provider", PUBLIC_DEFAULTS["ai_provider"]),
        "anthropic_model": current.get("anthropic_model", os.environ.get("SMARTSTAKE_MODEL", PUBLIC_DEFAULTS["anthropic_model"])),
        "ai_research_enabled": bool(current.get("ai_research_enabled", PUBLIC_DEFAULTS["ai_research_enabled"])),
        "ai_web_search_enabled": bool(current.get("ai_web_search_enabled", PUBLIC_DEFAULTS["ai_web_search_enabled"])),
        "ai_daily_call_limit": int(current.get("ai_daily_call_limit", PUBLIC_DEFAULTS["ai_daily_call_limit"])),
        "ai_daily_token_budget": int(current.get("ai_daily_token_budget", PUBLIC_DEFAULTS["ai_daily_token_budget"])),
        "ai_max_tokens_per_call": int(current.get("ai_max_tokens_per_call", PUBLIC_DEFAULTS["ai_max_tokens_per_call"])),
        "max_live_stake": float(current.get("max_live_stake", PUBLIC_DEFAULTS["max_live_stake"])),
        "max_daily_buys": int(current.get("max_daily_buys", PUBLIC_DEFAULTS["max_daily_buys"])),
        "max_open_positions": int(current.get("max_open_positions", PUBLIC_DEFAULTS["max_open_positions"])),
        "canary_mode": bool(current.get("canary_mode", PUBLIC_DEFAULTS["canary_mode"])),
        "canary_stake": float(current.get("canary_stake", PUBLIC_DEFAULTS["canary_stake"])),
        "telegram_chat_id": str(current.get("telegram_chat_id", PUBLIC_DEFAULTS["telegram_chat_id"])),
        "notify_enabled": bool(current.get("notify_enabled", PUBLIC_DEFAULTS["notify_enabled"])),
        "notify_trades": bool(current.get("notify_trades", PUBLIC_DEFAULTS["notify_trades"])),
        "notify_daily_hour": int(current.get("notify_daily_hour", PUBLIC_DEFAULTS["notify_daily_hour"])),
        "polymarket_enabled": bool(current.get("polymarket_enabled", PUBLIC_DEFAULTS["polymarket_enabled"])),
        "settings_path": SETTINGS_PATH,
        "note": "Krypto-botten bruger ingen AI-tokens. OpenAI og Gemini gemmes kun til fremtidige udvidelser; den nuværende AI-research bruger kun Claude/Anthropic og kun når AI-research er slået til.",
    }
