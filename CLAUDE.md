# Den Danske Metode — projekt-kontekst

Læs denne fil først. Den giver en ny samtale nok til at fortsætte arbejdet.
Brugeren skriver dansk — svar på dansk, og hold hele hjemmesiden på dansk.

## Hvad er det

En lokal Flask-app (kører på brugerens egen maskine) med to dele:
1. **Krypto auto-trader** — handler RIGTIGE penge autonomt på en krypto-børs
   (Coinbase som standard, via ccxt). Momentum + Kelly. Det er kerneproduktet.
2. **Sports-anbefalinger** — foreslår value-bets (fx VM). Placerer ALDRIG et
   væddemål automatisk (bettingsider forbyder bots) — brugeren handler selv.

## Ærlig ramme (vigtig — brugeren har accepteret den)

Det er en "sjovere, sikrere måde at gamble på med højere chance end slots" —
IKKE en pengemaskine. Edgen er tynd; forventningen er neutral-til-svagt-negativ
efter gebyrer. Vær altid ærlig om dette. Lov aldrig profit. Stå inde for HVORDAN
det virker (mekanisk), ikke for AT det tjener penge. Brugeren ved chancen er lav.

## Sådan kører man det

- Installér: `.\INSTALL_DDM.ps1`  (kræver Python på maskinen)
- Start: `.\START_DDM.ps1`  → http://127.0.0.1:5000  → login: jesaias / miebs112
- Tests: `python -m unittest discover -s tests`  (11 tests, skal være grønne)
- Gå-live-tjek: `python check_live.py`  (validerer env + preflight + readiness)
- Env-vars sættes i `.env.local.ps1` (kopi af `DDM_ENV_TEMPLATE.ps1`, gitignored)

## Arkitektur (engine/)

- `strategy.py` — ÉN kilde til handelslogik: trend-filter (SMA), trailing stop,
  stop-loss, gebyr/net-edge-filter, cooldown. Bruges af både live og backtest.
- `exchange.py` — ccxt-børs. Tre-trins live-gate, preflight, min-ordre/precision,
  deposit-adresse. KUN trade-rettigheder forventes (aldrig withdraw).
- `autotrader.py` — live cyklus, risikobremser (dagligt/total tabsloft, auto-flatten),
  canary-køb, dags-/positionslofter, kill switch (flatten), readiness().
- `scheduler.py` — autonom baggrundsloop; overlever genstart (data/scheduler.json).
- `store.py` — trådsikker, atomisk JSON-persistens (deles af alle moduler).
- `kelly.py`, `allocator.py` — sizing (fraktioneret Kelly + caps, kontant-buffer).
- `sports.py` — odds (the-odds-api), value-detektion. Sport via `DDM_SPORT`.
- `research.py` — valgfri Claude-web-research til sport (token-budget i Settings).
- `markets.py` — CoinGecko-signaler til simulatoren (paper).
- `backtest.py` — syntetisk backtest med samme strategi (ærlig risikoprofil).
- `settings.py`, `auth.py` — runtime-indstillinger og login (hashet kode).

`app.py` = Flask-ruter. `templates/` = login + faneopdelt dashboard
(Auto-trader / Indbetal / Simulator / Anbefalinger / Settings).

## Sikkerhedsdesign (rør ikke uden grund)

- Live kræver TRE ting: `DDM_LIVE=1` + `DDM_LIVE_ARMED=JEG_FORSTAAR_RISIKOEN` + nøgler.
  Ellers TØR-KØRSEL (ægte priser, ingen ordrer).
- Canary: første køb capped lille. Lofter: max stake/ordre, køb/dag, åbne positioner.
- Risikobremse: −5%/dag, −10%/total → stopper handel (DDM_DAILY/TOTAL_LOSS_LIMIT).
- Kill switch sælger alt. Krypto-botten bruger 0 AI-tokens.
- API-nøgler kun trade (aldrig withdraw): botten kan ikke flytte penge ud; kun
  brugeren selv kan hæve via Coinbase.

## Vigtige env-vars

EXCHANGE_ID (coinbase), DDM_QUOTE (EUR), DDM_UNIVERSE, EXCHANGE_API_KEY/SECRET,
DDM_LIVE, DDM_LIVE_ARMED, DDM_DAILY_LOSS_LIMIT, DDM_TOTAL_LOSS_LIMIT,
DDM_SPORT (fx soccer_fifa_world_cup), ANTHROPIC_API_KEY, ODDS_API_KEY.

## Status / plan

MVP committet og virker (tests grønne, dry-run + login + endpoints verificeret).
Brugeren planlægger at indbetale ~200 kr på Coinbase d. 1. i måneden og køre det
LIVE på sin stationære PC (autonomt). Brugervendte guides i mappen:
`KOM_GODT_IGANG_D1.txt`, `HUSKELISTE.txt`, `SPORTS_ANBEFALINGER_GUIDE.txt`.

## Konventioner

- `data/` (state, secret.key) er gitignored og maskine-lokal — commit den aldrig.
- Commit kun når brugeren beder om det. Hold ændringer testet (kør unittest).
- Sport auto-betting bygges IKKE (ToS + ulovligt via API). Kun anbefalinger.
