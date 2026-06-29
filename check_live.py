"""
"Gå live"-tjek — kør FØR du armer rigtige penge.

    python check_live.py

Validerer dine miljøvariabler, kører preflight mod Coinbase (uden at sende
ordrer) og readiness-tjekket. Sender ALDRIG en ordre. Slutter med exit-kode 0
hvis alt er grønt, ellers 1 — så du kan se sort på hvidt om maskinen er klar.
"""
import os
import sys

# Sørg for at æøå og pile kan skrives uanset Windows-konsollens kodning.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from engine import exchange, autotrader


def mark(ok: bool) -> str:
    return "[ OK ]" if ok else "[FEJL]"


def mask(v: str | None) -> str:
    return f"{v[:4]}...({len(v)} tegn)" if v else "(ikke sat)"


def main() -> int:
    line = "=" * 56
    print(f"\n{line}\n  DEN DANSKE METODE - GAA-LIVE TJEK\n{line}\n")

    print("Miljovariabler:")
    rows = [
        ("EXCHANGE_ID", os.environ.get("EXCHANGE_ID") or os.environ.get("DDM_EXCHANGE_ID") or "coinbase (standard)"),
        ("DDM_LIVE", os.environ.get("DDM_LIVE") or os.environ.get("SMARTSTAKE_LIVE") or "(ikke sat)"),
        ("DDM_LIVE_ARMED", os.environ.get("DDM_LIVE_ARMED") or "(ikke sat)"),
        ("EXCHANGE_API_KEY", mask(os.environ.get("EXCHANGE_API_KEY"))),
        ("EXCHANGE_API_SECRET", mask(os.environ.get("EXCHANGE_API_SECRET"))),
    ]
    for name, val in rows:
        print(f"  {name:22} {val}")

    print("\nPreflight (sender ingen ordrer):")
    pf = exchange.preflight()
    for c in pf["checks"]:
        print(f"  {mark(c['ok'])}  {c['name']:14} {c['message']}")
    if pf.get("missing_symbols"):
        print(f"         Manglende par: {', '.join(pf['missing_symbols'])}")

    print("\nReadiness (sikkerhedsprofil):")
    rd = autotrader.readiness()
    for c in rd["checks"]:
        print(f"  {mark(c['ok'])}  {c['name']:18} {c['message']}")

    ready = bool(pf.get("can_trade")) and bool(rd.get("ok"))
    print(f"\n{line}")
    if ready:
        print("  KLAR - maskinen er klar til en lille live-test.")
        print("  Start kun med penge du kan taale at tabe helt.")
    else:
        print("  IKKE KLAR - ret de [FEJL]-markerede punkter ovenfor.")
        if not exchange.live_requested():
            print("  -> saet DDM_LIVE=1")
        if not exchange.live_armed():
            print(f"  -> saet DDM_LIVE_ARMED={exchange.LIVE_ARM_PHRASE}")
        if not exchange.keys_present():
            print("  -> saet EXCHANGE_API_KEY og EXCHANGE_API_SECRET (trade-kun, ALDRIG withdraw)")
    print(f"{line}\n")
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
