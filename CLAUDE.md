# Den Danske Metode: projektkontekst

Laes README.md og docs/ARCHITECTURE.md. Svar brugeren paa dansk.

Primært: lokal Flask/SQLite sportsintelligens. UI i templates/dashboard.html og static/terminal*. Krypto-view i static/crypto-terminal.js; Coinbase-motor i engine/autotrader.py/exchange.py.

Ingen dokumenteret edge. LLM maa aldrig levere sandsynligheder, odds, historik eller indsats. AI kun valgfri kommentar. DEMO/PAPER/REAL/BACKTEST er adskilt. REAL sport er manuel registrering og sender ingen bookmaker-ordrer.

Kernen: feeds.py (identitet/tid/kvote), quant.py (vig/EV/Kelly/CLV/evaluering), database.py (immutable journal), intelligence.py (beslutning/risk/settlement), risk.py, models.py (Poisson/marked), lab.py (kronologisk replay/holdout), terminal_api.py.

Kryptomotoren er eksperimentel, ikke valideret profit. Respekter live-gates, pending-order journal, mode-adskillelse og processlaas. Uafklarede ordrer maa aldrig automatisk gentages eller slettes.

Noegler og data er gitignored og aldrig pakket. Windows-noegler er DPAPI-krypteret. Bevar alle eksisterende regnskaber, også tab. Incrementer model/strategiversion ved algoritmeaendringer. Ingen commit uden brugerens anmodning.

Tests: python -m unittest discover -s tests. Start med INSTALL_DDM.ps1 / START_DDM.ps1. Python >=3.10, frontend kraever ingen Node-runtime. Kun process.main starter scheduleren; den bindes foerst til en ledig port.
