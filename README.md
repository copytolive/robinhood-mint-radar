# Robinhood Mint Radar

TapeOut-style, read-only opportunity radar for NFT mint activity on Robinhood Chain.

> Machine searches and verifies. Wallet execution stays manual.

## Safety contract

- **No wallet private keys or seed phrases.**
- **No automatic minting or transaction signing.**
- LIVE views never fabricate missing market data: unavailable data is shown as `UNAVAILABLE` and money readiness fails closed.
- Public RPC endpoints are rate-limited; production operators can provide their own read-only RPC URL.

## Network

- Robinhood Chain mainnet: chain ID `4663`
- Public RPC fallback: `https://rpc.mainnet.chain.robinhood.com`
- Explorer: `https://robinhoodchain.blockscout.com`
- Hoodsea launchpad: `0xa1e9DAB10a4DED224c090c73B09b6658Cc69331b`

## Target architecture

`Robinhood Chain -> discovery -> contract checks -> mint economics -> momentum -> market evidence -> hard gates -> manual package -> realized/shadow outcomes -> calibration`

The repository contains both a continuous local SQLite runner and a public GitHub Pages snapshot runner. The public snapshot is not a substitute for the local continuous process.
