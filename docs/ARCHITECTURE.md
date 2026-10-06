# DDM: architecture and verification boundaries

## Audit and replacement

The inherited sports simulator used demo odds, unvalidated LLM estimates and random settlement. Its synthetic crypto backtest did not demonstrate a tradable edge. Live crypto could forget failed sells, assume unconfirmed fills, fall back to paper cash and restart a daily halt. These paths have been disabled or guarded. Legacy JSON records are retained, not imported into the new sports performance journal.

The new pipeline is provider -> complete timestamped snapshots -> no-vig probabilities -> leave-book-out comparison or historical Poisson -> uncertainty sensitivity -> price requirements -> transactional risk checks -> immutable decision -> paper/manual-real journal -> actual settlement -> same-book observed closing price -> CLV, calibration and return diagnostics.

DEMO is fabricated input for interface testing. PAPER uses the configured feed. REAL is a manual journal, not automatic sportsbook execution. A deposit is an accounting entry, not custody or a payment. Crypto is a separate experimental CCXT spot engine; funds remain on the exchange.

## Components

`database.py` uses SQLite WAL and serialized write transactions. Accounts, deposits, snapshots, decisions, bets and results are separated by mode. Decisions and snapshots are append-only. Allocation is rechecked inside the bet transaction; duplicate selections and idempotency conflicts are rejected.

`feeds.py` validates identity, complete outcomes, timestamps, freshness and margins. Exchange odds are excluded pending commission/liquidity modeling. Failures do not become demo data. A daily atomic counter bounds local requests; external provider credit pricing is separate.

`models.py` uses no LLM probabilities. Consensus excludes the offered bookmaker. Football estimates require dated historical results and shrink sparse samples toward league priors. The lower probability is a sensitivity buffer, not a statistically calibrated confidence interval. Injury, lineup and liquidity information is not inferred.

`risk.py` limits individual bets and event, team, league, sport, day and total exposure using fractional Kelly and cash-only allocation. Correlated event selections are not treated as independent.

`intelligence.py` owns BET/WATCH/PASS, expiry, settlement and portfolios. Scheduling registers PAPER bets only. LIVE strategy eligibility requires substantial provider-settled PAPER evidence for the current market-model version, positive CLV, a positive clustered return interval and calibration checks. Passing is not proof of future profitability and does not enable sportsbook execution.

`lab.py` imports attributed results and odds. Results must have been available before prediction. Chronological train/validation/holdout splitting avoids random-split leakage. Validation-only isotonic calibration is reported, not silently installed. Entry-price replay respects exposure and delayed settlement. Four predeclared edge buckets offer exploratory discovery with a multiple-testing penalty, never automatic promotion.

`research.py` provides optional manual, cached explanations of recorded facts. Worst-case token and call reservations are persisted before requests, including ambiguous failures. Only Claude is connected; stored OpenAI/Gemini keys are not active integrations. Local limits cannot guarantee an external billing account never incurs charges from another client or delayed billing.

`process_lock.py` and Waitress enforce one local worker. The scheduler prevents overlapping threads. Windows DPAPI encrypts keys for the current Windows user; moving ciphertext to another PC is unsupported. Authentication, CSRF, local host checks and masked keys protect the local interface. This is not an internet-facing deployment configuration.

## Evidence Still Needed

- Real pre-match multi-book data, independently sourced results and dated historical odds. DEMO profitability is irrelevant.
- Repeated walk-forward evaluation, an untouched prospective holdout and reconciliation against provider statements. A fixed chronological split is not a full walk-forward service.
- Measured liquidity, limits, fees, slippage and executable quote availability. Coverage is not liquidity.
- Validated injury/player models, models outside football, formal uncertainty intervals and calibrated production probabilities.
- Automatic crypto reconciliation after ambiguous, partial or interrupted orders. Trading now blocks rather than retries; manual reconciliation is required.
- Verified exchange execution: no real orders were submitted during this rebuild. Market orders do not guarantee price or total cost.
- Automatic drift-driven strategy demotion, complete overlapping-strategy attribution and independent model governance. Diagnostics exist, not a production model-risk service.

This is a local research and paper-trading foundation, not an institutional or proven profitable live betting system. Interface tests do not establish an edge.

## Verification and Transfer

Run `python -m unittest discover -s tests -v`. Tests use temporary databases and mock external orders. Browser checks cover login, mode separation, virtual funding, scans, decision detail, paper registration, history, settings, analytics and mobile layouts. They cannot establish bookmaker acceptance or exchange profitability.

The ZIP allowlists source and setup files and excludes `.env.local.ps1`, existing data, logs, virtual environments and Git metadata. Preserve the original PC's journal separately for migration. Never upload keys or account state publicly.
