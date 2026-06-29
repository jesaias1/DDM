# Kopier denne fil til .env.local.ps1 og udfyld dine egne vaerdier.
# Gem ALDRIG .env.local.ps1 offentligt eller i Git.

# Login til den lokale hjemmeside
$env:DDM_USER = "jesaias"
$env:DDM_PASS = "miebs112"

# Coinbase / ccxt
$env:EXCHANGE_ID = "coinbase"
$env:DDM_QUOTE = "EUR"
$env:DDM_UNIVERSE = "BTC/EUR,ETH/EUR,SOL/EUR,ADA/EUR,LINK/EUR"

# Udfyld disse naar du vil handle rigtigt.
# API-noeglen maa have view + trade, men ALDRIG withdraw/transfer.
# $env:EXCHANGE_API_KEY = "DIN_COINBASE_API_KEY"
# $env:EXCHANGE_API_SECRET = "DIN_COINBASE_API_SECRET"
# $env:EXCHANGE_API_PASSPHRASE = "DIN_PASSPHRASE_HVIS_KRAEVET"

# Live-handel: lad disse vaere kommenteret ud indtil preflight er OK.
# $env:DDM_LIVE = "1"
# $env:DDM_LIVE_ARMED = "JEG_FORSTAAR_RISIKOEN"

# Risikobremse
$env:DDM_DAILY_LOSS_LIMIT = "-0.05"
$env:DDM_TOTAL_LOSS_LIMIT = "-0.10"
$env:DDM_AUTO_FLATTEN_ON_HALT = "1"

# Valgfri AI-research til sport. Ikke noedvendig for krypto-botten.
# $env:ANTHROPIC_API_KEY = "DIN_CLAUDE_API_KEY"
# $env:SMARTSTAKE_MODEL = "claude-haiku-4-5"

# AI-forbrug styres nemmest i Settings-fanen.
# Standard i appen er: AI-research slaaet fra, web-soegning slaaet fra,
# max 3 AI-kald/dag og 12000 tokens/dag hvis du aktivt slaar det til.

# Valgfri live-odds til sports-anbefalinger. Ikke noedvendig for krypto-botten.
# $env:ODDS_API_KEY = "DIN_THE_ODDS_API_KEY"
