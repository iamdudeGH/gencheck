# GenCheck Accuracy Benchmark

**The live contract is v5.** Its result is the first section below. Everything
after it is the v1 → CSV arc that led there, kept as the record. Those earlier
runs store only `is_real`, so their block rates cannot separate a detection from
a page that would not load — a caveat marked at each one.

---

# v5 — the live contract (current)

**Contract:** `0xD914Bf44b78df2CC3FeFf343769800E11690288B` · prompt
`v5-admin-gated-cache-integrity` · 13 Sept 2026 · raw data
`benchmarks/benchmark_v5_results.json`

50 labeled cases through real consensus on the live contract: 21 phishing,
3 wrong-seller, 26 real. 49 produced a verdict — `music.apple.com` was skipped
by operator request after stalling twice. 46 were correct.

| Metric | Value |
|---|---|
| Cases attempted | 50 |
| Verdicts produced | 49 |
| **Accuracy on verdicts** | **46/49 = 93.9%** |
| False positives (fake allowed) | **0** |
| False negatives (real blocked) | **3** |
| Phishing blocked | 21/21 |
| Wrong seller blocked | 2/2 |
| Real allowed | 23/26 |
| `consensus_ok` | 50/50 |
| Verdicts served from cache | 3 |

## How the 23 blocks were actually reached

This is the number the earlier runs could not produce. `benchmark_results.json`,
`benchmark_v3_results.json` and `benchmark_csv_results.json` each store only
`is_real`, so a block earned by *catching* a scam and a block earned by *failing
to load the page* are the same value in those files. They are not the same
result, and only one of them is detection.

| Mechanism | Count |
|---|---|
| Detection (`scam` / `wrong_seller`) | **14/23** |
| Fail-closed (page unreachable → `unverifiable`) | 7/23 |
| `unsure` | 2/23 |

The v5 result file stores `verdict` per case, so this split is checkable rather
than asserted. **Any block reporting confidence 0 is fail-closed, not a catch.**

Three of the 7 fail-closed blocks matter for how this project is read:
`vardhan2k3.github.io`, `rajesh207k.github.io` and `sukhpreetkaur2406.github.io`
— the Amazon clones — now return **404 "Site not found" from GitHub Pages**.
They pass by failing closed and detect nothing. `vardhan2k3.github.io` is the
scenario wired into `portal/app.py`, `demo/shopping_agent.py` and the README, so
the headline demo case is currently a dead page.

## The 3 false negatives

| Domain | Verdict | Cause |
|---|---|---|
| sephora.com/checkout | `unverifiable` | bot-blocks the validators |
| costco.com/checkout | `unverifiable` | bot-blocks the validators |
| office.com | **`wrong_seller`** | genuine misjudgement, confidence 93 |

Two are the documented fail-closed price: a real page the validators cannot
reach is indistinguishable from one that will not load, and the contract blocks
both. `portal/app.py` already expects `unverifiable` for sephora, so this is a
known cost rather than a surprise.

`office.com` is the one genuine error, and it repeats a v3/CSV failure exactly.
The dataset labels the brand as the generic string "office", and a
domain-ownership rule correctly observes that office.com is not a domain
belonging to a brand called "office" — the same reasoning the v3 CSV run
recorded. It is a labelling artifact in the dataset, and it is still scored as a
failure here rather than explained away, because the contract has no way to know
the label is wrong. Any agent trusting a caller-supplied brand string inherits
this.

## v5 contract integrity — checked on chain, not in the source

The defects v5 exists to close, verified against what the live contract actually
did rather than what it says it does:

| Check | Result |
|---|---|
| Cache entries whose stored brand != the claimed brand | **0** |
| `unverifiable` results cached | **0/7** |
| Verdicts served from cache | 3/50 |
| `consensus_ok` | 50/50 |

v4 keyed the cache on domain alone, so a verdict judged for one brand could be
served for another; v4 also cached a fetch failure as `is_real: false`, which
permanently blacklisted any domain that was briefly down or that blocks
datacenter traffic. Both are confirmed absent in the live run. The 3 cache hits
include two deliberate repeats (`target.com`, `walmart.com`) that exist to
exercise the path.

## Notable

- **`nike.com/checkout` passed as `real` in 62.8s.** This case stalled the run
  twice across two sessions and produced a wrong intermediate diagnosis — that a
  transaction stuck at the head of the account's nonce queue was blocking every
  later one. It was not. The case simply outlasted the harness cap, and once
  that cap was bounded it resolved normally.
- **`mozilla.com` took 351s**, roughly 6× the median, and still resolved
  correctly. Latency on studio-dev remains the dominant source of variance.

---

# v1 — the original 18-case run

**Question:** When a shopping agent is about to pay a checkout URL, how often
does GenLayer's validator consensus correctly decide "real seller" vs
"lookalike/wrong-brand scam"?

- **Network:** studio-dev (chain ID 61997), real validators, real web fetches,
  real LLM judgment (gpt-5.4 via the network's LLM router)
- **Contract:** `0x04a9cCB5Cd21D36d5345577dcEE3CEDE19A0917d` (fresh deployment,
  clean cache — every case got a fresh judgment, no cache hits)
- **Consensus:** `gl.eq_principle.prompt_comparative` — validators must agree
  on the `is_real` verdict
- **Date:** 9 September 2026
- **Raw data:** `benchmarks/benchmark_results.json`, `benchmarks/benchmark_recovered.json`,
  `benchmarks/benchmark_retries.json` (per-case tx hashes, statuses, durations)

## Methodology

18 labeled cases, all distinct domains (so the contract's domain cache never
short-circuits a case):

- **9 REAL** — legitimate checkout/account pages for the claimed brand
  (including subdomain edge cases like `store.google.com` and
  `open.spotify.com` that a naive exact-match check would fail).
- **9 FAKE** — the classic phishing pattern: a real, fetchable page claiming
  the wrong brand (an "apple" checkout on bing.com, "paypal" on ebay.com,
  "amazon" on walmart.com, etc.).

Each case = one real consensus transaction: validators fetch the checkout URL
**and** the brand's official site, an LLM judges, validators compare verdicts.

## Results

### Real URLs (should → allow pay): 9/9 correct — 100%

| # | Checkout URL | Claimed brand | Verdict | |
|---|---|---|---|---|
| 1 | apple.com/shop/bag | apple | real | ✅ |
| 2 | www.apple.com/shop/watch | apple | real | ✅ |
| 3 | www.amazon.com/gp/cart | amazon | real | ✅ |
| 4 | www.paypal.com/signin | paypal | real | ✅ |
| 5 | www.microsoft.com/store | microsoft | real | ✅ |
| 6 | www.netflix.com/YourAccount | netflix | real | ✅ |
| 7 | github.com/pricing * | github | real | ✅ |
| 8 | store.google.com/us | google | real | ✅ |
| 9 | open.spotify.com | spotify | real | ✅ |

\* `github.com/settings/billing` redirected to a login wall and the leader
execution went idle; retried with `github.com/pricing` (see Failures).

**No legitimate checkout was ever blocked** (0 false negatives). Subdomains of
official domains (store.google.com, open.spotify.com) are correctly accepted.

### Fake URLs (should → block pay): 5/8 correct — 62.5%

| # | Checkout URL | Claimed brand | Verdict | |
|---|---|---|---|---|
| 10 | www.bing.com/shop | apple | not real | ✅ blocked |
| 11 | store.steampowered.com/cart | apple | not real | ✅ blocked |
| 12 | www.ebay.com/sl/list | paypal | — no verdict | ⚠️ infra failure |
| 13 | www.walmart.com/checkout | amazon | **real** | ❌ allowed |
| 14 | mail.yahoo.com | microsoft | not real | ✅ blocked |
| 15 | about.gitlab.com * | github | not real | ✅ blocked |
| 16 | www.hulu.com | netflix | not real | ✅ blocked |
| 17 | music.apple.com/us/browse | spotify | **real** | ❌ allowed |
| 18 | www.target.com/cart | paypal | **real** | ❌ allowed |

\* `gitlab.com/users/sign_in` failed with `WEBPAGE_LOAD_FAILED`; retried with
`about.gitlab.com` (see Failures).

### Headline numbers

| Metric | Value |
|---|---|
| Cases attempted | 18 |
| Verdicts produced | 17 (94.4%) |
| **Accuracy on verdicts** | **14/17 = 82.4%** |
| Real-URL recall (TPR) | **9/9 = 100%** — a legit checkout is never blocked |
| Fake-URL block rate (TNR) | 5/8 = 62.5% |
| False negatives (real blocked) | **0** |
| False positives (fake allowed) | 3 |
| Infra failures (no verdict) | 1 (ebay) |

## The failure pattern — and the fix

**All 3 false positives are the same category:** a *legitimate, well-known
site* claimed under the *wrong brand*:

- walmart.com claiming to be "amazon" → allowed
- target.com claiming to be "paypal" → allowed
- music.apple.com claiming to be "spotify" → allowed

Meanwhile, every *actually suspicious* pattern was blocked perfectly:
lookalike search engines (bing, yahoo), competitor stores (steam, gitlab,
hulu) — and every real URL passed.

**Diagnosis:** the prompt asks *"is this the REAL seller for a brand?"* but
the LLM tends to answer *"is this a legitimate, safe checkout page?"* Walmart
and Target are legitimate checkout pages — just not Amazon's or PayPal's.

**Fix (one-line prompt change):** make domain ownership the primary criterion,
e.g.:

> `is_real` must be `true` ONLY if the checkout domain is the brand's
> registered official domain (or a subdomain of it). A legitimate third-party
> retailer is NOT the brand's real seller — return `is_real: false` with
> verdict `"wrong_seller"` for that case.

Expected effect: the 3 FPs flip to blocked without touching the 9 TPs (all of
which are on official domains or subdomains). This is the benchmark's main
deliverable to the team: **domain-mismatch detection is the weak point, and
it's a prompt-level fix, not an architecture problem.**

## Failures (no verdict produced)

| Case | Cause | Detail |
|---|---|---|
| ebay.com/sl/list [paypal] | `NO_MAJORITY` | GenVM web module crashed fetching ebay (bot-blocking); validators could not agree |
| github.com/settings/billing [github] | leader idle | page redirects to a login wall |
| gitlab.com/users/sign_in [github] | `WEBPAGE_LOAD_FAILED` | page would not load for validators |

For a shopping agent this is the **safe** outcome: no verdict → no cache entry
→ block pay by default. But the transaction itself errors rather than caching
a "could not verify" verdict. *(Fixed in v0.4: the contract now catches the
fetch failure inside the consensus closure and returns an explicit, cacheable
`{"is_real": false, "verdict": "unverifiable"}` — see the final contract.)*

## Cost & latency (per validation)

- **Actual fee consumed:** **~0.000085 GEN** mean across 21 fresh-consensus
  transactions on the live contract (`fees.consumed` — `executionConsumed` +
  `storageFeeUsed` + `messageFeesConsumed`), range 0.000078–0.000162 GEN. That
  is roughly **12,000 validations per GEN**.
  0.000628 GEN is the budget *held* at submit; the unused remainder is refunded
  at finalization, so the deposit overstates the cost by ~7x.
  *Two corrections are recorded here. An early note said ~0.083 GEN — a 1000x
  error from reading the wei-denominated budget as 1e12-scaled instead of 1e18.
  A later note said ~0.0006 GEN, measured as the deployer's balance delta — that
  was the held deposit, not the consumed fee, because the balance was sampled
  before the refund settled. Read `fees.consumed`, never `fees.deposit`.*
- **Fee settlement lags finality by ~35 s.** A transaction reaching
  `FINISHED_WITH_RETURN` still reads `fees.consumed = 0` for roughly half a
  minute afterwards; measured 35.4 s on studio-dev (polled every 5 s from the
  instant of finality). Until then the deposit shows as held and the refund as
  pending — reading the fee at finality and calling it zero is wrong. The
  portal reports `settled: false` and keeps polling the *read* endpoint rather
  than printing a cost it does not have yet.
- **The vote map can be empty at the instant of finality too.** A transaction
  read the moment it finalizes sometimes comes back with `consensus_data.votes`
  empty while `leader_receipt` is already populated — the round is over, the
  record of it just is not complete yet. Building the jury from `votes` alone
  therefore renders a one-row table for a five-validator round. The portal
  builds it from `last_round.round_validators` (the round's actual roster,
  leader included) and reports `complete: false` until the votes arrive, so the
  table is whole throughout and only the vote column fills in late.
- **Latency:** highly variable on studio-dev. Execution is fast (leader ~1.5s,
  validator ~0.9s of actual work); end-to-end finalization has been observed
  anywhere from ~5s to ~135s depending on validator scheduling. Cache hits skip
  the LLM round, but still cost a transaction and still wait on consensus.

## Reproduce

```bash
# fresh venv with the Consensus v0.6 RC SDK
.venv-deploy/Scripts/pip install --pre "genlayer-py==0.19.0rc2"

set GENCHECK_PRIVATE_KEY=0x...   # funded burner key
.venv-deploy/Scripts/python scripts/benchmark.py
```

The script deploys a fresh contract, runs the labeled dataset through real
consensus, and writes per-case results to `benchmarks/benchmark_results.json`.

## Appendix: on-chain transaction hashes

All 21 transactions verified on-chain (via the studio-dev RPC) as addressed to
the benchmark contract with full consensus data. The explorer's contract page
may not list them all — open a tx directly by hash:
`https://explorer-studio-dev.genlayer.com/transaction/<hash>`

| Case | tx hash | Consensus |
|---|---|---|
| paypal.com/signin [paypal] | `0x314d5b8a48ea3ce459d3d52c6dfbe0c088981e6e6964a995957573ced3e32156` | MAJORITY_AGREE |
| apple.com/shop/bag [apple] | `0xdd90af9f946d2c2cd0d82d1c49299ebf1c13b51953056a19c6640f1a072e6921` | MAJORITY_AGREE |
| apple.com/shop/watch [apple] | `0x6d84007e40ade930165e34506075ebc3a198ba7ae7323234e37c2a68a2860711` | MAJORITY_AGREE |
| amazon.com/gp/cart [amazon] | `0xbe55aedb84494b721f1f148d5146bb217917cd8078cd4a4072d02a1df5e731ae` | MAJORITY_AGREE |
| microsoft.com/store [microsoft] | `0xe02b50148dfcf302970b32d72fca25a0b46906889d9d46177fe8d60f86116499` | MAJORITY_AGREE |
| netflix.com/YourAccount [netflix] | `0x4a497c409891845dd56ead1cefab6c7805a458da5d00400e4d065b69887c0e0a` | MAJORITY_AGREE |
| github.com/settings/billing [github] | `0xad52fa14ab134f091a940c7f5adb9a613da0fd10e704ccb2ac04cd5dce1f1297` | MAJORITY_AGREE (execution error) |
| store.google.com/us [google] | `0xc1e6b8494f3e8b4107ca920e72a00d6e840e06ff4466b0104eb348a1deaa09e1` | MAJORITY_AGREE |
| open.spotify.com [spotify] | `0xa5bf6773afe29c89cb0d19a267ff24272d090076492648b2cff7ab5b82a4113c` | MAJORITY_AGREE |
| bing.com/shop [apple] | `0xfeea713557c39d8f8414a2789ca721aadc6b5fb3e7964cf7a77ed9702efc5e8b` | MAJORITY_AGREE |
| steampowered.com/cart [apple] | `0x6c42d91959f2acd4ccd25accd920af8097e9eaf81084d37f870f07aae8e5933b` | MAJORITY_AGREE |
| ebay.com/sl/list [paypal] | `0x61e12902a726beb3af58d15f48aef98b16b658b9a12002e2bc7a6c77af7a6492` | NO_MAJORITY |
| walmart.com/checkout [amazon] | `0xbf521b2322ed4240253bc23f95d07cf8a9c695e086ed012243eac54686f20683` | MAJORITY_AGREE |
| mail.yahoo.com [microsoft] | `0x489a7590d7d9666e225984790f7876c31fa3eb7c9cac17c06683b86bcb64f333` | MAJORITY_AGREE |
| gitlab.com/users/sign_in [github] | `0x086038ff9c08e36278750ba49911158fb22eaaf143cf310f6fcf9fd72babd8ae` | MAJORITY_AGREE (execution error) |
| hulu.com [netflix] | `0x429971547c82e912b94014aeb8a015b0d8079d43fa069a416ad8a05546488617` | MAJORITY_AGREE |
| music.apple.com [spotify] (first run) | `0x2920cf892021a59a346895bea026d3be2f7240afc0470e6c9d96fe76790cea27` | TIMEOUT |
| target.com/cart [paypal] | `0x37408add76364baacc3676d58c5f7b6e80c714e2f85e742ac10d37bc61b3cfb9` | MAJORITY_AGREE |
| github.com/pricing [github] (retry) | `0x6f8f2170d6189d9d1919aa7d6f205efbee1b82719eec6cc4815294aa78afcc0b` | MAJORITY_AGREE |
| about.gitlab.com [github] (retry) | `0xaa6b270ac1d4f7c2305b2a57e722c4af56dc7b59dde37d757c1c629b97a3ed68` | MAJORITY_AGREE |
| music.apple.com [spotify] (retry) | `0x3e21f99743ac89855820f45c6f49973c3ac4a3621ed20132d96758215163a615` | MAJORITY_AGREE |

Run `scripts/verify_txs.py` to re-verify every hash against the RPC (target
contract, consensus result, execution outcome).

## Limitations

- Fake set uses *wrong-brand real sites* — the strongest domain-mismatch
  phishing signal. A second phase with hosted lookalike pages (e.g. an "Apple
  Secure Checkout" page on a non-Apple domain) would additionally test
  content-based detection (branding mimicry, fake trust badges).
- Single run per case; consensus is stochastic (LLM judgment + rotating
  validator sets). Repeated runs would give confidence intervals.
- 8 seeded brands only; unregistered brands fall back to the LLM's general
  knowledge (still exercised: music.apple.com was judged with Apple's official
  spotify.com fetch as reference).

---

# v2 — the domain-ownership fix

**Contract:** `0x12E17B838D81692Dd40ccc011C2538871E183559` · prompt
`v2-domain-ownership` · 9 Sept 2026

The v1 diagnosis said the 3 false positives were a prompt-level problem, so
v2 made **domain ownership the primary criterion** and added a
`wrong_seller` verdict: `is_real` is `true` only if the checkout domain is
the claimed brand's registered official domain (or a subdomain of it). A
legitimate third-party retailer is not the brand's real seller.

## Regression check (7 cases on a fresh contract)

| Case | v1 result | v2 result |
|---|---|---|
| walmart.com/checkout claimed "amazon" | ❌ allowed | ✅ **blocked** |
| target.com/cart claimed "paypal" | ❌ allowed | ✅ **blocked** |
| music.apple.com claimed "spotify" | ❌ allowed | ❌ **still allowed** |
| store.google.com [google] | ✅ allowed | ✅ allowed |
| open.spotify.com [spotify] | ✅ allowed | ✅ allowed |
| bing.com/shop claimed "apple" | ✅ blocked | ✅ blocked |
| apple.com/shop/bag [apple] | ✅ allowed | ⚠️ no verdict (apple 503) |

2 of 3 false positives flipped to blocked, with no false negatives on the
re-checked true positives.

## The remaining bug — proven from on-chain evidence

music.apple.com claimed as "spotify" still passed. Decoding the leader's
`eq_outputs` from the transaction's consensus data (base64 → JSON) showed
the LLM's actual reasoning: it validated the **page's own displayed brand
(Apple)** and concluded "this is Apple's legitimate site" — because the
prompt never named the brand the *customer* intended to buy from. The LLM
answered a different question than the one the benchmark was scoring.

That pinned the root cause: the prompt had no concept of a *claimed brand*
distinct from the page content.

# v3 — the claimed-brand prompt + fresh 21-case benchmark

**Contract:** `0xe366d9D7A94A7533a693eA0861b887232f1219A8` · prompt
`v3-claimed-brand` · 9 Sept 2026 · raw data `benchmarks/benchmark_v3_results.json`

## The fix

The prompt now leads with the claimed brand as a separate input:

> `CLAIMED BRAND: {brand}` — The brand the customer intends to buy from is
> "{brand}". You are NOT validating whatever brand the page itself displays.

…followed by an explicit domain-ownership anchor ("Does the checkout URL's
domain belong to "{brand}"?"), four ordered decision rules (`real` /
`wrong_seller` / `scam` / `unsure`, including a hosting-pattern rule: a
lookalike on github.io, blogspot, netlify, vercel, or an unrelated domain is
`scam`), and secondary signals that can never override the domain rule.
Unregistered brands fall back to the LLM's general knowledge of that brand's
official domain.

## Dataset — live phishing pages, not synthetic wrong-brand sites

Fake candidates came from the **OpenPhish community feed**
(openphish.com/feed.txt) filtered to fetchable pages, so every fake case is
a real, currently-live phishing/clone page:

- **8 phishing** — amazon & netflix storefront clones on github.io, an
  exodus-wallet phish on vercel, a "fedx" typosquat on netlify, a "ledgre"
  typosquat on pages.dev. Three target *unregistered* brands (exodus, fedex,
  ledger) — exercising the general-knowledge fallback.
- **3 wrong_seller** — the v1/v2 false positives: walmart→"amazon",
  target→"paypal", music.apple→"spotify".
- **10 real** — official pages for 8 seeded brands (incl. subdomains
  store.google.com, open.spotify.com) plus newly-registered walmart.com and
  target.com.

## Results: 21/21 — 100%

| Category | Correct | Verdicts |
|---|---|---|
| Phishing (live lookalikes) | 8/8 blocked | 100% |
| Wrong seller (v1's failure class) | 3/3 blocked | 100% |
| Real (incl. subdomains, unregistered-brand fallback) | 10/10 allowed | 100% |
| **Total** | **21/21** | **100%** |

> **Caveat added alongside v5.** This run stores only `is_real`. A block earned
> by detection and a block earned by a page failing to load are the same value in
> `benchmark_v3_results.json`, so 100% here is an upper bound on detection, not a
> measurement of it. When v5 measured the two separately, 14 of its 23 blocks
> were detections and 7 were unreachable pages. Three of the eight phishing cases
> below — the `*.github.io` Amazon clones — now return 404 from GitHub Pages, so
> today they would pass by failing closed rather than by being caught.

No-verdict cases (safe: block by default, no cache entry):

| Case | Cause |
|---|---|
| ledgre-wallet-io.pages.dev [ledger] | page 403s to validators → `FINISHED_WITH_ERROR` |
| apple.com/shop/bag [apple] | apple 503s (all day, locally too) → substituted `apple.com/iphone/`, which passed |
| music.apple.com [spotify] (first attempt) | consensus `TIMEOUT` (leader returned, validators didn't settle) → retry passed, blocked |

**Every verdict in all three categories was correct, including all three
v1/v2 false positives.** Median latency ~67s per validation
(51–95s; the apple.com/iphone/ substitute took 372s through a slow fetch).

Explorer: `https://explorer-studio-dev.genlayer.com/address/0xe366d9D7A94A7533a693eA0861b887232f1219A8`
— per-tx hashes in `benchmarks/benchmark_v3_results.json` (the explorer's contract
page may not list every tx; open by hash).

## Reproduce

```bash
set GENCHECK_PRIVATE_KEY=0x...
.venv-deploy/Scripts/python scripts/benchmark_v3.py     # 21-case run
.venv-deploy/Scripts/python scripts/run_one_v3.py <url> <brand> <category> <0|1> <note>
```

---

# CSV benchmark — 412-row labeled dataset

**Contracts:** first pass `0xCe9131cbC10324541B844e197EB9bD53D683DBD3`,
retry pass `0x94166f495dB604eadb65d7DdB268d3F7414263b5` · prompt
`v3-claimed-brand` · 9 Sept 2026 · raw data `benchmarks/benchmark_csv_results.json`

## Dataset reality check

The provided `benchmarks/gencheck_benchmark.csv` has 412 rows (312 fake from phishing
databases, 100 real). **300 of the 312 fake URLs are dead** (phishing pages
are taken down fast — mostly ConnectionError/404). Only 85 URLs still serve
content: 73 real, 12 fake. The benchmark sample is therefore **every live
fake (12)** plus a balanced 16 reals (8 brand checkout pages — ebay excluded
for the known GenVM web-module crash — and 8 recognizable top sites).

## Results (first pass + retry of every failure on a fresh contract)

| Metric | Value |
|---|---|
| Cases attempted | 28 (+6 retries) |
| Verdicts produced | 25/28 (89%) |
| **Accuracy on verdicts** | **24/25 = 96.0%** |
| Phishing block rate | **11/11 = 100%** — no phishing URL was ever allowed |
| Real recall | 13/14 = 92.9% |
| False positives (phishing allowed) | **0** |
| False negatives (real blocked) | 1 (office.com) |
| No verdict (safe block by default) | 3 |

> **Caveat added alongside v5.** As with v3, this run stores only `is_real`, and
> the phishing row above counts a page that would not load the same as a page
> that was caught. The line beneath the table already says "blocked or
> safe-blocked" — those are different results, and only one is detection. 11/11
> is therefore an upper bound. The v5 run is the first in this document that can
> tell them apart.

All 12 live phishing URLs were blocked or safe-blocked — including the
`unknown`-brand rows where the prompt falls back to judging the page on its
merits. Brand checkout pages for unregistered brands (shopify, nike, walmart,
target, netflix, sephora, costco) exercised the general-knowledge fallback.

## The one false negative: office.com — a labeling artifact

office.com [brand "office"] was blocked twice, consistently. Decoding the
leader's on-chain `eq_outputs` shows the LLM's reasoning: *"office.com is
not the official seller domain for Microsoft Office... those belong to
microsoft.com... the correct verdict is `wrong_seller`."* The CSV labels the
brand as the generic string "office", and the v3 prompt correctly validates
the **claimed brand** literally — "office" is not a brand that owns
office.com. With a real brand name ("microsoft") the page would pass
(www.microsoft.com/store passed in v1). mozilla.com, blocked once, passed on
retry — consensus variance on a redirect domain, not a deterministic flaw.

## No-verdict cases (safe block, no cache entry)

| Case | Cause | Retry |
|---|---|---|
| trackyourpackageusps.blogspot.com.br | fetch failed on-chain | ✅ blocked on retry |
| sdvrg.blogspot.hr | fetch fails on-chain consistently | still no verdict |
| sephora.com/checkout | sephora bot-blocks validators | still no verdict |
| costco.com/checkout | costco bot-blocks validators | still no verdict |

Validator-side fetch blocking (sephora, costco) is the remaining infra gap:
the page is legitimate but unverifiable, so GenCheck conservatively blocks.

## Reproduce

```bash
set GENCHECK_PRIVATE_KEY=0x...
.venv-deploy/Scripts/python scripts/check_csv.py      # fetchability check → benchmarks/csv_live_check.json
.venv-deploy/Scripts/python scripts/benchmark_csv.py  # 28-case run on a fresh contract
.venv-deploy/Scripts/python scripts/retry_csv.py      # retry failures/no-verdicts on a fresh contract
```
