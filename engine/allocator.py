"""
Allokator: fordeler puljen (fx 200 kr) på tværs af alle muligheder.

Tager rå muligheder fra markeds- og sports-modulerne, beregner en Kelly-andel for
hver, og omsætter det til konkrete kronebeløb — med to sikkerhedsregler:

  1. Kontant-buffer: en fast andel af puljen røres aldrig (tørt krudt + dæmper risiko).
  2. Samlet eksponering: summen af alle Kelly-andele skaleres ned hvis den
     overstiger det tilladte, så vi aldrig over-allokerer.

Det er her "AI bestemmer selv hvor meget på hver ting" bliver til faktiske beløb.
"""
from . import kelly

CASH_BUFFER = 0.20          # rør aldrig de sidste 20% af puljen
MAX_TOTAL_EXPOSURE = 0.80   # maks 80% af puljen ude at arbejde ad gangen
MIN_STAKE = 5.0             # under 5 kr er ikke besværet værd


def allocate(bankroll: float, opportunities: list[dict]) -> list[dict]:
    """
    Returnér en liste af konkrete handlinger:
      { ...mulighed, kelly_fraction, stake_dkk }
    sorteret efter størst Kelly-andel (stærkest overbevisning) først.
    """
    scored = []
    for opp in opportunities:
        if "kelly_fraction" in opp:            # sport/polymarket: binær Kelly er allerede regnet
            frac = opp["kelly_fraction"]
        else:                                  # market (krypto): kontinuert Kelly
            frac = kelly.continuous_kelly(opp["expected_return"], opp["volatility"])
        if frac > 0:
            scored.append({**opp, "kelly_fraction": frac})

    if not scored:
        return []

    # Skalér ned hvis den samlede Kelly-eksponering er for høj.
    total_frac = sum(s["kelly_fraction"] for s in scored)
    investable = bankroll * MAX_TOTAL_EXPOSURE
    scale = min(1.0, investable / (bankroll * total_frac)) if total_frac > 0 else 0.0

    actions = []
    deployed = 0.0
    for s in sorted(scored, key=lambda x: x["kelly_fraction"], reverse=True):
        stake = bankroll * s["kelly_fraction"] * scale
        # Respektér kontant-buffer: stop når vi nærmer os den.
        if deployed + stake > bankroll * (1 - CASH_BUFFER):
            stake = bankroll * (1 - CASH_BUFFER) - deployed
        if stake < MIN_STAKE:
            continue
        deployed += stake
        actions.append({**s, "stake_dkk": round(stake, 2)})
    return actions
