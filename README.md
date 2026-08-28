# Robinhood Mint Radar

TapeOut-style, read-only opportunity radar for NFT mint activity on **Robinhood Chain**.

> **Machine searches and verifies. Wallet execution stays manual.**

The system never stores a wallet private key or seed phrase and never signs or sends a transaction.

## V1.3 status

V1.3 is an operational scanner, not a landing-page mockup. It:

- reads Robinhood Chain mainnet (`chainId 4663`) via JSON-RPC;
- scans confirmed blocks with a configurable confirmation lag and checkpoint-hash reorg detection;
- detects ERC-721 mints and correctly expands ERC-1155 `TransferSingle` and `TransferBatch` mint quantities;
- detects Hoodsea `CollectionLaunched` and `NFTSold` events;
- reads generic Seaport 1.6 `OrderFulfilled` events from `0x0000000000000068F116a894984e2DB1123eB395`;
- rejects known non-collectible ERC-721 false positives such as position/liquidity-manager NFTs;
- checks ERC-165, verified source, owner privileges, mutability, proxy/delegatecall, owner/role mint, pause/freeze/blacklist, upgrade/withdraw and other static risk indicators;
- uses Blockscout v2 holder data for current holder count and top-holder concentration when available;
- can recognize an observed zero-value mint transaction as conservative evidence of a free mint;
- scores price asymmetry, mint velocity, acceleration, sell-through, secondary activity, holder growth, distribution and safety;
- has strict `MARKET_CONFIRMED` and `EARLY_ONCHAIN_ONLY` qualification paths;
- refuses a manual package when relevance, safety, trusted execution surface or required economic evidence is not good enough;
- persists history/checkpoints in SQLite WAL mode, runs integrity checks, retention, backups and restart recovery;
- records manual realized outcomes and shadow observations for Brier/ECE/MAE calibration;
- emits deduplicated macOS notifications only for a real `MANUAL_MINT_CANDIDATE`;
- serves a local TapeOut-style dashboard.

A safety PASS is a conservative software filter, **not a formal smart-contract audit or a guarantee of profit**.

## Data sources

- Robinhood Chain RPC: `https://rpc.mainnet.chain.robinhood.com`
- Chain ID: `4663`
- Blockscout: `https://robinhoodchain.blockscout.com`
- Hoodsea launchpad: `0xa1e9DAB10a4DED224c090c73B09b6658Cc69331b`
- Seaport 1.6: `0x0000000000000068F116a894984e2DB1123eB395`
- OpenSea API: optional enrichment only

Without an OpenSea API key, the radar can still use **fulfilled on-chain Seaport/Hoodsea sales** as secondary-market evidence. An API key is still useful for data that are not fully available on-chain before execution, such as active floor/orderbook enrichment.

## MacBook — one-command install

Requirements: macOS and Python 3.10+.

```bash
git clone https://github.com/copytolive/robinhood-mint-radar.git
cd robinhood-mint-radar
cp .env.example .env
sh install-mac.command
```

The installer first runs the live doctor. If it passes, it installs two user LaunchAgents:

1. continuous scanner;
2. localhost dashboard.

Then open:

```text
http://127.0.0.1:4173/
```

Run the audit at any time:

```bash
python3 -m radar.audit
```

Uninstall the background stack:

```bash
sh macos/uninstall-stack.sh
```

The Mac scanner runs while the Mac user session is awake and online. `launchd` restarts the process after failure/login; confirmed-block checkpoints and reorg detection protect restart continuity.

## Manual run

```bash
cp .env.example .env
./run-local.sh
```

Defaults:

- SQLite: `data/radar.sqlite`
- status: `public/status.json`
- scan interval: 15 seconds
- confirmed-block lag: 10 blocks
- observation retention: 30 days
- event retention: 90 days
- backups: daily, keep 7

## Qualification

A high score can **never override hard gates**.

Typical hard gates include:

- `NFT_RELEVANCE_NOT_PASS`
- `SAFETY_REJECT` / `SAFETY_REVIEW_REQUIRED`
- `UNVERIFIED_CONTRACT`
- `MINT_PRICE_UNKNOWN`
- `OWNERSHIP_CONCENTRATION_HIGH`
- `TRUSTED_EXECUTION_SURFACE_UNAVAILABLE`
- `MARKET_EVIDENCE_UNAVAILABLE`
- `EARLY_ONCHAIN_REQUIREMENTS_NOT_MET`

The conservative Hoodsea early path requires, among other conditions: a known Hoodsea launch, free mint, relevance PASS, safety PASS, at least 20 recent unique minters, 5-minute velocity of at least 2/min, and at least 10% sell-through. It does **not** allow arbitrary unknown collections to bypass market evidence.

## Prediction calibration

The calibration engine is implemented but deliberately reports:

```text
PREDICTION_UNCERTIFIED
```

until enough real realized or matured shadow samples exist. It will not fabricate a win rate or probability-certification status. With more samples it advances through `CALIBRATION_WARMUP` and, only when empirical error is acceptable, `CALIBRATED`.

Record a manual outcome without giving the program wallet access:

```bash
python3 -m radar.outcomes \
  --collection 0x... \
  --entry-cost-usd 1.00 \
  --exit-value-usd 2.50 \
  --gas-usd 0.05 \
  --predicted-score 90
```

## Tests

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall radar
```

GitHub Actions also validates the project on a real hosted macOS ARM runner, runs a live Robinhood doctor, dry-runs the one-command Mac installer, starts the localhost dashboard, and checks its JSON endpoint.

## Important limitations

- No software can guarantee that an NFT will rise 1,000% or more.
- Static source analysis is not a formal security audit.
- Active OpenSea floor/bid/orderbook data are not all derivable from fulfilled on-chain events; the official API remains optional enrichment for those fields.
- A non-zero mint transaction value is **not** automatically treated as exact per-NFT mint price because a transaction can contain multiple units or fees.
- A generic collection without a trusted mint/market execution surface stays blocked rather than sending the user to an unverified URL.
- Empirical calibration needs time and real outcomes.
- Installing on a specific physical Mac can only be proven by running the installer/audit on that Mac; hosted macOS CI proves compatibility, not possession/control of the user's machine.
