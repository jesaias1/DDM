"""
Simpel login til den lokale app.

Adgangskode gemmes aldrig i klartekst i en fil — den hashes ved opstart. Brugernavn
og kode kan overstyres med miljøvariablerne DDM_USER / DDM_PASS;
ellers bruges standarden.

Session-nøglen persisteres i data/secret.key, så du forbliver logget ind på tværs
af genstarter (men nøglen er unik for din maskine).
"""
import os
from werkzeug.security import generate_password_hash, check_password_hash

USERNAME = os.environ.get("DDM_USER", os.environ.get("SMARTSTAKE_USER", "jesaias"))
_PASSWORD = os.environ.get("DDM_PASS", os.environ.get("SMARTSTAKE_PASS", "miebs112"))
_HASH = generate_password_hash(_PASSWORD)

_SECRET_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "secret.key")


def check(username: str, password: str) -> bool:
    return username == USERNAME and check_password_hash(_HASH, password)


def secret_key() -> str:
    """Hent (eller opret) den persistente session-nøgle."""
    if os.path.exists(_SECRET_PATH):
        with open(_SECRET_PATH, encoding="utf-8") as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(_SECRET_PATH), exist_ok=True)
    key = os.urandom(32).hex()
    with open(_SECRET_PATH, "w", encoding="utf-8") as f:
        f.write(key)
    return key
