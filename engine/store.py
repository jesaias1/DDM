"""
Delt, trådsikker JSON-persistens.

Når baggrunds-scheduleren kører cyklusser SAMTIDIG med at du klikker i browseren,
skriver to tråde til de samme state-filer. Uden beskyttelse kan filen blive halvt
skrevet (korrupt) eller en opdatering gå tabt. Dette modul giver:

  • atomisk skrivning (skriv til temp-fil, byt så ind) — en læser ser enten den
    gamle eller den nye fil, aldrig en halvskreven.
  • en lås pr. fil — så load→ændr→gem kører udelt.

Brug `with lock_for(path):` omkring en hel læs-ændr-gem-sekvens.
"""
import os
import json
import threading

_locks: dict[str, threading.RLock] = {}
_registry_lock = threading.Lock()


def lock_for(path: str) -> threading.RLock:
    """Hent (eller opret) den genindgangs-lås der hører til en bestemt fil."""
    key = os.path.abspath(path)
    with _registry_lock:
        if key not in _locks:
            _locks[key] = threading.RLock()
        return _locks[key]


def load(path: str):
    """Læs JSON, eller None hvis filen ikke findes."""
    if not os.path.exists(path):
        return None
    with lock_for(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)


def save(path: str, obj) -> None:
    """Gem JSON atomisk: skriv temp + os.replace (atomisk på samme drev)."""
    with lock_for(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
