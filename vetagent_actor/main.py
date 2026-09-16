"""Apify entry point: read the input, check each token with VetAgent, write one row per token."""

from __future__ import annotations

import asyncio
import os
import time

from apify import Actor

from . import client


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        tokens, skipped = client.normalize_tokens(actor_input.get("tokens"))
        if not tokens:
            raise ValueError("No token addresses in the input: add at least one to `tokens`.")
        chain = client.check_chain(actor_input.get("chainHint"))
        verbose = bool(actor_input.get("verboseEvidence"))
        if skipped:
            Actor.log.warning("Checking the first %d addresses; %d more were skipped "
                              "(limit %d per run).", len(tokens), skipped, client.MAX_TOKENS)

        who = client.client_name(tokens, os.environ.get("APIFY_USER_ID"),
                                 os.environ.get("APIFY_IS_AT_HOME") == "1")
        Actor.log.info("Calling VetAgent as client %r for %d token(s).", who, len(tokens))

        counts: dict[str, int] = {}
        last_call = 0.0
        for index, token in enumerate(tokens, start=1):
            if client.looks_like_address(token):
                pause = client.MIN_INTERVAL_SECONDS - (time.monotonic() - last_call)
                if pause > 0:
                    await asyncio.sleep(pause)
                last_call = time.monotonic()
                status, payload, error = await asyncio.to_thread(
                    client.post_assess, token, chain, verbose, who)
                item = client.to_item(token, chain, status, payload, error)
            else:
                item = client.invalid_item(token, chain)
            await Actor.push_data(item)
            counts[item["riskLevel"]] = counts.get(item["riskLevel"], 0) + 1
            await Actor.set_status_message("Checked %d of %d" % (index, len(tokens)))

        summary = ", ".join("%s %d" % (level, counts[level])
                            for level in client.LEVELS if level in counts)
        Actor.log.info("Checked %d token(s): %s", len(tokens), summary)
        await Actor.set_status_message("Checked %d token(s): %s" % (len(tokens), summary),
                                       is_terminal=True)
