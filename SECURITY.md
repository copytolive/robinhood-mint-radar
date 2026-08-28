# Security model

Robinhood Mint Radar is deliberately read-only.

## Never store

- wallet private keys
- seed phrases
- signing sessions
- browser wallet cookies
- automatic transaction credentials

## Fail-closed rules

A missing/stale chain feed, unverified contract, safety rejection, unknown mint price, or unavailable required market evidence prevents a candidate from becoming a `MANUAL_MINT_CANDIDATE`.

Contract source heuristics are risk indicators, not formal verification. A PASS is not a guarantee of profit or safety.
