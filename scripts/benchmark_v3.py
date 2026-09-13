"""GenCheck benchmark v3 — live phishing pages + v3 prompt.

Dataset sources:
  - phishing: brand-impersonation pages from the live OpenPhish community
    feed (openphish.com/feed.txt) — brand clones on github.io / netlify /
    vercel / pages.dev, plus typosquats. All verified fetchable before the
    run (see scripts/check_dataset.py, benchmarks/dataset_check.json).
  - wrong-seller: legitimate sites claimed under the wrong brand (v1/v2
    continuity cases).
  - real: legitimate checkout/account pages, including two brands
    (walmart, target) registered on-chain via add_official_domain at run
    start, and subdomain edge cases.

Cache-key note: walmart/target real cases use the apex form (walmart.com)
while the wrong-seller cases use www.walmart.com — distinct cache keys, so
no case short-circuits another.

Usage:
    set GENCHECK_PRIVATE_KEY=0x...
    .venv-deploy/Scripts/python scripts/benchmark_v3.py
"""

import json
import os
import time

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet
from genlayer_py.transactions import is_successful

RESULTS_FILE = "benchmarks/benchmark_v3_results.json"

# brands registered on-chain via add_official_domain before the run
NEW_BRANDS = {
    "walmart": "walmart.com",
    "target": "target.com",
}

PHISHING_CASES = [
    # (url, brand, note) — brand-impersonation pages from the OpenPhish feed
    ("https://vardhan2k3.github.io/Amazon-Clone-Project/checkout.html", "amazon",
     "Amazon checkout clone on github.io"),
    ("https://rajesh207k.github.io/Aamazon_clone_2026", "amazon",
     "'Aamazon' typo-clone on github.io"),
    ("https://sukhpreetkaur2406.github.io/amazon-clone-project", "amazon",
     "Amazon storefront clone on github.io"),
    ("https://officialshahzebanwar-stack.github.io/NETFLIX-CLONE", "netflix",
     "Netflix clone on github.io"),
    ("https://bhatinishant38.github.io/Netflix-Clone", "netflix",
     "Netflix clone on github.io"),
    ("https://shrimohite1.github.io/spotify-frontend-clone", "spotify",
     "Spotify clone on github.io"),
    ("https://exoduswallethelpcenter.vercel.app/", "exodus",
     "Exodus wallet phish on vercel (unregistered brand)"),
    ("https://fedx-logistics.netlify.app/login", "fedex",
     "'fedx' typosquat on netlify (unregistered brand)"),
    ("http://ledgre-wallet-io.pages.dev/", "ledger",
     "'ledgre' typosquat on pages.dev (unregistered, 403 to local curl — may fail)"),
]

WRONG_SELLER_CASES = [
    ("https://www.walmart.com/checkout", "amazon",
     "real Walmart checkout claimed as Amazon"),
    ("https://www.target.com/cart", "paypal",
     "real Target cart claimed as PayPal"),
    ("https://music.apple.com/us/browse", "spotify",
     "real Apple Music page claimed as Spotify"),
]

REAL_CASES = [
    ("https://www.apple.com/shop/bag", "apple", "Apple bag"),
    ("https://www.amazon.com/gp/cart/view.html", "amazon", "Amazon cart"),
    ("https://www.paypal.com/signin", "paypal", "PayPal signin"),
    ("https://www.microsoft.com/en-us/store/buy", "microsoft", "MS Store"),
    ("https://www.netflix.com/YourAccount", "netflix", "Netflix account"),
    ("https://store.google.com/us", "google", "Google Store (subdomain)"),
    ("https://open.spotify.com", "spotify", "Spotify (subdomain)"),
    ("https://github.com/pricing", "github", "GitHub pricing"),
    ("https://walmart.com/cart", "walmart", "Walmart cart (new brand, apex)"),
    ("https://target.com/cart", "target", "Target cart (new brand, apex)"),
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


def run_case(client, account, contract, url, brand, category, expected_real, fees):
    domain = extract_domain(url)
    case = {"url": url, "brand": brand, "domain": domain, "category": category,
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
        case["consensus_ok"] = bool(
            is_successful(receipt)
            and receipt.get("txExecutionResultName") == "FINISHED_WITH_RETURN")

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

    results = {"contract": None, "prompt_version": "v3-claimed-brand", "cases": []}
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            results = json.load(f)

    with open("benchmark_fees.json") as f:
        fees = json.load(f)

    if not results.get("contract"):
        print("deploying fresh v3 benchmark contract ...", flush=True)
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
                f"v3 deploy failed: {receipt.get('result_name')} / "
                f"{receipt.get('txExecutionResultName')}")
        results["contract"] = contract
        print(f"v3 benchmark contract: {contract}", flush=True)

        # register the extra brands for the real-side cases
        for brand, domain in NEW_BRANDS.items():
            tx_id = retry(lambda b=brand, d=domain: client.write_contract(
                address=contract, function_name="add_official_domain",
                args=[b, d], account=account,
                fees={"distribution": fees["distribution"],
                      "feeValue": fees["paid_fee_value"]},
            ))
            retry(lambda t=tx_id: client.wait_for_finalization(
                t, retries=150, interval=5000))
            print(f"  registered brand: {brand} -> {domain}", flush=True)

    contract = results["contract"]
    done = {(c["url"], c["brand"]) for c in results["cases"]}

    dataset = (
        [(u, b, "phishing", False, note) for u, b, note in PHISHING_CASES]
        + [(u, b, "wrong_seller", False, note) for u, b, note in WRONG_SELLER_CASES]
        + [(u, b, "real", True, note) for u, b, note in REAL_CASES]
    )
    for i, (url, brand, category, expected, note) in enumerate(dataset, 1):
        if (url, brand) in done:
            print(f"[{i}/{len(dataset)}] SKIP (done): {url} [{brand}]", flush=True)
            continue
        print(f"[{i}/{len(dataset)}] {category.upper()}: {url} [{brand}] — {note}",
              flush=True)
        case = run_case(client, account, contract, url, brand, category,
                        expected, fees)
        case["note"] = note
        results["cases"].append(case)
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)
        verdict = case.get("is_real")
        mark = "?" if verdict is None else ("PASS" if case.get("correct") else "FAIL")
        print(f"  -> is_real={verdict} {mark} ({case.get('duration_s')}s)", flush=True)
        time.sleep(5)

    # summary
    cases = [c for c in results["cases"] if c.get("is_real") is not None]
    print("\n==== v3 SUMMARY ====")
    for cat in ("phishing", "wrong_seller", "real"):
        cat_cases = [c for c in cases if c["category"] == cat]
        cat_all = [c for c in results["cases"] if c["category"] == cat]
        if not cat_all:
            continue
        ok = sum(1 for c in cat_cases if c["correct"])
        print(f"{cat:<13} correct: {ok}/{len(cat_cases)} "
              f"(no verdict: {len(cat_all) - len(cat_cases)})")
    n = len(cases)
    if n:
        acc = sum(1 for c in cases if c["correct"]) / n
        print(f"accuracy: {acc:.1%} on {n} verdicts")
    print(f"\nfull results: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
