"""GenCheck accuracy benchmark on studio-dev.

Deploys a FRESH contract instance (clean cache) and runs a labeled dataset of
real and fake checkout URLs through real GenLayer consensus. Results are
written incrementally to benchmarks/benchmark_results.json so progress survives
interruptions.

Usage:
    set GENCHECK_PRIVATE_KEY=0x...
    .venv-deploy/Scripts/python scripts/benchmark.py

Runtime: one consensus transaction per case (~1-3 min each, sequential).
"""

import json
import os
import time

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet
from genlayer_py.transactions import is_successful

RESULTS_FILE = "benchmarks/benchmark_results.json"

# Labeled dataset. Every domain is distinct across ALL cases so each one gets
# a fresh LLM judgment (no cache hits).
REAL_CASES = [
    # (checkout_url, brand) — legitimate: expect is_real=true
    ("https://apple.com/shop/bag", "apple"),
    ("https://www.apple.com/shop/watch", "apple"),          # www variant
    ("https://www.amazon.com/gp/cart/view.html", "amazon"),
    ("https://www.paypal.com/signin", "paypal"),
    ("https://www.microsoft.com/en-us/store/buy", "microsoft"),
    ("https://www.netflix.com/YourAccount", "netflix"),
    ("https://github.com/settings/billing", "github"),
    ("https://store.google.com/us", "google"),              # subdomain of official
    ("https://open.spotify.com", "spotify"),                # subdomain of official
]

FAKE_CASES = [
    # (checkout_url, brand) — lookalike/wrong-brand: expect is_real=false
    ("https://www.bing.com/shop", "apple"),
    ("https://store.steampowered.com/cart", "apple"),
    ("https://www.ebay.com/sl/list", "paypal"),             # classic phishing pairing
    ("https://www.walmart.com/checkout", "amazon"),
    ("https://mail.yahoo.com", "microsoft"),
    ("https://gitlab.com/users/sign_in", "github"),         # competitor lookalike
    ("https://www.hulu.com", "netflix"),                    # competitor lookalike
    ("https://music.apple.com/us/browse", "spotify"),       # real Apple, wrong brand
    ("https://www.target.com/cart", "paypal"),
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
    """Retry an SDK call with backoff.

    The studio-dev RPC sits behind Cloudflare, which intermittently serves
    HTML challenge pages instead of JSON when request volume rises (observed
    as 'returned invalid JSON ... <!DOCTYPE html>'). Backing off and retrying
    the same call gets through.
    """
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
            delay = base_delay * attempt
            print(f"    transient RPC error, retry {attempt}/{tries - 1} "
                  f"in {delay}s: {msg[:120]}", flush=True)
            _t.sleep(delay)


def run_case(client, account, contract, url, brand, expected_real, fees):
    domain = extract_domain(url)
    case = {
        "url": url, "brand": brand, "domain": domain,
        "expected_real": expected_real, "started_at": time.time(),
    }
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
        case["consensus_ok"] = bool(
            is_successful(receipt)
            and receipt.get("txExecutionResultName") == "FINISHED_WITH_RETURN"
        )
        # capture the returned verdict if present in the receipt
        # (data.calldata is a dict in some receipt shapes, a str in others)
        calldata_field = (receipt.get("data") or {}).get("calldata")
        readable = (calldata_field.get("readable")
                    if isinstance(calldata_field, dict) else calldata_field)
        if readable and readable != "{}":
            try:
                case["returned"] = json.loads(readable)
            except (ValueError, TypeError):
                case["returned_raw"] = str(readable)[:500]

        cached = retry(lambda: client.read_contract(
            address=contract, function_name="get_cached_result", args=[domain]))
        case["is_real"] = cached.get("is_real")
    except Exception as e:  # noqa: BLE001 — record and continue with the dataset
        case["error"] = f"{type(e).__name__}: {str(e)[:400]}"

    if case.get("is_real") is not None:
        case["correct"] = case["is_real"] == expected_real
    case["finished_at"] = time.time()
    case["duration_s"] = round(case["finished_at"] - case["started_at"], 1)
    return case


def main():
    private_key = os.environ["GENCHECK_PRIVATE_KEY"]
    account = create_account(private_key)
    client = create_client(chain=studio_devnet, account=account)
    print(f"account: {account.address}", flush=True)

    results = {"contract": None, "cases": [], "started_at": time.time()}
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            results = json.load(f)

    # fee distribution proven by the first successful validate_checkout run
    # (0.00063 GEN held at submit, ~0.00008 consumed, rest refunded at finalization
    #  — the budget is wei at 1e18, not 1e12; an earlier note here was 1000x off)
    with open("benchmark_fees.json") as f:
        fees = json.load(f)

    if not results.get("contract"):
        print("deploying fresh benchmark contract ...", flush=True)
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
                f"benchmark deploy failed: {receipt.get('result_name')} / "
                f"{receipt.get('txExecutionResultName')}")
        results["contract"] = contract
        print(f"benchmark contract: {contract}", flush=True)

    contract = results["contract"]
    done = {(c["url"], c["brand"]) for c in results["cases"]}

    dataset = [(u, b, True) for u, b in REAL_CASES] + \
              [(u, b, False) for u, b in FAKE_CASES]
    for i, (url, brand, expected) in enumerate(dataset, 1):
        if (url, brand) in done:
            print(f"[{i}/{len(dataset)}] SKIP (done): {url} [{brand}]", flush=True)
            continue
        label = "REAL " if expected else "FAKE"
        print(f"[{i}/{len(dataset)}] {label}: {url} [{brand}]", flush=True)
        case = run_case(client, account, contract, url, brand, expected, fees)
        results["cases"].append(case)
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)
        verdict = case.get("is_real")
        mark = "?" if verdict is None else ("PASS" if case.get("correct") else "FAIL")
        print(f"  -> is_real={verdict} {mark} ({case.get('duration_s')}s)", flush=True)
        time.sleep(5)  # stay under the RPC's Cloudflare rate limit

    # summary
    cases = [c for c in results["cases"] if c.get("is_real") is not None]
    tp = sum(1 for c in cases if c["expected_real"] and c["is_real"])
    fn = sum(1 for c in cases if c["expected_real"] and not c["is_real"])
    tn = sum(1 for c in cases if not c["expected_real"] and not c["is_real"])
    fp = sum(1 for c in cases if not c["expected_real"] and c["is_real"])
    n = len(cases)
    print("\n==== SUMMARY ====")
    print(f"ran: {n}/{len(dataset)}  (errors: {len(results['cases']) - n})")
    print(f"real URLs allowed  (TP): {tp}/{tp+fn}")
    print(f"fake URLs blocked  (TN): {tn}/{tn+fp}")
    print(f"real URLs blocked  (FN): {fn}")
    print(f"fake URLs allowed  (FP): {fp}")
    if n:
        print(f"accuracy: {(tp+tn)/n:.1%}")
    print(f"\nfull results: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
