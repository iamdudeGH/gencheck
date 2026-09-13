"""Fetchability-check every URL in benchmarks/gencheck_benchmark.csv (concurrently).

Most phishing-database URLs are taken down; the GenLayer validators fetch
pages live, so only URLs serving content now are usable benchmark cases.
Writes benchmarks/csv_live_check.json.

Usage:
    .venv-deploy/Scripts/python scripts/check_csv.py
"""

import csv
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def domain_of(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()


def check_row(row):
    url = row["checkout_link"].strip()
    r = {"url": url, "domain": domain_of(url), "brand": row["brand"].strip(),
         "expected_verdict": row["expected_verdict"].strip(),
         "source": row["source"].strip()}
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": UA},
                            allow_redirects=True, verify=True)
        r["status"] = resp.status_code
        r["body_len"] = len(resp.text)
        r["fetchable"] = resp.status_code == 200 and len(resp.text) > 200
    except Exception as e:  # noqa: BLE001
        r["fetchable"] = False
        r["error"] = f"{type(e).__name__}: {str(e)[:100]}"
    return r


def main():
    with open("benchmarks/gencheck_benchmark.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"checking {len(rows)} urls ...", flush=True)

    with ThreadPoolExecutor(max_workers=40) as pool:
        results = list(pool.map(check_row, rows))

    with open("benchmarks/csv_live_check.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)

    from collections import Counter
    live = [r for r in results if r["fetchable"]]
    print(f"live: {len(live)}/{len(results)}")
    print("live by source:", Counter(r["source"] for r in live))
    print("live by verdict:", Counter(r["expected_verdict"] for r in live))


if __name__ == "__main__":
    main()
