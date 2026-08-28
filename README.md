# Robinhood Mint Radar

TapeOut-style, read-only opportunity radar for NFT mint activity on **Robinhood Chain**.

> **Machine searches and verifies. Wallet execution stays manual.**

## What V1 does

- Reads Robinhood Chain mainnet (`chainId 4663`) through JSON-RPC.
- Detects ERC-721 mint transfers and ERC-1155 `TransferSingle` / `TransferBatch` mints.
- Watches the Hoodsea launchpad `CollectionLaunched` event and records creator/name/ticker/mint price.
- Persists local history and block checkpoints in SQLite and resumes after restart.
- Computes 1m/5m/15m/60m mint momentum, acceleration, recent unique minters, and recent mint concentration.
- Queries Blockscout for contract verification/source risk indicators.
- Supports the official OpenSea API for collection floor/volume/sales evidence when `OPENSEA_API_KEY` is configured.
- Scores opportunities 0–100, then applies hard gates. A high score **cannot override** missing required evidence.
- Publishes a TapeOut-style GitHub Pages dashboard and runs Chromium browser acceptance after deploy.
- Produces `MANUAL_MINT_CANDIDATE` packages only. It never signs or sends a transaction.

## Safety contract

- **No wallet private keys or seed phrases.**
- **No automatic minting or transaction signing.**
- LIVE views never fabricate missing market data: unavailable data is shown as `UNAVAILABLE` and qualification fails closed.
- Public RPC endpoints are rate-limited; production operators should use a dedicated read-only RPC provider when needed.
- A safety PASS is not a guarantee that a collection is safe or profitable.

## Network sources

- Robinhood Chain mainnet: chain ID `4663`
- Public RPC fallback: `https://rpc.mainnet.chain.robinhood.com`
- Blockscout: `https://robinhoodchain.blockscout.com`
- Hoodsea launchpad: `0xa1e9DAB10a4DED224c090c73B09b6658Cc69331b`

## Architecture

```text
Robinhood Chain
      ↓
ERC-721 / ERC-1155 / Hoodsea discovery
      ↓
contract + source checks
      ↓
mint economics
      ↓
momentum + recent-flow concentration
      ↓
OpenSea market evidence (when configured)
      ↓
score 0–100
      ↓
hard gates
      ↓
WAIT / WATCH / MANUAL_MINT_CANDIDATE
      ↓
manual wallet decision only
```

## Local continuous runner

Requires Python 3.10+ and no third-party Python packages.

```bash
cp .env.example .env   # optional reference only; run-local.sh does not auto-source it
./run-local.sh
```

Default files:

- SQLite: `data/radar.sqlite`
- Dashboard snapshot: `public/status.json`
- Scan interval: 15 seconds

To use a dedicated read-only RPC:

```bash
export RH_RPC_URL='https://your-read-only-rpc'
./run-local.sh
```

To enable official OpenSea collection statistics:

```bash
export OPENSEA_API_KEY='your-key'
export OPENSEA_CHAIN='robinhood'
./run-local.sh
```

Without an OpenSea API key, the **market evidence gate is `UNAVAILABLE` and fails closed**. The scanner still discovers and scores on-chain activity, but it will not claim a fully qualified opportunity that depends on missing market evidence.

## macOS restart recovery

`macos/com.copytolive.robinhood-mint-radar.plist.example` is a LaunchAgent template. Replace `REPLACE_WITH_REPO_PATH` with the clone path, copy the plist to `~/Library/LaunchAgents/`, then load it with `launchctl` if you want the local scanner to restart with your Mac user session.

## Public dashboard

GitHub Actions runs a read-only snapshot on push, manual dispatch, and a five-minute schedule. It generates `public/status.json`, deploys `public/` to GitHub Pages, then opens the deployed page in headless Chromium and stores a full-page screenshot as workflow evidence.

Public snapshots are periodic. The Mac runner is the continuous 15-second scanner.

## Qualification model

Score components total 100 points:

| Component | Max |
|---|---:|
| Price asymmetry | 15 |
| Mint velocity | 20 |
| Acceleration | 15 |
| Sell-through | 10 |
| Secondary liquidity | 15 |
| Holder/minter growth | 10 |
| Distribution proxy | 5 |
| Safety | 10 |

Hard gates include safety rejection, unverified contract, unavailable required market evidence, and unknown mint price. These are deliberately conservative and will evolve only from measured outcomes.

## Tests

```bash
python -m unittest discover -s tests -v
```

CI also compiles all Python files and checks the no-auto-wallet safety contract.

## Non-goals

This repository does not promise returns, does not predict a guaranteed +1,000%, and does not bypass mint rules, allowlists, rate limits, or wallet confirmations. It is an evidence and ranking system for manual decisions.
