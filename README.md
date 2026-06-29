# Den Danske Metode

En lokal AI-/kvant-beslutningsmotor til højrisiko krypto og paper-trading. Appen har login, dansk dashboard, simulator, baggrundskørsel, Coinbase/ccxt-børsforbindelse og en kill switch.

Det vigtigste først: dette er ikke en pengemaskine. Momentum i krypto har perioder hvor det virker, og lange perioder hvor gebyrer, støj og faldende markeder æder kanten. Du kan tabe hele beløbet. Brug tør-kørsel og backtest før du sætter rigtige penge på.

## Kom i gang

```powershell
pip install -r requirements.txt
python app.py
```

Åbn http://localhost:5000 og log ind.

Standard-login:

```text
jesaias / miebs112
```

Du kan ændre login med:

```powershell
$env:DDM_USER = "nyt-brugernavn"
$env:DDM_PASS = "ny-adgangskode"
```

## Hvad er forbedret

- Fælles strategi-kerne til live, tør-kørsel og backtest.
- Trend-filter: køber kun når prisen ligger over sit 50-dages glidende gennemsnit.
- Gebyrbuffer: signaler skal være stærke nok til cirka at bære ind- og ud-gebyr.
- Trailing stop: vindere får lov at løbe, men beskyttes efter en ny top.
- Hard stop-loss: standard er -8 procent.
- Cooldown efter exit, så botten ikke straks køber samme par tilbage efter et stop.
- Paper-trading bruger nu også handelsgebyrer, så simulatoren ikke pynter på tallene.
- Coinbase er standardbørs, men alle ccxt-børser kan bruges.

## Rigtig krypto med Coinbase

Appen opbevarer ikke penge. Du indbetaler til din egen Coinbase-konto, og botten handler med saldoen via en API-nøgle.

Sikkerhedsreglen er enkel: opret API-nøglen med handelstilladelse, men aldrig udbetaling/withdraw. Så kan appen ikke flytte penge ud af kontoen.

Eksempel:

```powershell
$env:EXCHANGE_ID = "coinbase"
$env:EXCHANGE_API_KEY = "din-noegle"
$env:EXCHANGE_API_SECRET = "din-secret"
$env:DDM_LIVE = "1"
$env:DDM_LIVE_ARMED = "JEG_FORSTAAR_RISIKOEN"
$env:DDM_QUOTE = "EUR"
```

Nogle API-typer kræver også passphrase/password:

```powershell
$env:EXCHANGE_API_PASSPHRASE = "din-passphrase"
```

Standard-univers:

```text
BTC/EUR, ETH/EUR, SOL/EUR, ADA/EUR, LINK/EUR
```

Kan ændres med:

```powershell
$env:DDM_UNIVERSE = "BTC/EUR,ETH/EUR,SOL/EUR"
```

## Indbetaling

Fanen Indbetal kan hente en deposit-adresse fra børsen, hvis din API-nøgle har funding/deposit-adgang. Du kan også finde adressen manuelt i Coinbase under indbetaling/deposit.

Brug altid korrekt netværk for den coin du sender. Forkert netværk kan betyde tabte midler.

## Strategi-parametre

Alle kan justeres uden kodeændringer:

```powershell
$env:DDM_FEE = "0.006"
$env:DDM_TREND_LEN = "50"
$env:DDM_STOP_LOSS = "-0.08"
$env:DDM_TRAIL = "0.12"
$env:DDM_ARM = "0.05"
$env:DDM_COOLDOWN_SECONDS = "21600"
```

Legacy `SMARTSTAKE_*` miljøvariabler virker stadig, men `DDM_*` er det nye navn.

## Nattekørsel

Hvis målet er at starte botten om aftenen og se resultatet om morgenen:

1. Start appen.
2. Log ind.
3. Kør Preflight i dashboardet.
4. Tjek at den siger klar til live-handel.
5. Start Autonom drift med Auto-trader slået til.
6. Lad PC'en være tændt, på strøm og uden sleep.

Risikobremsen stopper nye køb hvis puljen rammer standardgrænserne:

```powershell
$env:DDM_DAILY_LOSS_LIMIT = "-0.05"        # stop ved -5% på dagen
$env:DDM_TOTAL_LOSS_LIMIT = "-0.10"        # stop ved -10% samlet
$env:DDM_AUTO_FLATTEN_ON_HALT = "1"        # luk åbne positioner når loft rammes
```

Hvis bremsen rammes, kan den ophæves manuelt i dashboardet. Det bør kun gøres efter du har set hvorfor den stoppede.

Til første live-test er standardprofilen bevidst lille:

- maks 25 EUR pr. live-køb
- maks 2 køb pr. dag
- maks 2 åbne positioner
- canary-mode: første live-køb maks 10 EUR

Det kan ændres i Settings, men lad det gerne være konservativt første nat.

## Sport og gambling

Sportsdelen er kun anbefalinger/simulering. Bettingsider har typisk ikke lovlige offentlige APIs til auto-betting, og bots kan bryde vilkår. Brug ROFUS hvis spil bliver et problem.

## Settings og AI-nøgler

Fanen Settings kan gemme lokale API-nøgler i `data/settings.json`. Filen er git-ignoreret og kommer ikke med i zip-pakken.

Krypto-botten bruger **0 AI-tokens**. Den køber/sælger ud fra markedsdata, trendfilter, trailing stop og risikostyring.

AI-research er slået fra som standard. Hvis du slår det til for sport/gamble-scouting, stopper appen automatisk ved dine grænser:

- max AI-kald pr. dag
- tokenbudget pr. dag
- web-søgning til/fra
- max output pr. kald

OpenAI og Gemini kan gemmes i Settings, men bruges ikke af motoren endnu. De kan derfor ikke bruge tokens i den nuværende version.

Der kan stadig opstå små afvigelser mellem appens tokenoptælling og udbyderens fakturering. Sæt derfor også gerne spending limits hos AI-udbyderen selv, hvis de tilbyder det.

Aktivt understøttet lige nu:

- `ANTHROPIC_API_KEY`: Claude AI-research til sport.
- `ODDS_API_KEY`: live sports-odds.

Kan gemmes til senere udvidelser, men bruges ikke af motoren endnu:

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`

Krypto-botten kræver ikke AI-nøgler. Den bruger Coinbase/ccxt API-nøgler til read + trade.

## Test

```powershell
python -m unittest discover -s tests
```

Testene dækker Kelly-matematik, allokering, atomisk JSON-persistens og auto-traderens tør-kørselslivscyklus med trailing stop.
