<img src="portal/static/favicon.svg" width="76" height="76" alt="GenCheck">

# GenCheck

**A shopping agent's trust layer for checkout URLs — built on GenLayer.**

Before money moves, GenCheck asks GenLayer validators to open a checkout URL and the real brand's official site and answer one question: **is this the real seller or a lookalike scam?**

- ✅ Real → allow pay
- ❌ Fake → block pay
- ⚠️ Unsure → block pay (conservative default)

> 📊 **Accuracy benchmark (v5, the live contract):** 50 labeled URLs — live
> OpenPhish phishing pages, wrong-seller sites, and legitimate checkouts —
> through real validator consensus: **46/49 verdicts correct (93.9%)**,
> **0 false positives**, **3 false negatives**. The three are named, not buried:
> sephora.com and costco.com bot-block the validators (fail-closed
> `unverifiable`), and office.com was a genuine misjudgement. Every one of the
> 23 lookalikes was blocked; not one was cleared for payment. See
> **[BENCHMARK.md](BENCHMARK.md)** for this run and the v1 → v3 prompt-fix arc
> (v1: 82.4% with 3 wrong-brand false positives, v3: 21/21).

**Live contract (studio-dev):** `0xD914Bf44b78df2CC3FeFf343769800E11690288B` —
[View on explorer](https://explorer-studio-dev.genlayer.com/address/0xD914Bf44b78df2CC3FeFf343769800E11690288B)

---

## How It Works

```
Shopping Agent                GenLayer Validators               Web
     │                               │                         │
     │  validate_checkout(url,brand) │                         │
     ├──────────────────────────────▶│                         │
     │                               ├── render(checkout_url) ─▶
     │                               │◀── page content ────────┤
     │                               ├── render(official_url) ─▶
     │                               │◀── page content ────────┤
     │                               │                         │
     │                               ├── LLM: "real or scam?"  │
     │                               │   (leader proposes)     │
     │                               ├── validators compare    │
     │                               │   verdicts via          │
     │                               │   prompt_comparative    │
     │                               │                         │
     │◀────── {is_real, verdict} ─────┤
     │                               │
     ├── is_real=true  → PAY ✅      │
     └── is_real=false → BLOCK ❌    │
```

1. **Cache check** — if the domain was validated before, the contract returns its stored verdict without a second LLM round (the call is still a transaction; it just resolves fast).
2. **Fetch both pages** — validators use `gl.nondet.web.render()` to open the checkout URL and the brand's official site.
3. **LLM judgment** — a security-expert prompt evaluates domain similarity (typosquatting, homoglyphs, subdomain tricks), page design, trust badges, and payment methods.
4. **Consensus** — `gl.eq_principle.prompt_comparative` requires validators to agree on the `is_real` verdict, not on exact wording.
5. **Cache and return** — the verdict is stored in a `TreeMap` so repeat checks skip the LLM round.

## Shopping Agent Demo

`demo/shopping_agent.py` is the end-to-end product story: a price-sensitive
shopping agent whose every payment is security-gated by GenCheck. Given a
purchase request, it sorts offers cheapest-first — and the cheap offer in the
demo scenario is a real Amazon-checkout lookalike on github.io. The agent
submits each checkout URL to validator consensus before paying:

```bash
set GENCHECK_PRIVATE_KEY=0x...
.venv-deploy/Scripts/python demo/shopping_agent.py
```

- lookalike offer → validators return `scam` → **BLOCK**
- official store → validators return `real` → **PAY**
- no verdict (fetch failure) → **BLOCK** (conservative default)

The full transcript of a live run is in
[`demo/demo_transcript.md`](demo/demo_transcript.md). Re-running the demo
hits the domain cache for already-validated domains — the LLM round is
skipped and the call finalizes fast, but each one is still a real write
costing ~0.00008 GEN. The cost model is: full consensus once per domain,
cache hits thereafter.

## Equivalence Strategy

GenCheck uses **`prompt_comparative`** rather than `strict_eq` because LLM outputs naturally vary in wording between validators. The comparison criterion:

> "The is_real verdict must match. If one validator says the site is real and another says it is a scam, they do not match."

This means validators must **agree on the verdict**, while tolerating differences in confidence scores, reasons, and phrasing. If validators disagree on `is_real`, the transaction fails consensus and goes through GenLayer's appeal process.

## Project Structure

```
gencheck/
├── contracts/
│   └── shopping_validator.py   ← Main GenCheck Intelligent Contract
├── gencheck/                   ← importable client package
│   ├── client.py               ← GenCheck class + fail-closed decide()
│   └── mcp_server.py           ← MCP server (3 tools) for AI agents
├── demo/
│   └── shopping_agent.py       ← End-to-end agent demo (+ demo_transcript.md)
├── portal/                     ← public verification portal (FastAPI + web)
│   ├── app.py                  ← /api/submit, /api/status, /api/examples
│   ├── static/index.html       ← the single-page frontend
│   ├── static/skill.md         ← the agent skill, served at /skill.md
│   └── DEPLOY.md               ← hosting guide (Vercel / HF Spaces / VPS)
├── api/index.py                ← Vercel serverless entry (wraps portal.app)
├── SKILL.md                    ← agent-facing skill (what/when/the one rule)
├── scripts/                    ← deploy, benchmark, verification tooling
├── tests/
│   ├── direct/
│   │   └── test_shopping_validator.py   ← Fast mocked tests (pytest)
│   └── integration/
│       └── test_consensus.py            ← Consensus tests (gltest)
├── BENCHMARK.md
├── README.md
└── requirements.txt
```

## Quick Start

### Prerequisites

- Python 3.10+
- GenLayer CLI: `npm install -g genlayer`
- Contract linting: `pip install genvm-linter`
- Direct tests: `pip install genlayer-test pytest`
- Integration tests: `pip install "genlayer-test[sim]"`

### Run Quality Gates

```bash
# 1. Lint the contract
#    (PYTHONUTF8=1 avoids a Windows console encoding crash in genvm-lint;
#     GENVM_VERSION pins the runner bundle so the linter doesn't pick the
#     genvm-manager archive, which lacks the v0.3.0-rc7 runner layout)
PYTHONUTF8=1 GENVM_VERSION=v0.3.0-rc7 genvm-lint check contracts/shopping_validator.py --json

# 2. Direct tests (mocked web + LLM, fast)
#    NOTE: these require the runner from the contract header
#    (py-genlayer:5jycge...) in the local genvm cache. That runner ships with
#    the Studio bundle and is not in the published genvm release tarballs, so
#    on a fresh machine lint validation reports E101 and direct tests cannot
#    resolve the SDK. The contract's behavior is instead verified end-to-end
#    on studio-dev itself (gen_call simulations + live consensus transactions).
PYTHONUTF8=1 GENVM_VERSION=v0.3.0-rc7 python -m pytest tests/direct/ -v

# 3. Integration tests (real consensus, requires node)
gltest tests/integration/ -v -s --network localnet
```

### Windows Environment Notes

Three issues were hit and resolved while setting this up on Windows 11:

1. **`genlayer 0.0.1` PyPI stub must be uninstalled.** It's an empty
   placeholder package that shadows the real GenVM SDK. `gltest`'s direct
   loader imports `genlayer` before adding the SDK to `sys.path`, so the stub
   gets cached in `sys.modules` and the contract's `import genlayer.gl` fails
   with `No module named 'genlayer.gl'`. Fix: `pip uninstall -y genlayer`.

2. **gltest 0.29.2 Windows bug** — `_inject_message_to_fd0` unlinks a temp
   file while the dup2'd fd 0 still holds it open (legal on POSIX, raises
   `PermissionError` on Windows). Worked around in
   `tests/direct/conftest.py` without touching site-packages.

3. **`genvm-lint` console encoding** — progress glyphs (`✓`) crash the
   Windows console codepage. `PYTHONUTF8=1` fixes it.

### Deployed on Studio Dev (Agent Tank network)

- **Final contract (v5 — admin-gated registry, brand-scoped cache)**: `0xD914Bf44b78df2CC3FeFf343769800E11690288B`
- **Network**: studio-dev preview, chain ID 61997
- **RPC**: `https://studio-dev.genlayer.com/api`
- **Explorer**: `https://explorer-studio-dev.genlayer.com/address/0xD914Bf44b78df2CC3FeFf343769800E11690288B`

Earlier contracts are kept as the benchmark evidence trail (see
[BENCHMARK.md](BENCHMARK.md)): v1 baseline `0x04a9cCB5...0917d`, v2 fix-check
`0x12E17B83...8559`, v3 benchmark `0xe366d9D7...219A8`, CSV benchmark
`0xCe9131cb...DBD3` (+ retry contract `0x94166f49...263b5`), demo-run
contract `0xC516b95d...BEb7`, v4 unverifiable-verdict
`0x61153C8d907eBa4Ea96d5955c7b05F67F2967e2D` — v4 is the one that exposed the
three unauthenticated paths v5 closes, and since contracts are immutable that
deployment is still vulnerable; nothing should point at it. The original manual
deploy `0x59c12366...D6b5F3` predates the prompt fixes and still runs the v1
prompt.

### Interacting without the CLI (genlayer-py 0.19 RC)

studio-dev runs the Consensus v0.6 release-candidate stack, which needs the
matching RC SDK (`genlayer-py 0.19.0rc2` — its `studio_devnet` chain definition
binds chain ID 61997, the RPC, and the consensus deployment together):

```bash
python -m venv .venv-deploy
.venv-deploy/Scripts/pip install --pre "genlayer-py==0.19.0rc2"

# reads (unsigned)
.venv-deploy/Scripts/python scripts/interact.py
.venv-deploy/Scripts/python scripts/interact.py --check apple.com
.venv-deploy/Scripts/python scripts/interact.py --brand netflix

# writes (needs a funded key; fees estimated per call)
set GENCHECK_PRIVATE_KEY=0x...
.venv-deploy/Scripts/python scripts/validate_checkout.py "https://apple.com/shop/bag" "apple"
```

Every deploy and write on studio-dev carries an explicit `FeesDistribution`
and fee value (the deployment is not gasless). `scripts/validate_checkout.py`
estimates fees via write simulation, submits, waits for finalization, and
verifies both consensus status (`MAJORITY_AGREE`) and execution result
(`FINISHED_WITH_RETURN`) before reading back the cached verdict.

## Try It: Verification Portal

**Anyone can test GenCheck in a browser, no wallet or key needed.** The portal
(`portal/`) is a single-page frontend + FastAPI backend wrapping the same
`gencheck` client and the same live contract — no separate trust path.

**Every check is a real on-chain transaction.** Clicking an example chip or
pasting your own URL submits its own `validate_checkout` transaction; the hash
appears in ~2s with an explorer link, and the verdict follows when validators
finalize. Nothing is simulated and nothing is pre-baked — the page shows the
real jury (validator addresses, votes, and the LLM each one ran).

- Real transaction per check, ~0.00008 GEN each (measured) — see
  [`portal/DEPLOY.md`](portal/DEPLOY.md) for the cost guards
- Pre-warmed examples: an Amazon-checkout lookalike on github.io
  (**BLOCKED — wrong_seller**), real Amazon / Best Buy / Walmart / Target carts
  (**CLEARED**), and sephora.com (**UNVERIFIABLE — fails closed**). They are
  cached on-chain, so the contract answers them fast — but each still produces
  a transaction with its own hash
- Serverless-ready: async submit/poll endpoints (`/api/submit`, `/api/status`)
  keep every request under ~5s, so it deploys to Vercel's free tier

```bash
.venv-deploy/Scripts/pip install fastapi "uvicorn[standard]"
.venv-deploy/Scripts/python -m uvicorn portal.app:app --port 8000
# open http://127.0.0.1:8000
```

Deploying to **Vercel** (repo already Vercel-shaped: `api/index.py` +
`vercel.json`): push to GitHub → import at vercel.com/new → set
`GENCHECK_PRIVATE_KEY` as a secret. Full guide incl. Docker/VPS options in
[`portal/DEPLOY.md`](portal/DEPLOY.md). The key is always a host env var /
secret — never in files.

## The Agent Skill

**[`SKILL.md`](SKILL.md) is the agent-facing surface** — one markdown file an agent
reads to know what GenCheck is, when to call it, the one rule it must obey (*pay only
on `is_real: true`; every other outcome is BLOCK*), and how to set itself up: fund a
studio-dev account from the faucet, `pip install`, then call the CLI or the MCP server.
It also documents the three MCP tools, cost/latency, and the live contract address.

The portal serves it at a stable URL, so pointing an agent at GenCheck is one line:

```bash
curl -s https://gencheck-live.vercel.app/skill.md
```

It is also installable as a Claude Code skill (`.claude/skills/gencheck/SKILL.md`)
and ships as the repo-root `SKILL.md`. All three copies are byte-identical.

## Integrating an AI Agent

GenCheck's integration model is the **active validation gate**: the agent's
payment code fails closed — it signs nothing unless validator consensus
explicitly cleared the domain.

**Who pays.** Every validation is a real transaction, so it runs on the agent's
**own** funded studio-dev account. GenCheck operates no endpoint that spends GEN
on your behalf — the only way to build one is to ask you for your private key,
which is the one thing a trust tool should never do. (The hosted portal is a
browser demo that signs with its own account; see the note under it below.)

### Fund an account — GEN is free on studio-dev

Create any EVM wallet, then at **https://studio-next.genlayer.com** connect it
and click **Fund**. One claim covers roughly 12,000 validations (~0.00008 GEN
each). Keep the key in `GENCHECK_PRIVATE_KEY`, never in a file you commit.

### Install

```bash
pip install git+https://github.com/iamdudeGH/gencheck    # Python 3.12+
```

That installs two entry points: `gencheck` (the CLI) and `gencheck-mcp` (the MCP
server). The `genlayer-py` pin is an exact pre-release, which resolves without
`--pre` — a range would silently pick a stable release that points consensus at
the wrong chain.

### Claude Code: install the plugin instead

If your agent is Claude Code, the plugin bundles the skill and the MCP server and
asks for your key **once** — kept in your OS keychain, not in a file you might commit:

```bash
/plugin marketplace add iamdudeGH/gencheck
/plugin install gencheck@gencheck
```

The key prompt is skippable: leave it blank and you keep the free read-only checks.
The plugin still needs the `pip install` above — the MCP server runs from that
install, so do that first or the tools will not appear.

**What happens to your key.** It is passed to the MCP server as
`GENCHECK_PRIVATE_KEY`, used to sign validation transactions on your own account,
and nothing else. GenCheck has no backend that receives it: every check goes
straight from your machine to the GenLayer RPC. That is the whole reason the
integration is a local package and not a hosted endpoint — see *Who pays* above.

### Option 1: CLI — works for any agent that can run a command

The exit code *is* the gate, so a shell chain fails closed with no glue at all:

```bash
gencheck check "$CHECKOUT_URL" "$BRAND" && pay || refuse
```

| exit | meaning |
|---|---|
| `0` | **PAY** — consensus returned `is_real: true` |
| `1` | **BLOCK** — a verdict came back, and it was not `is_real: true` |
| `2` | **ERROR** — no verdict obtained (no key, network, unverifiable) |

Both non-zero codes mean do not pay, so `&&` is safe without distinguishing
them. stdout is a single JSON object for callers that would rather parse than
check exit codes. The free reads need no key at all:
`gencheck cache <domain>` and `gencheck domain <brand>`.

### Option 2: MCP server

Any MCP-capable agent (Claude Code, Claude Desktop, Cursor, custom agent
frameworks) can add GenCheck as a tool. The server
([`gencheck/mcp_server.py`](gencheck/mcp_server.py)) exposes three tools:

| Tool | Cost | What it does |
|---|---|---|
| `gencheck_check_domain(domain)` | free, instant | cached consensus verdict (a read — no transaction) |
| `gencheck_validate(url, brand)` | ~0.00008 GEN per call | full validator consensus, as a real transaction |
| `gencheck_official_domain(brand)` | free, instant | brand registry lookup |

```bash
# the key goes in the server's env — MCP stdio clients start servers with a
# minimal default environment, so a shell export will not reach it
claude mcp add gencheck --env GENCHECK_PRIVATE_KEY=0x... -- gencheck-mcp

# verify end-to-end (spawns the server over stdio and calls every tool)
.venv-deploy/Scripts/python scripts/test_mcp.py
```

The agent's policy then gates payments on the tool result: proceed only when
`decision` is `PAY`. Verified live: `www.amazon.com` → PAY,
`sephora.com` → BLOCK (unverifiable), unvalidated domains → BLOCK.

### Option 3: Python client

```python
import os
from gencheck import GenCheck, decide

gc = GenCheck(private_key=os.environ["GENCHECK_PRIVATE_KEY"])  # writes
gc = GenCheck()                                                # reads only

cached = gc.check_cache("www.amazon.com")   # instant + free, None if unvalidated
verdict = gc.validate(checkout_url, brand)  # full consensus (~6-10s on studio-dev now)
action, why = decide(verdict)               # ("PAY"|"BLOCK", reason) — fails closed
```

### Not an integration: the hosted portal

`https://gencheck-live.vercel.app` runs the same gate in a browser and shows the
full jury — every validator's address, vote and model — per transaction. It is
there to watch the gate work or to check a domain by hand. **Do not build an
agent against it:** it signs with the portal's own account, so you get no cost
control, no guarantee it stays funded, and no on-chain proof that *you* asked.
The portal also serves [`SKILL.md`](SKILL.md) at `GET /skill.md`.

### The decision table (fail-closed)

| GenCheck result | Agent action |
|---|---|
| `real` (`is_real: true`) | ✅ **PAY** — the only path where money moves |
| `scam` / `wrong_seller` / `unsure` | ❌ BLOCK |
| `unverifiable` (validators can't fetch the page) | ❌ BLOCK |
| no verdict (consensus timeout / tx error) | ❌ BLOCK |

Custody stays with the agent — GenCheck is a trust oracle, not a wallet.
The gate is a hard rule inside the agent: the signing step is unreachable
without a consensus-backed `real`, so an agent built this way cannot be
tricked into paying a lookalike checkout. A scammer can't win by making the
check *fail* (fail-closed default); they'd need multiple independent
validators to actively judge their page the genuine brand's official domain.

Cost model: ~0.00008 GEN per validation transaction, measured across 21 real
consensus runs, so ~12,000 per GEN. (The 0.000628 GEN shown as a deposit is
held at submit and mostly refunded at finalization — the consumed figure is
the real cost.) The contract caches each domain's verdict on-chain, so a
merchant judged once is answered from cache on later checks — that skips the
LLM round and the wait, but every `gencheck_validate` call is still a real
transaction with a hash. Agents that only need an answer (not proof) can use
the free `gencheck_check_domain` read instead.

**Roadmap (not built):** a chain-enforced escrow mode — agent deposits into a
contract that releases funds only on `is_real: true` — would make the gate
unbypassable even for a compromised agent. Deliberately out of scope for now.

## Contract API

| Method | Type | Description |
|---|---|---|
| `validate_checkout(checkout_url, brand)` | write | Validate a checkout URL against the brand's official site; caches the verdict |
| `add_official_domain(brand, domain)` | write | Register a new official brand domain in the persisted registry |
| `is_site_validated(domain)` | view | `true` if the domain was validated and deemed real |
| `get_cached_result(domain)` | view | Full cached verdict for a domain (raises `UserError` if unvalidated) |
| `get_official_domain(brand)` | view | Look up the registered official domain for a brand |

### Verdict Format

```json
{
  "is_real": true,
  "confidence": 99,
  "reasons": ["domain matches official registry", "checkout flow matches brand design"],
  "evidence": ["https://apple.com"],
  "verdict": "real"
}
```

`confidence` is an integer percent (0-100) — the runner's calldata encoder
cannot serialize floats, so the contract normalizes the LLM's `0.99` to `99`
defensively (missing/non-numeric becomes 0). `verdict` ∈ `real` | `scam` |
`wrong_seller` | `unsure` | `unverifiable`:

- `wrong_seller` — the page is a legitimate, well-known site but **not the
  claimed brand's** seller (e.g. walmart.com claimed as "amazon"); the v2
  prompt makes domain ownership the primary criterion so this case is
  blocked rather than allowed.
- `unverifiable` — validators could not fetch the checkout page (bot-blocking
  or offline). The contract catches the fetch failure inside the consensus
  closure and returns an explicit block verdict instead of erroring, so the
  block is cacheable and retries are free.

The shopping agent should treat everything other than `real` — `scam`,
`wrong_seller`, `unsure`, **and** `unverifiable` — as **block pay**.

## Brand Registry

The registry is a persisted `TreeMap[str, str]` contract field (not a module
global — GenVM only persists declared storage fields), seeded at deploy time
with well-known brands (apple, amazon, paypal, microsoft, google, netflix,
spotify, github). `add_official_domain` extends it on-chain. If a brand isn't
registered, validation still runs — the LLM compares the checkout page
against its general knowledge of the brand, and the result flags lower
confidence.

## Safety Design Notes

- **Conservative default**: unsure ≠ allow. The agent-side integration should block payment on anything other than a confident `real`.
- **Caching is domain-scoped**: a verdict for `apple.com` never leaks to `apple.com.evil.io` — domains are exact-match keys in a `TreeMap`.
- **Pinned dependency**: `py-genlayer` is hash-pinned in the contract header — no `:latest`.
- **Deterministic inputs before the non-det block**: the URL, brand, and prompt are built before entering `gl.nondet`, following GenLayer best practice.

## Agent Tank Hackathon

Built for the [GenLayer Agent Tank Hackathon](https://portal.genlayer.foundation/agent-tank)
— **Agentic Commerce Infrastructure** track (payments, escrow, identity and
insurance for agents trading with agents).

- Build window: 3–17 September 2026
- Winners announced: 25 September 2026
