# Deploying the GenCheck verification portal

The portal is a single FastAPI app (`portal/app.py`) + one static page
(`portal/static/index.html`). It talks to the live studio-dev contract through
the same `gencheck` client package the demo agent and MCP server use — no new
trust path, just a browser interface on top.

**Every check submits a real `validate_checkout` transaction.** There is no
cache short-circuit: example chips and pasted URLs both produce an on-chain
transaction whose hash the visitor can open on the explorer. The contract may
answer from its own domain cache (so the verdict returns fast), but the
transaction, its hash, and its validator votes are real either way.

Two request shapes are supported:

- **`/api/check`** — blocking, waits for consensus and returns the verdict in
  one response. Use for long-lived servers (Docker/VPS/Render).
- **`/api/submit` + `/api/status`** — async: submit returns a tx hash in ~2s,
  the frontend polls every 3s; status returns the real chain state plus, on
  finalization, per-validator votes and models. Use for serverless hosts
  (Vercel) that kill long-running requests. The frontend uses this automatically.

## Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `GENCHECK_CONTRACT` | no | Contract address override (defaults to `final_contract.json`) |
| `GENCHECK_PRIVATE_KEY` | **yes** | Funded key that signs the validation transactions. **Every check is a real on-chain transaction, so without this key the portal cannot answer at all** — it returns a "not configured" response rather than a fake verdict. |

**Never put the private key in a file, commit, or image.** Always set it as a
host env var / secret.

## Cost guards baked in

Every check — including the pre-warmed example chips — submits its own
`validate_checkout` transaction, so there is no cache shortcut and no free
path. What that costs, measured on studio-dev:

- **~0.00008 GEN per transaction.** Measured across 21 real consensus runs:
  0.000628 GEN is held at submit, only ~0.00008 GEN is actually consumed, and
  the remainder is refunded at finalization. That is roughly 12,000
  transactions per GEN — cost is not the binding constraint, the rate limits
  below are.
- Rate limit: 30 transactions per IP per rolling hour.
- Global cap: 400 transactions per rolling hour (~0.04 GEN/hour worst case),
  which bounds the worst-case drain of the demo wallet regardless of traffic.
- No key configured → the portal returns a clear "not configured" response. It
  never invents a verdict.

## Option A — Vercel (recommended, free Hobby tier)

The repo is already Vercel-shaped: `api/index.py` (serverless function
wrapping the whole FastAPI app), `vercel.json` (routes + 60s max duration),
`.vercelignore` (small bundle), and a runtime-only `requirements.txt`.

1. Push this repo to GitHub.
2. [vercel.com/new](https://vercel.com/new) → import the repo (framework
   preset: Other; no build command needed).
3. Environment Variables → add `GENCHECK_PRIVATE_KEY` = your burner key
   (mark as **Secret**, Production + Preview).
4. Deploy. The portal is live at `https://<project>.vercel.app`.

Notes:

- Each serverless invocation is short by design (submit ~2-5s, poll ~0.5s) —
  well inside Vercel's limits even on the free tier.
- First request after idle pays a cold start (~2-5s while the Python runtime
  imports) — harmless for a demo.
- Update the contract by deploying fresh (`scripts/deploy_final.py`), updating
  `final_contract.json`, and setting `GENCHECK_CONTRACT` in Vercel — or just
  redeploy with the new JSON committed.

## Option B — Hugging Face Spaces (free, Docker)

1. Create a Space → **Docker** → blank template (port 7860).
2. Settings → Secrets → `GENCHECK_PRIVATE_KEY`.
3. Push `Dockerfile`, `requirements.txt`, `gencheck/`, `contracts/`,
   `final_contract.json`, `benchmark_fees.json`, `portal/`. Change the
   Dockerfile port to 7860 (`EXPOSE`/`CMD`).

## Option C — any VPS / Render (Docker)

```bash
docker build -t gencheck-portal .
docker run -d --restart unless-stopped -p 8000:8000 \
  -e GENCHECK_PRIVATE_KEY=0x... \
  gencheck-portal
```

(Render: Web Service → Docker → add `GENCHECK_PRIVATE_KEY` env var. Free tier
sleeps after inactivity — fine for a demo.)

## Local test

```powershell
.venv-deploy\Scripts\pip install fastapi "uvicorn[standard]"
.venv-deploy\Scripts\python -m uvicorn portal.app:app --port 8000
# open http://127.0.0.1:8000
```

## Ops notes

- Verdicts for a domain are cached **on-chain forever** (immutable contract).
  A misjudged domain cannot be re-judged on the same contract — if that
  becomes a problem, deploy a fresh contract with `scripts/deploy_final.py`
  and point `GENCHECK_CONTRACT` at it.
- Rate-limit state is in-process memory — per serverless instance on Vercel,
  which is fine for a demo (the real cost guard is the wallet balance).
- Pre-warmed domains on the v5 contract, read back from the chain rather than
  copied from an earlier contract's list:

  | domain | cached brand | cached verdict |
  |---|---|---|
  | `www.amazon.com` | amazon | `is_real` true — cleared |
  | `walmart.com` | walmart | `is_real` true — cleared |
  | `target.com` | target | `is_real` true — cleared |
  | `www.walmart.com` | **amazon** | `is_real` false — blocked (wrong_seller) |
  | `www.target.com` | **paypal** | `is_real` false — blocked (wrong_seller) |

  Note what that table means for the demo chips. The cache is keyed on
  `(domain, brand)` as of v5, so `www.walmart.com/cart [walmart]` does **not**
  hit the entry stored under brand `amazon` — it runs a fresh consensus round.
  That is the v5 fix working, not a bug, but it costs ~60s and needs a key.
  The two rows worth relying on for an instant, key-free demo are
  `www.amazon.com` and `walmart.com`/`target.com` (apex).

  Everything else in `EXAMPLES` — the github.io Amazon clone, Best Buy, and
  Sephora — is **not** pre-warmed and will submit a real transaction.
  `unverifiable` results are deliberately never cached, so Sephora can never
  become warm; it will always cost a round.

  To warm a domain, run the demo or a single validation once with a funded key
  and the result persists. Phishing URLs rot, so the clone URL in `EXAMPLES`
  needs re-checking periodically; a replacement should be taken from
  <https://openphish.com/feed.txt>.
