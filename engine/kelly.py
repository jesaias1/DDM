"""
Kelly-kriteriet — den matematiske kerne i "hvor meget af puljen skal på hver ting".

Kelly fortæller hvilken ANDEL af din bankroll du skal satse for at maksimere
den langsigtede vækstrate uden at gå bankerot. Vi bruger ALTID fraktioneret
Kelly (en brøkdel af det fulde Kelly-bud), fordi fuld Kelly svinger voldsomt og
en enkelt fejlvurdering kan halvere puljen. Standard her er 1/4 Kelly.

To former:
  - binær (sportsbet): du vinder odds, eller taber indsatsen.
  - kontinuert (aktie/krypto): position med forventet afkast og volatilitet.
"""

# Hvor stor en brøkdel af det fulde Kelly-bud vi tør bruge. Lavere = mere forsigtig.
DEFAULT_KELLY_FRACTION = 0.25

# Hårdt loft: ingen enkelt position må nogensinde være mere end dette af puljen.
MAX_POSITION_FRACTION = 0.20


def binary_kelly(win_prob: float, decimal_odds: float,
                 kelly_fraction: float = DEFAULT_KELLY_FRACTION) -> float:
    """
    Kelly-andel for et binært væddemål.

    win_prob      : DIN estimerede sandsynlighed for at vinde (0-1).
    decimal_odds  : europæiske/decimal-odds, fx 2.50 (indsats * odds = udbetaling).

    Returnerer andelen af puljen der bør satses (0 hvis ingen edge).

    Formel: f* = (p*b - (1-p)) / b,  hvor b = decimal_odds - 1.
    Hvis f* <= 0 er der ingen positiv forventning -> satser intet.
    """
    b = decimal_odds - 1.0
    if b <= 0 or not (0.0 < win_prob < 1.0):
        return 0.0
    edge = win_prob * b - (1.0 - win_prob)
    f_star = edge / b
    if f_star <= 0:
        return 0.0
    return min(f_star * kelly_fraction, MAX_POSITION_FRACTION)


def continuous_kelly(expected_return: float, volatility: float,
                     kelly_fraction: float = DEFAULT_KELLY_FRACTION) -> float:
    """
    Kelly-andel for et kontinuert aktiv (aktie/krypto) over én periode.

    expected_return : forventet afkast for perioden, fx 0.03 = +3%.
    volatility      : standardafvigelse på afkastet for samme periode.

    Formel (Merton): f* = forventet_afkast / varians = mu / sigma^2.
    Negativt forventet afkast -> ingen position (vi shorter ikke her).
    """
    if volatility <= 0 or expected_return <= 0:
        return 0.0
    f_star = expected_return / (volatility ** 2)
    if f_star <= 0:
        return 0.0
    return min(f_star * kelly_fraction, MAX_POSITION_FRACTION)


def implied_probability(decimal_odds: float) -> float:
    """Markedets implicitte sandsynlighed = 1/odds (inkl. bookmakerens margin)."""
    if decimal_odds <= 0:
        return 0.0
    return 1.0 / decimal_odds


def remove_vig(odds_list: list[float]) -> list[float]:
    """
    Fjern bookmakerens margin ('vig') fra et sæt odds for samme kamp, så de
    implicitte sandsynligheder summer til præcis 1. Det giver markedets BEDSTE
    bud på de 'fair' sandsynligheder — vores nulpunkt for at lede efter value.
    """
    implied = [implied_probability(o) for o in odds_list]
    total = sum(implied)
    if total <= 0:
        return implied
    return [p / total for p in implied]
