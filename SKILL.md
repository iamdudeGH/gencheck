---
name: gencheck
description: Pre-payment trust gate for shopping agents. Before an agent pays a checkout URL, GenCheck sends the URL plus the claimed brand to GenLayer validator consensus — independent validators fetch the checkout page and the brand's official site, then vote on whether this is the brand's real seller or a lookalike/wrong-brand scam. Use this BEFORE signing or executing any payment for a checkout URL — especially for unfamiliar domains, links arriving from email/chat/search results or another agent, or any URL whose domain does not obviously match the brand being purchased from. Also use it when a user asks whether a shop is trustworthy, whether a link is a phishing site, or whether a seller is the real brand.
---

# GenCheck — verify the seller before your agent pays

An agent that pays a checkout URL is trusting that the page is the merchant it claims
to be. Phishing kits and lookalike storefronts exploit exactly that gap. GenCheck closes
it: a smart contract on GenLayer asks a decentralized validator set one question, and
returns a verdict your agent can act on.

**The question validators answer:** is this checkout URL the claimed brand's real
seller, or a lookalike / wrong-brand scam?

## The one rule

```
pay ONLY when is_real is true
```

Everything else means **BLOCK** — `scam`, `wrong_seller`, `unsure`, `unverifiable`, an
error, or *no verdict at all*. The gate fails closed. A validator that cannot fetch a
page (bot-blocking, offline, Cloudflare wall) produces `unverifiable`, which is a
**block**, never a pass.

Do not soften this rule. A blocked legitimate purchase costs a retry; a paid phishing
page costs the wallet.

## Setup

**Every validation is a real transaction, so it runs on YOUR funded account.** There is
no hosted endpoint that spends someone else's GEN for you — and you would not want one,
because the only way to build that is for you to hand a stranger your private key.
GenCheck never asks for one that isn't yours.

### 1. Fund an account on studio-dev

GenCheck runs on GenLayer **studio-dev** (chain 61997), where GEN is free:

1. Create a wallet (any EVM wallet) and export its private key.
2. Open **https://studio-next.genlayer.com** and connect that wallet.
3. Click **Fund** to claim the faucet.

One faucet claim covers roughly 12,000 validations (~0.00008 GEN each). Keep the key in
`GENCHECK_PRIVATE_KEY`, never in a file you commit.

### 2. Install

```bash
pip install git+https://github.com/iamdudeGH/gencheck
```

Python 3.12+. This gives you two commands: `gencheck` (CLI) and `gencheck-mcp` (MCP
server over stdio).

### 3. Pick how your agent calls it

| if your agent… | use | extra setup |
|---|---|---|
| can run a shell command — **any** agent | the CLI | none |
| speaks MCP (Claude Code, Cursor, custom) | the MCP server | one `claude mcp add` |
| is a browser demo or a human | the hosted portal | none — but see the warning below |

**On Claude Code?** Install the plugin instead of wiring it by hand — it bundles this
skill and the MCP server, and asks for your key once (kept in your OS keychain, never
written to a file you might commit):

```bash
/plugin marketplace add iamdudeGH/gencheck
/plugin install gencheck@gencheck
```

The plugin still needs the package from step 2 — the MCP server runs from that install,
so `pip install` first or the tools will not appear. The key prompt is skippable: leave
it blank and you still get the free read-only checks.

---

## Option A — the CLI (works for any agent)

The exit code is the gate, so a shell chain fails closed with no glue at all:

```bash
gencheck check "$CHECKOUT_URL" "$BRAND" && pay || refuse
```

| exit | meaning |
|---|---|
| `0` | **PAY** — consensus returned `is_real: true` |
| `1` | **BLOCK** — consensus returned a verdict, and it was not `is_real: true` |
| `2` | **ERROR** — no verdict obtained (no key, network failure, unverifiable) |

Both non-zero codes mean do not pay, so `&&` is safe without distinguishing them.

stdout is a single JSON object if you would rather parse than check exit codes:

```json
{ "status": "consensus_verdict", "is_real": false, "verdict": "wrong_seller",
  "confidence": 99, "decision": "BLOCK", "decision_reason": "…",
  "reasons": ["The checkout URL's domain is vardhan2k3.github.io, which is not amazon.com …"] }
```

Free reads, no key needed — use these before spending a consensus round:

```bash
gencheck cache shop.example     # the on-chain verdict for a domain, if one exists
gencheck domain example         # the registered official domain for a brand
```

## Option B — the MCP server

```bash
claude mcp add gencheck --env GENCHECK_PRIVATE_KEY=0x… -- gencheck-mcp
```

The key goes in the server's `env`, not the shell, because MCP stdio clients start
servers with a minimal default environment. Reads work with no key at all; only
writes need one.

### Tools

#### `gencheck_check_domain(domain)`

Free and instant — reads the on-chain verdict cache. Call this **first**: if the domain
was already judged, you get the consensus verdict with no cost and no wait.

```
{ "domain": "www.amazon.com", "status": "cached_consensus_verdict",
  "is_real": true, "decision": "PAY", "reason": "…" }
```

A domain that has never been validated returns `status: "never_validated"` and
`decision: "BLOCK"` — escalate to `gencheck_validate` if you want a real answer.

#### `gencheck_validate(checkout_url, brand)`

Full validator consensus, submitted as **a real transaction** on your account
(~0.00008 GEN). Validators independently fetch the checkout page **and** the claimed
brand's official site, then vote. Fails closed.

```
{ "checkout_url": "…", "brand": "amazon", "status": "consensus_verdict",
  "is_real": false, "verdict": "wrong_seller", "confidence": 99,
  "reasons": ["…"], "decision": "BLOCK", "decision_reason": "…" }
```

#### `gencheck_official_domain(brand)`

The registered official domain for a brand, or null if unknown. Useful to pre-check a
suspicious URL yourself before spending a consensus round.

### Usage pattern

```
1. domain = extract domain from checkout_url
2. r = gencheck_check_domain(domain)          # free, instant
3. if r.status == "never_validated":
       r = gencheck_validate(checkout_url, brand)   # consensus, costs fees
4. if r.decision != "PAY":  halt — do not sign or send payment
5. else: proceed with payment
```

## Option C — the hosted portal (demo only, not an integration)

**https://gencheck-live.vercel.app** runs the same gate in a browser, with the full jury
— every validator's address, vote, and model — shown per transaction. Use it to watch
the gate work or to check a domain by hand.

**Do not build an agent against it.** It signs with the portal owner's account, so you
get no cost control, no guarantee it stays funded, and — because the transaction is
signed by someone else — no on-chain proof that *you* asked for the check. For real
agent use, run the CLI or the MCP server on your own account.

The portal also serves this file at `GET /skill.md`.

## Cost and latency

| | |
|---|---|
| `gencheck check` / `gencheck_validate` | **one real transaction**, ~0.00008 GEN |
| `gencheck cache`, `gencheck domain`, `gencheck_check_domain` | free read — no transaction, no hash |
| First check of a domain | full validator consensus (validators fetch and reason) |
| Repeat check of a known domain | contract returns its cached verdict; still a real transaction, just no LLM round |

**Two caches — do not confuse them:**

- `gencheck_check_domain` / `gencheck cache` is a **free read** of an existing verdict.
  No transaction is created and there is no hash to show.
- `gencheck_validate` / `gencheck check` **always writes a real transaction with a
  hash**, even when the contract answers from its own domain cache. Use it when you
  need on-chain proof, or when the domain has never been judged.

On-chain verdicts are cached permanently, so a merchant is only ever fully
re-investigated once per contract — but note that the contract is immutable, so a
verdict that was wrong cannot be re-judged on the same deployment.

## What validators actually do

Each validator independently fetches the checkout URL and the brand's official site,
then reasons over domain ownership, page content, branding, and impersonation
heuristics, and submits a signed vote. GenLayer's consensus tallies the votes; the
resulting verdict is written on-chain. The reasoning is not a black box — the verdict
carries the validators' `reasons`, and the full jury (addresses, votes, models) is
readable from the transaction.

## Live deployment

| | |
|---|---|
| Network | studio-dev (chain 61997) — GEN is free from the faucet |
| Contract | `0xD914Bf44b78df2CC3FeFf343769800E11690288B` |
| Explorer | https://explorer-studio-dev.genlayer.com |
| Portal (demo) | https://gencheck-live.vercel.app |
| Source | https://github.com/iamdudeGH/gencheck |
| Working demo agent | `demo/shopping_agent.py` |

Every verdict is a real transaction — verify any of them independently on the explorer.

## Scope

GenCheck gates a payment **before** it happens. It is not a dispute-resolution or
escrow layer: it holds no funds and takes no custody. Agents that need adjudication
*after* a transaction are solving a different problem — GenCheck is the check that runs
first, and it composes with whatever settlement layer you already use.
