"""Build and fetchability-check the v3 benchmark dataset.

Phishing side: brand-impersonation pages from the live OpenPhish community
feed (openphish.com/feed.txt) — hosted brand clones / phishing kits on
non-brand domains (github.io, blogspot, netlify, vercel, pages.dev, sketchy
TLDs). Unlike dead URLs in academic datasets, these are live right now.

Real side: legitimate checkout/account pages of well-known brands.

Every candidate is fetched locally first: the GenLayer validators fetch the
URL live during consensus, so a URL that doesn't serve content here would
produce an infra failure, not a detection data point.

Usage:
    python scripts/check_dataset.py        # (any venv with `requests`)
"""

import json

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# --- phishing / brand-impersonation candidates (from the OpenPhish feed) ----
# (url, claimed brand, expect_real=False, why it is a phishing-style case)
PHISHING_CASES = [
    ("https://vardhan2k3.github.io/Amazon-Clone-Project/checkout.html", "amazon",
     "Amazon checkout clone hosted on github.io"),
    ("https://vardhan2k3.github.io/Amazon-Clone-Project/orders.html", "amazon",
     "Amazon orders-page clone on github.io"),
    ("https://rajesh207k.github.io/Aamazon_clone_2026", "amazon",
     "'Aamazon' typo-clone hosted on github.io"),
    ("https://sukhpreetkaur2406.github.io/amazon-clone-project", "amazon",
     "Amazon storefront clone on github.io"),
    ("https://officialshahzebanwar-stack.github.io/NETFLIX-CLONE", "netflix",
     "Netflix clone hosted on github.io"),
    ("https://bhatinishant38.github.io/Netflix-Clone", "netflix",
     "Netflix clone hosted on github.io"),
    ("https://shrimohite1.github.io/spotify-frontend-clone", "spotify",
     "Spotify clone hosted on github.io"),
    ("http://login-outlook365.yzz.me/", "microsoft",
     "Outlook 365 login phish on .me TLD"),
    ("https://www.facebooklogin21.blogspot.com/", "facebook",
     "Facebook login phish on blogspot"),
    ("https://www.instagramlogin68.blogspot.com/", "instagram",
     "Instagram login phish on blogspot"),
    ("http://www.walletcoinbase-zeta.vercel.app/", "coinbase",
     "Coinbase wallet phish on vercel (unregistered brand)"),
    ("https://exoduswallethelpcenter.vercel.app/", "exodus",
     "Exodus wallet support phish on vercel (unregistered brand)"),
    ("http://ledgre-wallet-io.pages.dev/", "ledger",
     "'ledgre' typosquat of ledger.com (unregistered brand)"),
    ("https://fedx-logistics.netlify.app/login", "fedex",
     "'fedx' typosquat of fedex.com (unregistered brand)"),
]

# --- wrong-brand legitimate sites (v1/v2 benchmark continuity) -------------
WRONG_SELLER_CASES = [
    ("https://www.walmart.com/checkout", "amazon",
     "real Walmart checkout claimed as Amazon"),
    ("https://www.target.com/cart", "paypal",
     "real Target cart claimed as PayPal"),
    ("https://music.apple.com/us/browse", "spotify",
     "real Apple Music page claimed as Spotify"),
]

# --- legitimate checkout/account pages ---------------------------------------
REAL_CASES = [
    ("https://www.apple.com/shop/bag", "apple", "Apple bag"),
    ("https://www.amazon.com/gp/cart/view.html", "amazon", "Amazon cart"),
    ("https://www.paypal.com/signin", "paypal", "PayPal signin"),
    ("https://www.microsoft.com/en-us/store/buy", "microsoft", "MS Store"),
    ("https://www.netflix.com/YourAccount", "netflix", "Netflix account"),
    ("https://store.google.com/us", "google", "Google Store (subdomain)"),
    ("https://open.spotify.com", "spotify", "Spotify (subdomain)"),
    ("https://github.com/pricing", "github", "GitHub pricing"),
    # new brands, registered on-chain at benchmark start via add_official_domain
    ("https://www.walmart.com/cart", "walmart", "Walmart cart [walmart]"),
    ("https://www.target.com/cart", "target", "Target cart [target]"),
    ("https://www.facebook.com", "facebook", "Facebook homepage"),
    ("https://www.instagram.com", "instagram", "Instagram homepage"),
    ("https://www.ebay.com", "ebay", "eBay homepage"),
    ("https://www.bestbuy.com/cart", "bestbuy", "Best Buy cart"),
]

# brands to register on-chain before the run (brand -> official domain)
NEW_BRANDS = {
    "walmart": "walmart.com",
    "target": "target.com",
    "facebook": "facebook.com",
    "instagram": "instagram.com",
    "ebay": "ebay.com",
    "bestbuy": "bestbuy.com",
}


def check(url: str, brand: str, expect_real: bool) -> dict:
    result = {"url": url, "brand": brand, "expected_real": expect_real}
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": UA},
                            allow_redirects=True, verify=True)
        body = resp.text
        result["status"] = resp.status_code
        result["final_url"] = resp.url
        result["body_len"] = len(body)
        result["brand_kw"] = brand.lower() in body.lower()
        result["fetchable"] = (
            resp.status_code == 200 and len(body) > 200
        )
    except Exception as e:  # noqa: BLE001
        result["fetchable"] = False
        result["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    return result


def main():
    all_cases = (
        [(u, b, False, why) for u, b, why in PHISHING_CASES]
        + [(u, b, False, why) for u, b, why in WRONG_SELLER_CASES]
        + [(u, b, True, why) for u, b, why in REAL_CASES]
    )

    checked = []
    for url, brand, expect_real, why in all_cases:
        r = check(url, brand, expect_real)
        r["note"] = why
        checked.append(r)
        ok = "OK " if r["fetchable"] else "BAD"
        kw = "kw" if r.get("brand_kw") else "--"
        print(f"[{ok}] {kw} {url[:70]:<70} [{brand}] {why}")

    dataset = {
        "new_brands": NEW_BRANDS,
        "phishing": [c for c in checked if not c["expected_real"]],
        "real": [c for c in checked if c["expected_real"]],
    }
    with open("benchmarks/dataset_check.json", "w") as f:
        json.dump(dataset, f, indent=2)

    p_ok = sum(1 for c in dataset["phishing"] if c["fetchable"])
    r_ok = sum(1 for c in dataset["real"] if c["fetchable"])
    print(f"\nphishing fetchable: {p_ok}/{len(dataset['phishing'])}")
    print(f"real fetchable:     {r_ok}/{len(dataset['real'])}")
    print(f"\nfull check: benchmarks/dataset_check.json")


if __name__ == "__main__":
    main()
