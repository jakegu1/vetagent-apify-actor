# Token Honeypot & Rug-Pull Check

Check a token before you, your trading bot or your AI agent buys it, and answer the question
that matters first: **could you still sell it?**

This Actor sends each address to [VetAgent](https://vetagent.dev), a free pre-trade check, and
returns one row per token with a `low`, `medium`, `high` or `unknown` verdict and every signal
behind it. Use it for batch checks, scheduled runs, or to wire a pre-trade check into Make,
Zapier or a webhook through Apify's integrations.

## What it checks

| Check | Chains |
|---|---|
| Buy/sell simulation (honeypot), buy/sell/transfer tax | Ethereum, BSC, Base |
| Mint and freeze authority, top-10 holder concentration | Solana |
| Liquidity depth, counted only for reserves held in independently priced assets | Ethereum, BSC, Base, Arbitrum, Optimism, Polygon, Avalanche, Solana |
| Pair age, 24h turnover across the token's pools | Every chain |
| Same-ticker impersonation within one chain | Every chain |
| Owner powers in the bytecode (blacklist, tax change, pause, mint): disclosed, never scored | Ethereum, BSC, Base |

On a chain the sell simulator does not cover, the answer says so and comes back `unknown`
rather than pretending the check ran.

## How to read the verdict

- **`low`**: no fatal signal in the checks that ran. The exit was open when the token was
  checked; that does not mean nobody can close it later.
- **`medium`**: real signals, none fatal. Read them before acting.
- **`high`**: do not proceed without review.
- **`unknown`**: a critical check could not run. **Never treat it as a green light.**
  `nextAction` says whether to `retry` (a data source failed) or `abstain` (nothing can see
  the token).

If this Actor cannot get an answer at all (an invalid address, or a call that still failed
after retries), the row still comes back `unknown`, with `verdictSource` set to `actor` and the
reason in `error`. A failure can never be read as low risk.

## Input

```json
{
    "tokens": ["0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"],
    "chainHint": "base",
    "verboseEvidence": false
}
```

- `tokens`: EVM (`0x...`) or Solana mint addresses, up to 100 per run.
- `chainHint`: `auto`, `ethereum`, `bsc`, `base`, `arbitrum`, `polygon`, `optimism`,
  `avalanche` or `solana`. The same address can exist on several chains; with `auto`, each
  answer covers the chain holding the most liquidity and names it.
- `verboseEvidence`: also return raw upstream fields such as reserves.

## Output

One dataset row per token. A shortened real answer for USDC on Base:

```json
{
    "token": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "chain": "base",
    "riskLevel": "low",
    "riskScore": 0,
    "confidence": "high",
    "driver": null,
    "recommendation": "Low risk: sellable and liquid when checked, no fatal signal. ...",
    "nextAction": null,
    "checkedAt": "2026-09-15T05:17:23Z",
    "signals": [
        {"severity": "ok", "name": "Liquidity is adequate", "category": "liquidity"},
        {"severity": "ok", "name": "Buys and sells normally", "category": "honeypot"}
    ],
    "verdictSource": "vetagent",
    "error": null
}
```

## How accurate is it?

VetAgent publishes its own measured error rates, including the ones that make it look worst,
with the benchmark that reproduces them: [vetagent.dev/method](https://vetagent.dev/method).
No figures are copied here, because they change every time the benchmark is re-run.

## For AI agents: connect over MCP instead

An agent that speaks MCP does not need this Actor. Point it at `https://vetagent.dev/mcp`
(Streamable HTTP, no key) and it gets `assess_token_risk`, `get_token_liquidity` and
`find_new_hot_pools` directly. See [vetagent.dev/api](https://vetagent.dev/api).

## Limits and cost

- Up to 100 addresses per run; any beyond that are skipped, and the log says how many.
- VetAgent allows about 60 calls a minute per caller. The Actor paces itself and waits when
  it is asked to.
- VetAgent is free and needs no API key. Runs use your Apify platform usage like any Actor.

## Privacy

Each address goes in the body of an HTTPS POST to `https://vetagent.dev/assess`, never in a
URL. VetAgent does not log the token addresses it is asked about. The Actor sends no Apify
user id, token or run id; it sends a client name, which is how VetAgent tells its own test
traffic from real use. Runs of the prefilled example, which Apify's daily health check uses,
and runs by this Actor's author are labelled as VetAgent's own.

## Not investment advice

Read-only analysis. It executes no trades and gives no investment advice.

## Source

- This Actor (MIT): [github.com/jakegu1/vetagent-apify-actor](https://github.com/jakegu1/vetagent-apify-actor)
- The engine and its benchmark: [github.com/jakegu1/vetagent](https://github.com/jakegu1/vetagent)
- Questions or problems: hello@vetagent.dev, or an issue on either repository
