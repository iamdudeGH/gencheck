"""GenCheck end-to-end demo: a shopping agent that refuses to pay scammers.

The scenario: a customer asks the agent to buy something. The agent's product
search returns several offers — including one that is suspiciously cheap
(a lookalike scam page). Before ANY payment, the agent consults GenCheck
(GenLayer validator consensus) on each checkout URL and only pays offers
that are verified as the claimed brand's real seller.

Cheapest offer first — the agent is price-sensitive, but every payment is
security-gated by GenCheck.

Usage:
    set GENCHECK_PRIVATE_KEY=0x...
    .venv-deploy/Scripts/python demo/shopping_agent.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gencheck import GenCheck, decide

TRANSCRIPT_FILE = "demo/demo_transcript.md"

# The shopping request + what "product search" returned.
# The cheap offer is a real Amazon-checkout clone hosted on github.io, taken
# from the OpenPhish feed. The original target (vardhan2k3.github.io) started
# 404ing, so it was blocking by failing closed rather than by detection —
# replace this URL from https://openphish.com/feed.txt if it goes the same way.
REQUEST = "Buy me the cheapest Amazon Echo Dot you can find"
OFFERS = [
    {
        "store": "sarthforge.github.io",
        "checkout_url": "https://sarthforge.github.io/amazon-clone/cart.html",
        "brand": "amazon",
        "price": 19.99,
        "note": "found via product search — 60% below market",
    },
    {
        "store": "www.amazon.com",
        "checkout_url": "https://www.amazon.com/gp/cart/view.html",
        "brand": "amazon",
        "price": 49.99,
        "note": "official Amazon cart",
    },
]


def log(msg=""):
    print(msg, flush=True)


def main():
    gencheck = GenCheck(private_key=os.environ["GENCHECK_PRIVATE_KEY"])
    contract = gencheck.contract

    transcript = []

    def say(msg=""):
        log(msg)
        transcript.append(msg)

    say("=" * 72)
    say("GENCHECK SHOPPING AGENT — end-to-end demo (studio-dev, live consensus)")
    say("=" * 72)
    say(f"GenCheck contract: {contract}")
    say()
    say(f'Customer request: "{REQUEST}"')
    say()
    say("Product search returned 2 offers (cheapest first):")
    for i, o in enumerate(OFFERS, 1):
        say(f"  {i}. {o['store']:<28} ${o['price']:<6} {o['note']}")
    say()

    paid = None
    for i, offer in enumerate(OFFERS, 1):
        say(f"[offer {i}] {offer['store']} — ${offer['price']} (brand: {offer['brand']})")
        say("      asking GenCheck validators to fetch the page and judge...")

        cached = gencheck.check_cache(offer["store"])
        if cached is not None:
            verdict = {"is_real": cached["is_real"],
                       "verdict": "real" if cached["is_real"] else "scam",
                       "confidence": 100,
                       "reasons": ["cached from previous consensus run (instant, free)"]}
            say("      cache hit: domain already validated by earlier consensus")
        else:
            t0 = time.time()
            verdict = gencheck.validate(offer["checkout_url"], offer["brand"])
            say(f"      validator consensus took {time.time() - t0:.0f}s")

        if verdict:
            say(f"      verdict:   {verdict.get('verdict')}")
            say(f"      is_real:   {verdict.get('is_real')}")
            conf = verdict.get("confidence")
            if isinstance(conf, float) and conf <= 1.0:  # raw LLM scale 0-1
                conf = int(round(conf * 100))
            say(f"      confidence:{conf}")
            for r in verdict.get("reasons", [])[:3]:
                say(f"      reason:    {r[:100]}")
        else:
            say("      verdict:   NONE — validators could not produce one")

        action, why = decide(verdict)
        if action == "PAY":
            say(f"      >>> DECISION: PAY — ${offer['price']} to {offer['store']} ({why})")
            paid = offer
            break  # bought it; stop evaluating offers
        say(f"      >>> DECISION: BLOCK — {offer['store']} ({why})")
        say()

    say()
    say("=" * 72)
    if paid:
        say(f"RESULT: purchased from {paid['store']} for ${paid['price']}.")
    else:
        say("RESULT: no offer passed GenCheck — no payment made.")
    say("Blocked offers cost the customer nothing. That is the point.")
    say("=" * 72)

    with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
        f.write("```text\n" + "\n".join(transcript) + "\n```\n")
    log(f"\ntranscript saved: {TRANSCRIPT_FILE}")


if __name__ == "__main__":
    main()
