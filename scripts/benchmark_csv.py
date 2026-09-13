"""GenCheck benchmark — CSV dataset (benchmarks/gencheck_benchmark.csv sample).

The CSV has 412 labeled rows (312 fake from phishing databases, 100 real).
Only 85 URLs are still live (phishing pages get taken down); the runnable
sample is every live fake (12) plus a balanced real set (16):

  - 12 live phishing URLs (5 brand-matched + 7 generic), straight from the
    phishing database rows
  - 8 curated brand checkout pages (shopify, nike, walmart, paypal, target,
    netflix, sephora, costco) — ebay.com/checkout excluded: ebay crashed the
    GenVM web module in the v1 benchmark (known infra risk)
  - 8 recognizable top-sites (bbc, nature, arxiv, mozilla, pinterest,
    office, cnn, flickr)

URLs are loaded from benchmarks/csv_live_check.json (the fetchability-check output) so
the exact long phishing URLs are preserved byte-for-byte. Brands not in the
seed registry run through the v3 prompt's general-knowledge fallback.

Usage:
    set GENCHECK_PRIVATE_KEY=0x...
    .venv-deploy/Scripts/python scripts/benchmark_csv.py
"""

import json
import os
import time

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet
from genlayer_py.transactions import is_successful

RESULTS_FILE = "benchmarks/benchmark_csv_results.json"

FAKE_DOMAINS = [
    "store.microsoft-surface.ru",
    "microsoft.userid-81d.ws",
    "microsoft-mail-outlook.myportfolio.com",
    "shubham-ebay-clone.netlify.app",
    "ikea-promotion.com",
    "trackyourpackageusps.blogspot.com.br",
    "login0365organizationsigning.com",
    "flqwakhjxr.np9q2f3.sbs",
    "filedoc-myportfolio.myportfolio.com",
    "stro.uscreen.io",
    "ledger.band",
    "sdvrg.blogspot.hr",
]

REAL_DOMAINS = [
    # curated brand checkouts
    "shopify.com",
    "nike.com",
    "walmart.com",
    "paypal.com",
    "target.com",
    "netflix.com",
    "sephora.com",
    "costco.com",
    # top sites
    "nature.com",
    "arxiv.org",
    "bbc.com",
    "mozilla.com",
    "pinterest.com",
    "office.com",
    "cnn.com",
    "flickr.com",
]


def load_sample():
    with open("benchmarks/csv_live_check.json", encoding="utf-8") as f:
        checked = json.load(f)
    by_domain = {c["domain"]: c for c in checked if c["fetchable"]}
    sample = []
    for dom in FAKE_DOMAINS + REAL_DOMAINS:
        c = by_domain[dom]
        sample.append({
            "url": c["url"], "brand": c["brand"], "domain": dom,
            "category": "phishing" if dom in FAKE_DOMAINS else "real",
            "expected_real": c["expected_verdict"] == "real",
            "source": c["source"],
        })
    return sample


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


def run_case(client, account, contract, case_info, fees):
    url, brand = case_info["url"], case_info["brand"]
    domain = case_info["domain"]
    case = dict(case_info, started_at=time.time())
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
        case["correct"] = case["is_real"] == case_info["expected_real"]
    case["duration_s"] = round(time.time() - case["started_at"], 1)
    return case


def main():
    private_key = os.environ["GENCHECK_PRIVATE_KEY"]
    account = create_account(private_key)
    client = create_client(chain=studio_devnet, account=account)
    print(f"account: {account.address}", flush=True)

    sample = load_sample()

    results = {"contract": None, "prompt_version": "v3-claimed-brand", "cases": []}
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            results = json.load(f)

    with open("benchmark_fees.json") as f:
        fees = json.load(f)

    if not results.get("contract"):
        print("deploying fresh CSV-benchmark contract ...", flush=True)
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
                f"csv deploy failed: {receipt.get('result_name')} / "
                f"{receipt.get('txExecutionResultName')}")
        results["contract"] = contract
        print(f"csv benchmark contract: {contract}", flush=True)

    contract = results["contract"]
    done = {(c["url"], c["brand"]) for c in results["cases"]}

    for i, case_info in enumerate(sample, 1):
        if (case_info["url"], case_info["brand"]) in done:
            print(f"[{i}/{len(sample)}] SKIP (done)", flush=True)
            continue
        label = "REAL" if case_info["expected_real"] else "FAKE"
        print(f"[{i}/{len(sample)}] {label}: {case_info['url'][:70]} "
              f"[{case_info['brand']}]", flush=True)
        case = run_case(client, account, contract, case_info, fees)
        results["cases"].append(case)
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)
        verdict = case.get("is_real")
        mark = "?" if verdict is None else ("PASS" if case.get("correct") else "FAIL")
        print(f"  -> is_real={verdict} {mark} ({case.get('duration_s')}s)", flush=True)
        time.sleep(5)

    cases = [c for c in results["cases"] if c.get("is_real") is not None]
    print("\n==== CSV BENCHMARK SUMMARY ====")
    for cat in ("phishing", "real"):
        cat_cases = [c for c in cases if c["category"] == cat]
        cat_all = [c for c in results["cases"] if c["category"] == cat]
        ok = sum(1 for c in cat_cases if c["correct"])
        print(f"{cat:<9} correct: {ok}/{len(cat_cases)} "
              f"(no verdict: {len(cat_all) - len(cat_cases)})")
    n = len(cases)
    if n:
        acc = sum(1 for c in cases if c["correct"]) / n
        print(f"accuracy: {acc:.1%} on {n} verdicts")
    print(f"\nfull results: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
