# Den Danske Metode

Lokal sportsintelligens med oddsjournal, deterministisk sandsynlighed/EV, konservativ risiko og en separat kryptoterminal. **Der er endnu ingen dokumenteret betting-edge.** PAPER er standard for afproevning; REAL-sport sender ingen bookmaker-ordrer.

## Online-demo paa Vercel

Vercel bruger `cloud.server:app`, ikke den lokale `app.py`. Online-versionen er en separat, skrivebeskyttet DEMO uden konto-/journal-synkronisering, provider-kald, API-noeglelagring, boersordrer eller baggrundsbot. Den lokale funktionalitet er uændret.

Online-login kraever separate Vercel-miljoevariabler: `DDM_CLOUD_USER`, `DDM_CLOUD_PASS` (mindst 20 tegn) og `DDM_CLOUD_SESSION_SECRET` (mindst 32 tegn). Ingen standardkode accepteres i cloud. Gem aldrig disse i Git. Preview-deployments kraever deres egne miljoevariabler; deployment protection skal beholdes.

En rigtig online-journal kraever permanent ekstern database og en separat worker eller en sikret forbindelse til stationaeren. Lokal SQLite og nøgler uploades ikke. Vercel-projektet er koblet til GitHub-repoet for kommende deployments.

## Start paa Windows

Python 3.10 eller nyere og internet til installationen:

```powershell
.\INSTALL_DDM.ps1
.\START_DDM.ps1
```

Aabn http://127.0.0.1:5000. Standardlogin: jesaias / miebs112. Saet DDM_USER/DDM_PASS i .env.local.ps1 for at aendre det. Kun localhost/127.0.0.1 accepteres. Porten kan aendres med DDM_PORT. PC'en skal forblive taendt og uden sleep ved baggrundsdrift.

## Et meningsfuldt foerste forloeb

1. DEMO viser deterministiske eksempelpriser, tydeligt adskilt fra virkelig performance. Tilfoej et valgfrit virtuelt EUR-beloeb under Portefolje og scan igen.
2. Tilfoej en The Odds API-noegle under Indstillinger. AI-noegler er ikke noedvendige for beregninger.
3. Vaelg PAPER, registrer en virtuel pulje og scan. EXPERIMENT giver WATCH/PASS. Saet strategien til PAPER for at afproeve kvalificerede signaler.
4. Registrer paper-bets fra analysen, eller start PAPER-drift under Strategier. Risiko og priser kontrolleres igen ved hver registrering.
5. Hent resultater i Portefolje. Automatisk settlement understottes for de eksplicit valgte almindelige fodboldligaer; oevrige sportsgrene/resultater registreres manuelt. Ingen tilfaeldige udfald bruges i sportsjournalen.
6. CLV kraever faktisk observerede priser lige foer kampstart. Manglende lukkepriser forbliver tomme. Et 15-minutters scaninterval kan derfor ofte mangle CLV; dataindsamling skal planlaegges og budgetteres derefter.

DEMO, PAPER og REAL har egne puljer, positioner og resultater. Ingen saldo er automatisk sat til 200 EUR. Tilfoej pulje er kun regnskab; siden modtager ikke crypto eller penge.

## Den kvantitative metode

Komplette 2-/3-vejs h2h-markeder med eksakte event-/udfaldsidentiteter. Alle gyldige bookmakerpriser bevares, inklusive source, received_at og last_update. Ukomplette, mistaenkelige, fremtidige og for gamle priser afvises eller saettes i karantaene. Exchanges uden modelleret kommission/likviditet bruges ikke.

Marginfjernelse: proportional, power og Shin. Power er den forhaandsvalgte reference; de andre bruges til foelsomhed. Det er et modelvalg, ikke en dokumenteret universel forbedring. Eksempelberegninger er kontrolleret mod [implied-pakkens dokumentation](https://cran.mirror.garr.it/mirrors/CRAN/web/packages/implied/vignettes/introduction.html).

Markedskonsensus udelukker den bookmaker, der tilbyder den analyserede pris. En eksperimentel Poisson-model kan bruge importerede fodboldresultater, men kun resultater som var tilgaengelige foer beslutningen. Ingen skader, nyheder, opstillinger eller statistikker opfindes.

EV per indsatsenhed = p * decimalodds - 1. Fair odds = 1/p. Minimumsodds bruger konservativ p og kraever 2% EV. Kelly-score = 100 * fuld Kelly ved konservativ p, **ikke** en valideret sandsynlighed for profit. Usikkerhedsbufferen er metodefoelsomhed, **ikke et statistisk konfidensinterval**. Bogdaekning A-D er ikke likviditet; likviditet er ukendt.

Default risiko: 1/4 Kelly; maks. 1% pr. bet, 2% pr. event, 3% pr. hold, 4% pr. liga, 5% pr. sport/dag, 10% samlet og 100 aabne bets. Samme event/hold behandles konservativt som koncentreret eksponering. Ingen martingale eller tabsjagt.

REAL/LIVE for sport kraever mindst 500 provider-afgjorte PAPER-bets i den aktuelle model/strategiversion, mindst 100 CLV-observationer, positiv gennemsnitlig CLV, positiv nedre cluster-bootstrap ROI-graense og Brier mindst paa niveau med markedet. Denne adgangsport beviser ikke fremtidig profit. REAL er stadig manuel registrering, ingen sportsbook-integration.

## Resultater og evaluering

Den gamle /api/backtest med syntetiske priser er pensioneret (HTTP 410). Strategilab bruger importerede, daterede data og giver ingen profitgaranti.

- Uforanderlige odds-snapshots og beslutninger i data/ddm.sqlite3. Settlement kan ikke overskrives; annullering refunderer indsatsen.
- CLV = taget decimalodds / samme bookmakers observerede lukkeodds - 1. Det er pris-CLV, ikke no-vig EV. Kun faktisk indsamlede quotes hoejst 300 sekunder foer kampstart bruges.
- Brier, log loss og ECE paa foerste pre-match signal per kamp/udfald/model, ogsaa WATCH/PASS. BET-performance vises separat. Multiklasse-Brier fra strategilab har en anden skala end binaer selection-Brier.
- ROI-intervaller resampler event-clustre ved mindst 30 afgjorte events. Korrelationsafhaengighed mellem forskellige kampe er stadig en begraensning.
- Indbetalinger er ikke profit. Equity-kurven bruger de faktiske regnskabstidspunkter; drawdown korrigeres for tilfoert kapital.
- Monte Carlo er betinget paa modelsandsynligheder. Samme events udfald er gensidigt udelukkende, forskellige events antages uafhaengige. Modelfejl og ukendt korrelation kan goere den virkelige risiko stoerre.
- Historik er soegbar, sorterbar, pagineret og kan eksporteres som CSV. Gemte visninger findes lokalt i browseren.

## Historiske data og strategilab

Resultat-CSV bruger: id, league, home, away, start, available_at, home_goals, away_goals, source. Tider skal vaere UTC-tal eller ISO8601 med tidszone. available_at er tidspunktet, hvor resultatet faktisk blev tilgaengeligt, ikke blot kickoff.

Historisk odds-JSON bruger The Odds API-eventformat plus received_at. Event-id, hold, liga og kampstart skal matche resultaterne. Odds observeret efter start afvises. API-formatet foelger [udbyderens dokumentation](https://the-odds-api.com/liveapi/guides/v4/).

Mindst 300 resultater kraeves; en realistisk liga kan behoeve mange flere for at opfylde minimumshistorik pr. hold. Split er kronologisk 60/20/20. Modellen opdaterer kun med tidligere kendte resultater; isotonic kalibrering fit'es kun paa validation og rapporteres paa holdout. Den aktiveres ikke automatisk i runtime.

Replay bruger seneste observerede pris mindst 60 minutter foer start; udloebne quotes afvises. Pengene frigives foerst ved available_at. Syntetiske crypto-forloeb beviser ikke en sports-edge. EV-undergrupper er kun eksplorative med train-only udvaelgelse og korrektion for fire tests; ingen automatisk LIVE-forfremmelse.

Samme datasethash/model genbruger en frossen evaluering. Incrementer model-/feature-/strategiversioner ved logikaendringer. Frys et nyt, endnu uset holdout-datasaet foer nye hypoteser; software kan ikke forhindre menneskelig overfitting efter gentagen inspektion. Coverage/survivorship, tidsstempelkvalitet og manglende historiske tilbudsgraenser er uafklarede datarisici.

## Nogle vigtige driftsforhold

Feedbudget er 24 API-kald pr. UTC-dag som standard, faelles for odds og resultater. Det er antal forespoergsler, ikke udbyderens kreditberegning. PAPER-interval er 900 sekunder (minimum 300). Budget reserveres foer request; fejl returneres og logges uden API-noegler. Ingen demo-fallback ved feedfejl.

AI er kun en valgfri manuelt startet forklaring af eksisterende data. Kvantitative beregninger bruger 0 AI-tokens. Anthropic har kallofter og forudreserveret tokenbudget; ingen web-sogning eller automatiske retries. OpenAI/Gemini bruges ikke. Provider-fakturering er ekstern; appen garanterer ikke et absolut monetart faktureringsloft.

Paa Windows gemmes API-noegler DPAPI-krypteret, bundet til bruger/maskine; tidligere klartekstsettings migreres ved opstart. Zip indeholder aldrig noegler eller regnskab. Indtast noegler igen paa en anden PC. Paa andre platforme bruges miljoevariabler til noegler.

## Krypto

/crypto bevarer Coinbase/ccxt-motoren, men den er en **eksperimentel momentum-strategi uden dokumenteret edge**. Live kraever DDM_LIVE=1, DDM_LIVE_ARMED=JEG_FORSTAAR_RISIKOEN og boersnoegler. Boersnoegler laeses fra miljoet. Ingen withdrawals understottes.

Brug noegler uden withdraw/transfer-rettigheder. Live-saldo/prisfejl stopper operationen; paper-positioner kan ikke handles som live. En ordreintention gemmes foer submission. Timeout, ukendt fee/status eller ukendt partial fill blokerer automatisk gentagelse. Ved uafklaret ordre skal du afstemme boersens historik og journalen manuelt; der er ingen automatisk reconciliation. Markedsordrer kan overskride forventet pris pga. slippage. Ingen reel ordre er valideret af vores tests.

Kill switch stopper drift og bevarer usolgte positioner ved fejl. Stop overlever midnat. Appen opretter en processlaas og binder HTTP-porten foer genoptagelse af scheduler, saa en ekstra server ikke starter en ekstra handelsmotor.

## Verifikation og backup

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m compileall -q app.py engine
.\PACKAGE_DDM.ps1
```

Tests bruger isolerede SQLite-filer, kontrollerede historiske data og mocks; ingen rigtige vaeddemaal/boersordrer. Til backup af journalen bruges SQLite backup-API eller en lukket app; kopier ikke kun hovedfilen mens WAL er aktiv. Bevar eksisterende data/ paa samme maskine ved opgraderinger. Gamle JSON-simulationer importeres ikke til den nye sports-performance.

Se docs/ARCHITECTURE.md for audit, modulansvar og praecise begraensninger.
