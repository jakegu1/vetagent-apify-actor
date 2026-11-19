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
| Mint and freeze authority; top-10 holder concentration only when RugCheck provides a holder list | Solana |
| Liquidity depth, counted only for reserves held in independently priced assets | Ethereum, BSC, Base, Arbitrum, Optimism, Polygon, Avalanche, Solana |
| Pair age, 24h turnover across the token's pools | Every chain |
| Same-ticker impersonation within one chain | Every chain |
| Owner powers in the bytecode (blacklist, tax change, pause, mint): disclosed, never scored | Ethereum, BSC, Base |

An unavailable critical sell check is disclosed and cannot justify a `low` verdict.
It generally yields `unknown`; independent fatal evidence can still yield `high`.

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

## Review one token from your pool alert

Run the Actor with one token address and its chain. Replace the public USDC address below
with the token from your alert and set `chainHint` to its chain. Do not enter a wallet address.
The prefilled USDC example is a demonstration, not a check of your own alert.

```json
{
    "tokens": [
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    ],
    "chainHint": "base",
    "verboseEvidence": true
}
```

- `tokens`: EVM (`0x...`) contract addresses or Solana mint addresses, up to 100 per run.
- `chainHint`: `auto`, `ethereum`, `bsc`, `base`, `arbitrum`, `polygon`, `optimism`,
  `avalanche` or `solana`. Specify the chain from your alert. With `auto`, the engine
  selects the chain from the available market evidence; inspect the returned chain rather
  than assuming it is the chain you intended or always the globally deepest market.
- `verboseEvidence`: set this to `true` for reported pool identifiers when available and
  `evidence.pool_link_details` used below. Some identifiers can be missing or truncated;
  do not treat a partial identifier as an exact pool match. The default slim evidence still exposes
  `evidence.pool_link`, but omits the full pool-comparison details.

## Read the evidence before forwarding the alert

Each token produces one dataset row. Actor fields such as `riskLevel` use camel case;
the nested `evidence` object keeps the API's snake-case field names.

1. Compare the returned `chain` with your alert's chain.
2. Read `evidence.pool_link`. `same` means the adopted sell-simulation response reports the
   displayed market pool on the same chain. `different` means those pools differ.
   `unknown` means their relationship could not be established; inspect the details.
   This field is a relationship status, not a URL or a second risk rating.
3. With verbose evidence, compare `pool_link_details.market_pool` (the displayed market
   pool) and `reported_pool` (the pool reported by the adopted simulation response), along
   with their chain fields. The Actor takes a token and chain, not the alert's pool ID:
   compare these addresses with your alert yourself. Even `same` does not prove your
   intended pool or intended sale amount was tested.
4. Read `evidence.data_gaps` for each missing check and its reason. It may be absent when
   no critical gap was reported. Also read `signals` and `recommendation` for other
   limitations. If `riskLevel` is `unknown`, route the alert to human review;
   `nextAction: retry` indicates a temporary failure, while `abstain` indicates a gap that
   an immediate retry will not close. `pool_link: unknown` alone does not necessarily make
   the overall `riskLevel` unknown.

### A same-pool observation

This small excerpt is from a tagged HTTP release check for Ethereum WETH on
2026-11-17 at 02:33 UTC, not a new Apify run or a live quote. Only the two observed fields
are shown here, using the Actor's `riskLevel` spelling:

```json
{
    "riskLevel": "low",
    "evidence": {
        "pool_link": "same"
    }
}
```

The simulation and market pool matched in that observation. It does not establish that a
later run, a different pool, or your intended sale amount will have the same result.

### A result to send for human review

This excerpt was mapped through the unchanged Actor adapter from a Base USDC response
replayed on 2026-11-19 using saved upstream responses. It is an archive replay, not a fresh
market check or an Apify run. Full responses contain more fields than these excerpts.

```json
{
    "chain": "base",
    "riskLevel": "low",
    "evidence": {
        "pool_link": "different",
        "pool_link_details": {
            "market_chain": "base",
            "market_pool": "0x6cDcb1C4A4D1C3C6d054b27AC5B77e89eAFb971d",
            "reported_chain": "base",
            "reported_pool": "0x6c561b446416e1a00e8e93e221854d6ea4171372"
        }
    }
}
```

The overall verdict was `low`, but the adopted simulation response reported a different
pool from the displayed market pool. Do not read its sell result as evidence for that
displayed pool. The pool addresses can be compared independently on
[BaseScan](https://basescan.org/).

If a new run instead returns `riskLevel: unknown`, read its actual `evidence.data_gaps`;
do not copy a historical reason into your workflow. The
[unknown-result guide](https://vetagent.dev/unknown) explains coverage gaps and temporary
source failures. Solana has authority and liquidity checks here, not a sell simulation.

If you try your own alert, an issue on this repository can simply say whether it ran,
which evidence field affected your decision, and whether you used it again on another day.
Please do not post wallet addresses, token inputs, private alerts, or transaction records.

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
