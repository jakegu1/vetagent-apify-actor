"""Everything the Actor does that does not need the Apify SDK, so it can be tested anywhere.

The one piece that is more than plumbing is `client_name`. VetAgent decides whether anyone
outside uses it by counting the clients that call it, and it counts every client whose name
starts with "vetagent-" as its own traffic. Apify runs every public Actor once a day with its
prefilled input, and the author tests it too. Both are labelled here as VetAgent's own, so
neither can ever be counted as a user.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

API_URL = "https://vetagent.dev/assess"
USER_AGENT = "apify-vetagent/0.1 (+https://github.com/jakegu1/vetagent-apify-actor)"

CLIENT_USER = "apify-vetagent"          # someone running the Actor on their own tokens
CLIENT_DEMO = "vetagent-apify-demo"     # the prefilled example, which Apify's daily test runs
CLIENT_OWNER = "vetagent-apify-owner"   # the Actor's author testing it
CLIENT_LOCAL = "vetagent-apify-local"   # run outside the Apify platform, e.g. while developing

# The Apify user who owns this Actor (Apify Console -> Settings -> API & Integrations).
OWNER_USER_ID = "8fRyGugpGvG4MziX6"

# Must equal the prefill of `tokens` in .actor/input_schema.json; tests/test_client.py checks it.
PREFILL_TOKENS = ("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",)

CHAINS = ("ethereum", "bsc", "base", "arbitrum", "polygon", "optimism", "avalanche", "solana")
LEVELS = ("low", "medium", "high", "unknown")
MAX_TOKENS = 100
MIN_INTERVAL_SECONDS = 1.1   # VetAgent allows about 60 calls a minute per caller
ATTEMPTS = 3
TIMEOUT_SECONDS = 60

_EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
_SOLANA = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

FIELDS = ("token", "chainHint", "chain", "dex", "liquidityUsd", "riskLevel", "riskScore",
          "confidence", "driver", "driverCategory", "recommendation", "unknownKind",
          "nextAction", "checkedAt", "evidenceMaxAgeSeconds", "signals", "evidence",
          "verdictSource", "httpStatus", "error")


def _key(token):
    """EVM addresses compare case-insensitively; Solana addresses are case-sensitive."""
    token = token.strip()
    return token.lower() if token.lower().startswith("0x") else token


def normalize_tokens(raw):
    """Strip, drop blanks and repeats, keep order, cap at MAX_TOKENS.

    Returns (tokens, skipped), where `skipped` counts what the cap removed, so the run can
    say so instead of looking complete.
    """
    if isinstance(raw, str):
        raw = raw.splitlines()
    seen, tokens = set(), []
    for value in raw or []:
        if not isinstance(value, str) or not value.strip():
            continue
        if _key(value) in seen:
            continue
        seen.add(_key(value))
        tokens.append(value.strip())
    return tokens[:MAX_TOKENS], max(0, len(tokens) - MAX_TOKENS)


def check_chain(value):
    """'auto' or a chain VetAgent accepts. Anything else is an input error, not a guess."""
    chain = (value or "auto").strip().lower()
    if chain != "auto" and chain not in CHAINS:
        raise ValueError("chainHint must be auto or one of: %s" % ", ".join(CHAINS))
    return chain


def looks_like_address(token):
    return bool(_EVM.match(token) or _SOLANA.match(token))


def client_name(tokens, user_id, at_home):
    """The name this run gives VetAgent: its own traffic unless someone is using the Actor."""
    if not at_home:
        return CLIENT_LOCAL
    if user_id and user_id == OWNER_USER_ID:
        return CLIENT_OWNER
    if [_key(t) for t in tokens] == [_key(t) for t in PREFILL_TOKENS]:
        return CLIENT_DEMO
    return CLIENT_USER


def _retry_after(headers, default=60):
    try:
        value = headers.get("Retry-After") if headers is not None else None
        return max(1, min(120, int(value or default)))
    except (TypeError, ValueError):
        return default


def _json_or_none(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None


def post_assess(token, chain, verbose, client, opener=urllib.request.urlopen, sleep=time.sleep):
    """POST one address to VetAgent. The address travels in the body, never in the URL.

    Returns (http_status or None, parsed JSON or None, error text or None). A 429 is retried
    after Retry-After, a 5xx or a network failure after a short pause, up to ATTEMPTS calls.
    """
    body = {"address": token}
    if chain != "auto":
        body["chain_hint"] = chain
    if verbose:
        body["verbose"] = True
    data = json.dumps(body).encode("utf-8")
    headers = {"content-type": "application/json", "accept": "application/json",
               "user-agent": USER_AGENT, "x-mcp-client": client}
    status, payload, error = None, None, None
    for attempt in range(1, ATTEMPTS + 1):
        request = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
        try:
            with opener(request, timeout=TIMEOUT_SECONDS) as response:
                return response.status, _json_or_none(response.read()), None
        except urllib.error.HTTPError as e:
            status, payload = e.code, _json_or_none(e.read())
            error = "VetAgent answered HTTP %d" % e.code
            if attempt < ATTEMPTS and e.code == 429:
                sleep(_retry_after(e.headers))
                continue
            if attempt < ATTEMPTS and e.code >= 500:
                sleep(5)
                continue
            return status, payload, error
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            status, payload = None, None
            error = "the call to VetAgent failed (%s)" % type(e).__name__
            if attempt < ATTEMPTS:
                sleep(5)
    return status, payload, error


def _blank(token, chain, status=None):
    item = dict.fromkeys(FIELDS)
    item.update(token=token, chainHint=chain, signals=[], evidence={}, httpStatus=status)
    return item


def not_assessed(token, chain, reason, next_action, status=None):
    """A row for a token this Actor could not get a verdict for. Always `unknown`: a failure
    must never be readable as low risk."""
    item = _blank(token, chain, status)
    item.update(riskLevel="unknown", verdictSource="actor", nextAction=next_action,
                error=reason,
                recommendation="Not assessed: %s. This is NOT a low-risk result and must not "
                               "justify a trade." % reason)
    return item


def invalid_item(token, chain):
    return not_assessed(token, chain, "not an EVM (0x...) or Solana address", "fix_input")


def to_item(token, chain, status, payload, error):
    """One dataset row from one VetAgent answer, or a not-assessed row when there was none."""
    if status == 200 and isinstance(payload, dict) and payload.get("risk_level") in LEVELS:
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        best_pair = evidence.get("best_pair") if isinstance(evidence.get("best_pair"), dict) else {}
        driver = payload.get("driver") if isinstance(payload.get("driver"), dict) else {}
        signals = payload.get("signals") if isinstance(payload.get("signals"), list) else []
        item = _blank(token, chain, status)
        # VetAgent's slim evidence names the pool, not the token: best_pair carries dex,
        # chain, liquidity_usd, price_usd and trade counts, and no symbol.
        item.update(chain=best_pair.get("chain"), dex=best_pair.get("dex"),
                    liquidityUsd=best_pair.get("liquidity_usd"),
                    riskLevel=payload["risk_level"], riskScore=payload.get("risk_score"),
                    confidence=payload.get("confidence"), driver=driver.get("name"),
                    driverCategory=driver.get("category"),
                    recommendation=payload.get("recommendation"),
                    unknownKind=payload.get("unknown_kind"),
                    nextAction=payload.get("next_action"),
                    checkedAt=payload.get("checked_at"),
                    evidenceMaxAgeSeconds=payload.get("evidence_max_age_seconds"),
                    signals=signals, evidence=evidence, verdictSource="vetagent")
        return item
    detail = (payload.get("detail") or payload.get("error")) if isinstance(payload, dict) else None
    reason = error or ("VetAgent answered HTTP %s without a verdict" % status)
    if detail:
        reason = "%s: %s" % (reason, str(detail)[:200])
    bad_input = status is not None and 400 <= status < 500 and status != 429
    return not_assessed(token, chain, reason, "fix_input" if bad_input else "retry", status)
