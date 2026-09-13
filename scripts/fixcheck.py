"""Re-run of the benchmark's failure cases against the FIXED prompt.

The v1 prompt let legitimate-but-wrong-brand sites through (walmart->amazon,
target->paypal, music.apple->spotify). The v2 prompt makes domain ownership the
primary criterion. This script deploys a fresh contract (clean cache) and runs:

  - the 3 false-positive cases  (expect is_real=False now)
  - 3 true-positive sanity cases, incl. subdomain edge cases (expect True)
  - 1 true-negative sanity case (expect False)

Usage:
    set GENCHECK_PRIVATE_KEY=0x...
    .venv-deploy/Scripts/python scripts/fixcheck.py
"""

import json
import os
import time

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet

RESULTS_FILE = "benchmarks/fixcheck_results.json"

CASES = [
    # (url, brand, expected_real, note)
    # --- the 3 false positives from the v1 benchmark; must flip to blocked ---
    ("https://www.walmart.com/checkout", "amazon", False, "v1 FP #1"),
    ("https://www.target.com/cart", "paypal", False, "v1 FP #2"),
    ("https://music.apple.com/us/browse", "spotify", False, "v1 FP #3"),
    # --- true-positive sanity: subdomains are the regression risk for a
    #     strict domain-ownership rule ---
    ("https://apple.com/shop/bag", "apple", True, "TP: apex domain"),
    ("https://store.google.com/us", "google", True, "TP: subdomain"),
    ("https://open.spotify.com", "spotify", True, "TP: subdomain"),
    # --- true-negative sanity: must stay blocked ---
    ("https://www.bing.com/shop", "apple", False, "TN: wrong-brand site"),
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
            print(f"    transient RPC error, retry {attempt}/{tries - 1} "
                  f"in {base_delay * attempt}s: {msg[:120]}", flush=True)
            _t.sleep(base_delay * attempt)


def run_case(client, account, contract, url, brand, expected_real, fees):
    domain = extract_domain(url)
    case = {"url": url, "brand": brand, "domain": domain,
            "expected_real": expected_real, "started_at": time.time()}
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
            address=contract, function_name="get_cached_result", args=[domain]))
        case["is_real"] = cached.get("is_real")
    except Exception as e:  # noqa: BLE001
        case["error"] = f"{type(e).__name__}: {str(e)[:400]}"

    if case.get("is_real") is not None:
        case["correct"] = case["is_real"] == expected_real
    case["duration_s"] = round(time.time() - case["started_at"], 1)
    return case


def main():
    private_key = os.environ["GENCHECK_PRIVATE_KEY"]
    account = create_account(private_key)
    client = create_client(chain=studio_devnet, account=account)
    print(f"account: {account.address}", flush=True)

    results = {"contract": None, "prompt_version": "v2-domain-ownership", "cases": []}
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            results = json.load(f)

    with open("benchmark_fees.json") as f:
        fees = json.load(f)

    if not results.get("contract"):
        print("deploying fresh fix-check contract (v2 prompt) ...", flush=True)
        estimate = client.estimate_transaction_fees()
        tx_id = client.deploy_contract(
            code=open("contracts/shopping_validator.py", encoding="utf-8").read(),
            fees={"distribution": estimate["distribution"],
                  "feeValue": estimate["feeValue"]},
        )
        receipt = client.wait_for_finalization(tx_id, retries=150, interval=5000)
        contract = receipt.get("data", {}).get("contract_address")
        if receipt.get("txExecutionResultName") != "FINISHED_WITH_RETURN" or not contract:
            raise RuntimeError(
                f"fix-check deploy failed: {receipt.get('result_name')} / "
                f"{receipt.get('txExecutionResultName')}")
        results["contract"] = contract
        print(f"fix-check contract: {contract}", flush=True)

    contract = results["contract"]
    done = {(c["url"], c["brand"]) for c in results["cases"]}

    for i, (url, brand, expected, note) in enumerate(CASES, 1):
        if (url, brand) in done:
            print(f"[{i}/{len(CASES)}] SKIP (done): {url} [{brand}]", flush=True)
            continue
        print(f"[{i}/{len(CASES)}] {note}: {url} [{brand}] "
              f"(expect {'REAL' if expected else 'FAKE'})", flush=True)
        case = run_case(client, account, contract, url, brand, expected, fees)
        case["note"] = note
        results["cases"].append(case)
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)
        verdict = case.get("is_real")
        mark = "?" if verdict is None else ("PASS" if case.get("correct") else "FAIL")
        print(f"  -> is_real={verdict} {mark} ({case.get('duration_s')}s)", flush=True)
        time.sleep(5)

    cases = [c for c in results["cases"] if c.get("is_real") is not None]
    print("\n==== FIX-CHECK SUMMARY ====")
    print(f"verdicts: {len(cases)}/{len(CASES)}")
    fps_fixed = sum(1 for c in cases if c["note"].startswith("v1 FP") and c["is_real"] is False)
    print(f"v1 false positives now blocked: {fps_fixed}/3")
    tp_ok = sum(1 for c in cases if c["note"].startswith("TP") and c["is_real"] is True)
    print(f"true positives still allowed: {tp_ok}/3")
    tn_ok = sum(1 for c in cases if c["note"].startswith("TN") and c["is_real"] is False)
    print(f"true negatives still blocked: {tn_ok}/1")
    print(f"\nfull results: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
