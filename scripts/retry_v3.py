"""Retry the two v3 no-verdict cases against the v3 benchmark contract.

music.apple.com [spotify] hit a consensus TIMEOUT and apple.com/shop/bag
[apple] hit apple's 503s — neither cached a verdict, so re-running
validate_checkout triggers a fresh consensus round. Results are appended to
benchmarks/benchmark_v3_results.json with note "retry".

Usage:
    set GENCHECK_PRIVATE_KEY=0x...
    .venv-deploy/Scripts/python scripts/retry_v3.py
"""

import json
import os
import time

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet

RESULTS_FILE = "benchmarks/benchmark_v3_results.json"

RETRY_CASES = [
    ("https://music.apple.com/us/browse", "spotify", "wrong_seller", False,
     "real Apple Music page claimed as Spotify (retry: v3 TIMEOUT)"),
    ("https://www.apple.com/shop/bag", "apple", "real", True,
     "Apple bag (retry: apple 503s)"),
]


def extract_domain(url: str) -> str:
    if "://" in url:
        url = url.split("://", 1)[1]
    if "/" in url:
        url = url.split("/", 1)[0]
    if "@" in url:
        url = url.split("@", 1)[1]
    if ":" in url:
        url = url.split(":", 1)[0]
    return url.lower()


def retry(fn, tries=8, base_delay=15):
    import time as _t
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            transient = ("invalid JSON" in msg or "DOCTYPE" in msg
                         or "1010" in msg or "Timeout" in msg
                         or "timed out" in msg.lower())
            if attempt == tries or not transient:
                raise
            _t.sleep(base_delay * attempt)


def main():
    private_key = os.environ["GENCHECK_PRIVATE_KEY"]
    account = create_account(private_key)
    client = create_client(chain=studio_devnet, account=account)

    with open(RESULTS_FILE) as f:
        results = json.load(f)
    contract = results["contract"]
    print(f"v3 contract: {contract}", flush=True)

    with open("benchmark_fees.json") as f:
        fees = json.load(f)

    for url, brand, category, expected, note in RETRY_CASES:
        domain = extract_domain(url)
        print(f"RETRY {category}: {url} [{brand}]", flush=True)
        case = {"url": url, "brand": brand, "domain": domain, "category": category,
                "expected_real": expected, "note": note, "started_at": time.time()}
        try:
            tx_id = retry(lambda: client.write_contract(
                address=contract, function_name="validate_checkout",
                args=[url, brand], account=account,
                fees={"distribution": fees["distribution"],
                      "feeValue": fees["paid_fee_value"]},
            ))
            case["tx_id"] = tx_id
            print(f"  submitted {tx_id[:18]}...", flush=True)
            receipt = retry(lambda: client.wait_for_finalization(
                tx_id, retries=150, interval=5000))
            case["result_name"] = receipt.get("result_name")
            case["execution"] = receipt.get("txExecutionResultName")
            cached = retry(lambda: client.read_contract(
                address=contract, function_name="get_cached_result",
                args=[domain]))
            case["is_real"] = cached.get("is_real")
        except Exception as e:  # noqa: BLE001
            case["error"] = f"{type(e).__name__}: {str(e)[:400]}"
        if case.get("is_real") is not None:
            case["correct"] = case["is_real"] == expected
        case["duration_s"] = round(time.time() - case["started_at"], 1)
        results["cases"].append(case)
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)
        verdict = case.get("is_real")
        mark = "?" if verdict is None else ("PASS" if case.get("correct") else "FAIL")
        print(f"  -> is_real={verdict} {mark} ({case['duration_s']}s)", flush=True)
        time.sleep(5)

    cases = [c for c in results["cases"] if c.get("is_real") is not None]
    print("\n==== v3 + RETRIES SUMMARY ====")
    for cat in ("phishing", "wrong_seller", "real"):
        cat_cases = [c for c in cases if c["category"] == cat]
        ok = sum(1 for c in cat_cases if c["correct"])
        print(f"{cat:<13} correct: {ok}/{len(cat_cases)}")
    n = len(cases)
    if n:
        print(f"accuracy: {sum(1 for c in cases if c['correct'])/n:.1%} on {n} verdicts")


if __name__ == "__main__":
    main()
