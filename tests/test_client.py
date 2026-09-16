"""Tests for the parts of the Actor that do not need the Apify SDK or the network.

Run:  python -m unittest discover -s tests -v
"""

import io
import json
import os
import sys
import unittest
import urllib.error

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from vetagent_actor import client  # noqa: E402

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
OTHER = "0x4200000000000000000000000000000000000006"
STRANGER_ID = "someoneElse123456"

# Shortened from the real answer on https://vetagent.dev/api. The best_pair keys are the ones
# `_liquidity_signals` in the engine's src/risk.py writes; a first version of this fixture
# invented baseToken/quoteToken there, and the Actor's symbol column came back null in its
# first real run while every test passed.
ANSWER = {
    "address": USDC_BASE,
    "risk_level": "low",
    "risk_score": 0,
    "confidence": "high",
    "driver": None,
    "signals": [{"severity": "ok", "name": "Liquidity is adequate", "category": "liquidity"}],
    "evidence": {"best_pair": {"dex": "aerodrome", "chain": "base", "liquidity_usd": 1000000,
                               "price_usd": 1.0, "sellers_24h": 10, "volume_24h_usd": 50000,
                               "pair_created_at": 1700000000000, "buys_24h": 20,
                               "sells_24h": 20}},
    "recommendation": "Low risk: sellable and liquid when checked, no fatal signal.",
    "checked_at": "2026-09-15T05:17:23Z",
    "evidence_max_age_seconds": 0,
}


class Labels(unittest.TestCase):
    """VetAgent counts a client as its own when the name starts with 'vetagent-'."""

    def test_prefill_in_schema_is_the_demo_list(self):
        with open(os.path.join(ROOT, ".actor", "input_schema.json"), encoding="utf-8") as f:
            schema = json.load(f)
        self.assertEqual(schema["properties"]["tokens"]["prefill"], list(client.PREFILL_TOKENS))

    def test_only_real_use_escapes_the_prefix(self):
        for name in (client.CLIENT_DEMO, client.CLIENT_OWNER, client.CLIENT_LOCAL):
            self.assertTrue(name.startswith("vetagent-"), name)
        self.assertFalse(client.CLIENT_USER.startswith("vetagent-"))
        for name in (client.CLIENT_USER, client.CLIENT_DEMO, client.CLIENT_OWNER, client.CLIENT_LOCAL):
            self.assertLessEqual(len(name), 32, name)   # the server keeps 32 characters

    def test_daily_health_check_is_ours(self):
        self.assertEqual(client.client_name([USDC_BASE], STRANGER_ID, True), client.CLIENT_DEMO)
        self.assertEqual(client.client_name([USDC_BASE.lower()], STRANGER_ID, True), client.CLIENT_DEMO)

    def test_owner_is_ours_whatever_the_input(self):
        self.assertEqual(client.client_name([OTHER], client.OWNER_USER_ID, True), client.CLIENT_OWNER)

    def test_local_run_is_ours(self):
        self.assertEqual(client.client_name([OTHER], None, False), client.CLIENT_LOCAL)

    def test_a_user_with_their_own_tokens_is_a_user(self):
        self.assertEqual(client.client_name([OTHER], STRANGER_ID, True), client.CLIENT_USER)
        self.assertEqual(client.client_name([USDC_BASE, OTHER], STRANGER_ID, True), client.CLIENT_USER)


class Rows(unittest.TestCase):

    def test_answer_maps_to_a_row(self):
        row = client.to_item(USDC_BASE, "base", 200, ANSWER, None)
        self.assertEqual(set(row), set(client.FIELDS))
        self.assertEqual((row["riskLevel"], row["chain"], row["dex"], row["liquidityUsd"],
                          row["verdictSource"]),
                         ("low", "base", "aerodrome", 1000000, "vetagent"))
        self.assertIsNone(row["error"])

    def test_answer_without_a_pool_still_maps(self):
        answer = dict(ANSWER, risk_level="unknown", evidence={"data_gaps": []},
                      unknown_kind="coverage", next_action="abstain")
        row = client.to_item(OTHER, "auto", 200, answer, None)
        self.assertEqual((row["riskLevel"], row["chain"], row["dex"], row["nextAction"]),
                         ("unknown", None, None, "abstain"))

    def test_no_verdict_is_never_low(self):
        cases = [(429, {"error": "rate_limited"}, "VetAgent answered HTTP 429", "retry"),
                 (500, None, "VetAgent answered HTTP 500", "retry"),
                 (None, None, "the call to VetAgent failed (URLError)", "retry"),
                 (200, {"unexpected": True}, None, "retry"),
                 (400, {"error": "invalid_request", "detail": "bad address"},
                  "VetAgent answered HTTP 400", "fix_input")]
        for status, payload, error, action in cases:
            row = client.to_item(USDC_BASE, "auto", status, payload, error)
            self.assertEqual(row["riskLevel"], "unknown", status)
            self.assertEqual(row["verdictSource"], "actor", status)
            self.assertEqual(row["nextAction"], action, status)
            self.assertIn("NOT a low-risk result", row["recommendation"])
            self.assertTrue(row["error"])
            self.assertEqual(set(row), set(client.FIELDS))

    def test_invalid_address_is_not_sent_and_not_low(self):
        self.assertFalse(client.looks_like_address("0x123"))
        self.assertTrue(client.looks_like_address(USDC_BASE))
        self.assertTrue(client.looks_like_address("So11111111111111111111111111111111111111112"))
        row = client.invalid_item("0x123", "auto")
        self.assertEqual((row["riskLevel"], row["nextAction"]), ("unknown", "fix_input"))


class Input(unittest.TestCase):

    def test_cap_is_reported_not_silent(self):
        many = ["0x%040x" % i for i in range(105)] + ["0x%040X" % 1, "  ", None]
        tokens, skipped = client.normalize_tokens(many)
        self.assertEqual((len(tokens), skipped), (100, 5))

    def test_unknown_chain_is_an_error(self):
        self.assertEqual(client.check_chain(None), "auto")
        self.assertEqual(client.check_chain("Base"), "base")
        with self.assertRaises(ValueError):
            client.check_chain("tron")


class Calls(unittest.TestCase):

    class _Response:
        def __init__(self, body):
            self.status, self._body = 200, body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_429_waits_then_succeeds_and_names_itself(self):
        seen, slept = [], []

        def opener(request, timeout):
            seen.append(request)
            if len(seen) == 1:
                raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests",
                                             {"Retry-After": "7"}, io.BytesIO(b"{}"))
            return self._Response(json.dumps(ANSWER).encode("utf-8"))

        status, payload, error = client.post_assess(USDC_BASE, "base", False, client.CLIENT_USER,
                                                    opener=opener, sleep=slept.append)
        self.assertEqual((status, payload["risk_level"], error), (200, "low", None))
        self.assertEqual(slept, [7])
        request = seen[-1]
        self.assertEqual(request.full_url, client.API_URL)          # the address is not in the URL
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"address": USDC_BASE, "chain_hint": "base"})
        self.assertEqual(request.get_header("X-mcp-client"), client.CLIENT_USER)

    def test_gives_up_after_the_last_attempt(self):
        slept = []

        def opener(request, timeout):
            raise urllib.error.URLError("down")

        status, payload, error = client.post_assess(USDC_BASE, "auto", False, client.CLIENT_DEMO,
                                                    opener=opener, sleep=slept.append)
        self.assertIsNone(status)
        self.assertEqual(len(slept), client.ATTEMPTS - 1)
        self.assertIn("failed", error)


if __name__ == "__main__":
    unittest.main()
