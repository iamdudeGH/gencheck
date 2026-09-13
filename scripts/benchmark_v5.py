"""GenCheck benchmark v5 — the live contract, 50-case union dataset.

Why this exists separately from the other two harnesses: benchmark_v3.py and
benchmark_csv.py each DEPLOY their own contract from
contracts/shopping_validator.py, which is the v4 build. Neither can target the
deployed v5 contract. This one deploys nothing and benchmarks whatever
`load_contract_address()` resolves — i.e. the contract the portal is actually
using.

Dataset: the union of both curated sets, deduplicated on (url, brand) — 50
cases, 21 phishing / 3 wrong-seller / 26 real. Two deliberate repeats
(target.com, walmart.com) exercise the cache path.

Two differences from the earlier harnesses, both learned the hard way:

 1. The verdict is decoded from the leader receipt's `payload.readable`, not by
    reading the cache back. On v5 that matters: `unverifiable` is deliberately
    NOT cached, so a cache read cannot tell "the contract returned
    unverifiable" apart from "the tx never landed". Decoding also exposes v5's
    `cached` flag and the real confidence (v4 stored a hardcoded 100).

 2. retry() treats connection errors as transient. The earlier harnesses retried
    only JSON/timeout failures, so a mid-run ConnectionResetError aborted them.
    Symmetrically, wait_bounded() deliberately does NOT retry `Timeout` — see
    its docstring.

Per-case v5 integrity fields recorded alongside the verdict:
    cached              verdict came from cache, not fresh consensus
    cache_brand_matches the persisted entry's brand equals the claimed brand
                        (v4 keyed the cache on domain alone, so a verdict judged
                        for one brand could be served for another)

The summary separates blocks reached by DETECTION from blocks reached by
FAILING CLOSED. That split is the point of this harness: every earlier result
file in benchmarks/ stores only `is_real`, so a caught scam and an unreachable
page are the same value in them. Any block reporting confidence 0 is
fail-closed, not a catch.

Usage:
    set GENCHECK_PRIVATE_KEY=0x...
    .venv-deploy/Scripts/python scripts/benchmark_v5.py

Interrupting and re-running resumes: results are written after every case and
cases that already have a verdict are skipped.
"""

import json
import os
import sys
import time
from urllib.parse import urlparse

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet
from genlayer_py.transactions import is_successful

# repo root on the path, so this runs from anywhere — `gencheck` for the
# contract address, `scripts` for the two datasets being unioned
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import benchmark_csv  # noqa: E402
import benchmark_v3  # noqa: E402

RESULTS_FILE = os.path.join(ROOT, "benchmarks", "benchmark_v5_results.json")
PROMPT_VERSION = "v5-admin-gated-cache-integrity"

# Verdicts that mean the validators actually identified a problem. Everything
# else that blocks (unverifiable, unsure) is the gate failing closed.
DETECTION_VERDICTS = {"scam", "wrong_seller"}

# v5's registry is seeded with amazon/apple/paypal/spotify at deploy; walmart
# was registered during deploy verification. target is not, and the v3 harness
# registered walmart+target before its run — so register target here too, or the
# target cases would run through the general-knowledge fallback and not be
# comparable to the historical numbers.
EXTRA_BRANDS = {"target": "target.com"}

# Cases recorded as skipped rather than retried.
#
# https://music.apple.com/us/browse stalled past its one-pass cap (12.5 min) on
# both attempts — a heavy JS single-page app on a bot-hostile host, the same
# class as the ebay case the v1 benchmark lost to NO_MAJORITY. Retrying it
# indefinitely blocks every remaining case behind one unfetchable page, so it is
# skipped deliberately and reported as skipped rather than silently dropped.
#
# A skipped case is NOT scored and is NOT a contract failure: the tx was
# submitted, the network just never produced a verdict.
SKIP_URLS = {
    "https://music.apple.com/us/browse",
}


def build_dataset():
    """Union of both curated datasets, deduplicated on (url, brand)."""
    cases = []
    for url, brand, note in benchmark_v3.PHISHING_CASES:
        cases.append({"url": url, "brand": brand, "category": "phishing",
                      "expected_real": False, "note": note, "source": "v3"})
    for url, brand, note in benchmark_v3.WRONG_SELLER_CASES:
        cases.append({"url": url, "brand": brand, "category": "wrong_seller",
                      "expected_real": False, "note": note, "source": "v3"})
    for url, brand, note in benchmark_v3.REAL_CASES:
        cases.append({"url": url, "brand": brand, "category": "real",
                      "expected_real": True, "note": note, "source": "v3"})
    for c in benchmark_csv.load_sample():
        cases.append({"url": c["url"], "brand": c["brand"],
                      "category": c["category"], "expected_real": c["expected_real"],
                      "note": c["source"], "source": "csv"})

    seen, unique = set(), []
    for c in cases:
        key = (c["url"], c["brand"])
        if key in seen:
            continue
        seen.add(key)
        c["domain"] = urlparse(c["url"]).netloc.lower()
        unique.append(c)
    return unique


def retry(fn, tries=10, base_delay=15):
    """Retry transient RPC failures, INCLUDING connection resets.

    The earlier harnesses omitted network errors here, which is precisely why a
    ConnectionResetError killed a run instead of being retried.
    """
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            transient = any(s in msg for s in (
                "invalid JSON", "DOCTYPE", "1010", "Timeout", "timed out",
                "Connection aborted", "ConnectionResetError", "ProtocolError",
                "ConnectionError", "Max retries exceeded", "Read timed out",
                "RemoteDisconnected", "502", "503", "504",
                # cost the music.apple.com verdict on the first pass:
                # "eth_getTransactionByHash failed (code=-32002): Service
                # temporarily unavailable" — a node outage, not a bad tx
                "-32002", "Service temporarily unavailable",
            ))
            if attempt == tries or not transient:
                raise
            print(f"    transient ({type(e).__name__}), retry {attempt}/{tries - 1} "
                  f"in {base_delay * attempt}s: {msg[:100]}", flush=True)
            time.sleep(base_delay * attempt)


def wait_bounded(client, tx_id, tries=3, base_delay=10):
    """Wait for finalization ONCE, plus retries only for transport failures.

    Deliberately does NOT retry "Timeout"/"timed out". `wait_for_finalization`
    already polls for 12.5 min (150 x 5s), so treating its timeout as transient
    and re-entering it turns a single stalled case into ~2 hours. That is what
    happened to nike.com/checkout, which sat past its one-pass cap while a whole
    run waited on it.

    Connection errors ARE retried — those are the transport failing, not the
    transaction, and a fresh connection usually succeeds.
    """
    for attempt in range(1, tries + 1):
        try:
            return client.wait_for_finalization(tx_id, retries=150, interval=5000)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "timed out" in msg.lower() or "Timeout" in msg:
                raise  # the tx itself is stuck — do not re-wait
            transient = any(s in msg for s in (
                "Connection aborted", "ConnectionResetError", "ProtocolError",
                "ConnectionError", "Max retries exceeded", "Read timed out",
                "RemoteDisconnected", "502", "503", "504",
            ))
            if attempt == tries or not transient:
                raise
            print(f"    transport error, retry {attempt}/{tries - 1} "
                  f"in {base_delay * attempt}s: {msg[:90]}", flush=True)
            time.sleep(base_delay * attempt)


def decode_leader_verdict(tx):
    """The leader's returned dict, or None.

    The network changed receipt shape around 12 Sept 2026: rounds after that
    come back with `eq_outputs` EMPTY and the decoded verdict in
    `result.payload.readable` instead. Every receipt carries `readable`, so that
    is the primary path; see scripts/decode_verdict.py for the old shape.
    """
    for r in (tx.get("consensus_data") or {}).get("leader_receipt") or []:
        if r.get("mode") != "leader":
            continue
        readable = ((r.get("result") or {}).get("payload") or {}).get("readable")
        if isinstance(readable, str):
            try:
                return json.loads(readable)
            except Exception:  # noqa: BLE001
                return {"_unparsed": readable[:300]}
    return None


def run_case(client, account, contract, case, fees):
    domain = case["domain"]
    out = dict(case, started_at=time.time())
    try:
        tx_id = retry(lambda: client.write_contract(
            address=contract, function_name="validate_checkout",
            args=[case["url"], case["brand"]], account=account,
            fees={"distribution": fees["distribution"],
                  "feeValue": fees["paid_fee_value"]},
        ))
        out["tx_id"] = tx_id
        print(f"  submitted {tx_id}", flush=True)   # full hash, so it is usable

        receipt = wait_bounded(client, tx_id)
        out["result_name"] = receipt.get("result_name")
        out["execution"] = receipt.get("txExecutionResultName")
        out["consensus_ok"] = bool(
            is_successful(receipt)
            and receipt.get("txExecutionResultName") == "FINISHED_WITH_RETURN")

        # the real verdict, straight from the leader's return value
        tx = retry(lambda: client.get_transaction(tx_id))
        verdict = decode_leader_verdict(tx)
        if verdict is not None:
            out["verdict"] = verdict.get("verdict")
            out["is_real"] = verdict.get("is_real")
            out["confidence"] = verdict.get("confidence")
            out["cached"] = verdict.get("cached")
            out["reasons"] = (verdict.get("reasons") or [])[:3]
            out["evidence"] = (verdict.get("evidence") or [])[:4]

        # the persisted entry, for the v5 cache-integrity checks
        try:
            entry = retry(lambda: client.read_contract(
                address=contract, function_name="get_cached_result", args=[domain]))
            out["cache_entry"] = entry
            if isinstance(entry, dict):
                out["cache_brand"] = entry.get("brand")
                out["cache_brand_matches"] = (entry.get("brand") == case["brand"])
        except Exception as e:  # noqa: BLE001
            out["cache_entry"] = None
            # v5 does not cache `unverifiable` — absence is expected there
            out["cache_absent"] = type(e).__name__
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e)[:400]}"

    if out.get("is_real") is not None:
        out["correct"] = out["is_real"] == case["expected_real"]
    out["duration_s"] = round(time.time() - out["started_at"], 1)
    return out


def summarise(results, dataset):
    cases = results["cases"]
    scored = [c for c in cases if c.get("is_real") is not None]
    print("\n==== v5 SUMMARY ====")
    for cat in ("phishing", "wrong_seller", "real"):
        cat_scored = [c for c in scored if c["category"] == cat]
        cat_all = [c for c in cases if c["category"] == cat]
        if not cat_all:
            continue
        ok = sum(1 for c in cat_scored if c.get("correct"))
        print(f"  {cat:<13} correct {ok}/{len(cat_scored)}"
              f"   (no verdict: {len(cat_all) - len(cat_scored)})")

    n = len(scored)
    if n:
        acc = sum(1 for c in scored if c.get("correct")) / n
        print(f"\n  accuracy: {acc:.1%} on {n} verdicts "
              f"({len(cases) - n} without a verdict)")

    # the safety metric that matters: a real checkout must never be blocked
    real_cases = [c for c in scored if c["expected_real"]]
    fn = [c for c in real_cases if not c.get("correct")]
    print(f"  false negatives (real blocked): {len(fn)}/{len(real_cases)}")
    for c in fn:
        print(f"      FN: {c['url']} [{c['brand']}] -> {c.get('verdict')}")
    fake_cases = [c for c in scored if not c["expected_real"]]
    fp = sum(1 for c in fake_cases if not c.get("correct"))
    print(f"  false positives (fake allowed): {fp}/{len(fake_cases)}")

    # -- the split the earlier harnesses could not produce ---------------------
    # Their result files store only is_real, so a detection and a page that
    # would not load are the same value in them. This is the number that says
    # how much of the block rate is actually detection.
    #
    # Reported against two denominators, because they answer different
    # questions: the lookalikes alone say how well the gate detects, while
    # including the real false negatives shows what a legitimate customer
    # experiences. Quoting one without naming it is how "14/23" and "15/26"
    # become an apparent contradiction.
    def split(group):
        det = sum(1 for c in group if c.get("verdict") in DETECTION_VERDICTS)
        fail = sum(1 for c in group if c.get("verdict") == "unverifiable")
        uns = sum(1 for c in group if c.get("verdict") == "unsure")
        return det, fail, uns

    lookalikes = [c for c in scored if not c["expected_real"]]
    blocked = [c for c in lookalikes if not c.get("is_real")]
    all_blocked = [c for c in scored if not c.get("is_real")]
    if blocked:
        det, fail, uns = split(blocked)
        print(f"\n  -- how the {len(blocked)} lookalikes were blocked --")
        print(f"  by DETECTION (scam/wrong_seller): {det}/{len(blocked)}")
        print(f"  by FAIL-CLOSED (page unreachable): {fail}/{len(blocked)}")
        print(f"  by unsure: {uns}/{len(blocked)}")
        if len(all_blocked) != len(blocked):
            d2, f2, u2 = split(all_blocked)
            n_fn = len(all_blocked) - len(blocked)
            print(f"  (with the {n_fn} real false negatives counted too, "
                  f"out of {len(all_blocked)} blocks: "
                  f"detection {d2}, fail-closed {f2}, unsure {u2})")
        if fail:
            print("  fail-closed lookalikes (these did NOT exercise detection):")
            for c in blocked:
                if c.get("verdict") == "unverifiable":
                    print(f"      {c['domain']:<42} [{c['brand']}]")

    print("\n  -- v5-specific integrity --")
    mism = [c for c in cases if c.get("cache_brand_matches") is False]
    print(f"  cache entries whose brand != claimed brand: {len(mism)}"
          f"{'  <-- v4 would have served the wrong brand here' if not mism else '  <-- REGRESSION'}")
    cached_hits = sum(1 for c in cases if c.get("cached"))
    print(f"  served from cache: {cached_hits}/{len(cases)}")
    unver = [c for c in cases if c.get("verdict") == "unverifiable"]
    print(f"  unverifiable (fail-closed, not cached): {len(unver)}")
    skipped = [c for c in cases if c.get("skipped")]
    noverdict = [c for c in cases
                 if c.get("is_real") is None and not c.get("skipped")]
    print(f"  skipped by operator (not scored): {len(skipped)}")
    for c in skipped:
        print(f"      {c['domain']} [{c['brand']}] — {c.get('skipped_reason', '')}")
    print(f"  no verdict at all: {len(noverdict)}")

    print("\n  -- consensus --")
    nocon = [c for c in cases if c.get("consensus_ok") is False]
    print(f"  consensus_ok: {len(cases) - len(nocon)}/{len(cases)}"
          + (f"   failures: {[c.get('result_name') for c in nocon]}" if nocon else ""))

    print(f"\nfull results: {RESULTS_FILE}")


def main():
    private_key = os.environ["GENCHECK_PRIVATE_KEY"]
    account = create_account(private_key)
    client = create_client(chain=studio_devnet, account=account)

    from gencheck import load_contract_address  # noqa: E402
    contract = load_contract_address()
    print(f"account : {account.address}")
    print(f"contract: {contract}   (benchmarks the deployed contract — no deploy)\n",
          flush=True)

    with open(os.path.join(ROOT, "benchmark_fees.json")) as f:
        fees = json.load(f)

    results = {"contract": contract, "prompt_version": PROMPT_VERSION, "cases": []}
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            prev = json.load(f)
        if prev.get("contract") == contract:
            results = prev
            print(f"resuming: {len(results['cases'])} case(s) already recorded\n")
        else:
            print(f"existing results are for {prev.get('contract')} — starting fresh\n")

    # -- preflight: brands the dataset needs that the registry lacks ----------
    for brand, official in EXTRA_BRANDS.items():
        current = retry(lambda b=brand: client.read_contract(
            address=contract, function_name="get_official_domain", args=[b]))
        if current:
            print(f"registry: {brand} -> {current} (already registered)")
            continue
        print(f"registry: registering {brand} -> {official} ...", flush=True)
        tx_id = retry(lambda b=brand, d=official: client.write_contract(
            address=contract, function_name="add_official_domain",
            args=[b, d], account=account,
            fees={"distribution": fees["distribution"],
                  "feeValue": fees["paid_fee_value"]}))
        retry(lambda t=tx_id: client.wait_for_finalization(
            t, retries=150, interval=5000))
        print(f"registry: {brand} -> {official} registered", flush=True)

    dataset = build_dataset()
    # nike.com/checkout already stalled past its one-pass cap once. Run it last
    # so a repeat stall cannot hold up everything else — results are written
    # incrementally, so the other cases land well before it. sort() is stable,
    # so the rest keep dataset order.
    dataset.sort(key=lambda c: "nike.com/checkout" in c["url"])

    # An earlier pass may have recorded a stall case without a verdict. Mark it
    # skipped so `done` below treats it as finished instead of retrying it.
    for c in results["cases"]:
        if c.get("url") in SKIP_URLS:
            c["skipped"] = True

    done = {(c["url"], c["brand"]) for c in results["cases"]
            if c.get("is_real") is not None or c.get("skipped")}
    print(f"\ndataset: {len(dataset)} cases "
          f"({sum(1 for c in dataset if c['category'] == 'phishing')} phishing, "
          f"{sum(1 for c in dataset if c['category'] == 'wrong_seller')} wrong_seller, "
          f"{sum(1 for c in dataset if c['category'] == 'real')} real)\n", flush=True)

    run_durations = []
    for i, case in enumerate(dataset, 1):
        if (case["url"], case["brand"]) in done:
            print(f"[{i}/{len(dataset)}] SKIP (done): {case['url'][:60]}", flush=True)
            continue
        if case["url"] in SKIP_URLS:
            print(f"[{i}/{len(dataset)}] SKIP(operator): {case['url'][:60]}", flush=True)
            out = dict(case, skipped=True, duration_s=0.0,
                       skipped_reason="stalled past the one-pass cap; skipped by request")
            results["cases"].append(out)
            with open(RESULTS_FILE, "w") as f:
                json.dump(results, f, indent=2, default=str)
            continue

        label = {"phishing": "PHISH", "wrong_seller": "WRONG", "real": "REAL "}[case["category"]]
        print(f"[{i}/{len(dataset)}] {label}: {case['url'][:66]} [{case['brand']}]",
              flush=True)
        out = run_case(client, account, contract, case, fees)
        results["cases"].append(out)
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)

        if out.get("duration_s"):
            run_durations.append(out["duration_s"])
        mark = ("?" if out.get("is_real") is None
                else ("PASS" if out.get("correct") else "FAIL"))
        extra = ""
        if out.get("cached") is not None:
            extra += " cached" if out["cached"] else " fresh"
        if out.get("cache_brand_matches") is False:
            extra += " !!CACHE-BRAND-MISMATCH"
        print(f"  -> verdict={out.get('verdict')} is_real={out.get('is_real')} "
              f"{mark} ({out.get('duration_s')}s){extra}", flush=True)

        remaining = sum(1 for c in dataset[i:]
                        if (c["url"], c["brand"]) not in done)
        if run_durations and remaining:
            eta = sum(run_durations) / len(run_durations) * remaining / 60
            print(f"     ~{eta:.0f} min left for {remaining} case(s)", flush=True)
        time.sleep(5)

    summarise(results, dataset)


if __name__ == "__main__":
    main()
