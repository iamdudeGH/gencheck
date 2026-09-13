"""GenCheck verification portal — let anyone test the trust layer in a browser.

FastAPI app wrapping the proven `gencheck` client package. Same contract,
same fail-closed logic as the agent demo and MCP server — this is a new
interface, not a new trust path.

Endpoints:
    GET  /               → the single-page frontend (static/index.html)
    GET  /skill.md       → the agent-facing skill (static/skill.md)
    GET  /api/examples   → curated example URLs (pre-cached → instant results)
    POST /api/check      → {url, brand} → verdict (blocking; long-lived servers)
    POST /api/submit     → {url, brand} → cached verdict, or a tx_id to poll
    GET  /api/status     → real chain state of a submitted tx + consensus detail

Run locally:
    .venv-deploy/Scripts/pip install fastapi uvicorn
    set GENCHECK_PRIVATE_KEY=0x...   (optional; without it, only cached domains work)
    .venv-deploy/Scripts/uvicorn portal.app:app --port 8000

Deploy: see portal/DEPLOY.md (Docker image included).
"""

import os
import sys
import time
from collections import defaultdict, deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gencheck import GenCheck, decide
from gencheck.client import extract_domain, retry

app = FastAPI(title="GenCheck verification portal")

_private_key = os.environ.get("GENCHECK_PRIVATE_KEY")
_gc: GenCheck | None = None
_gc_full: GenCheck | None = None

# --- cost/abuse guards ------------------------------------------------------
# EVERY check is a real `validate_checkout` transaction on the contract — the
# portal has no cache short-circuit, so example chips and pasted URLs alike
# produce an on-chain transaction with a hash the visitor can verify.
#
# Measured cost: ~0.00008 GEN actually consumed per transaction. The full
# budget (0.000628 GEN) is held at submit and the unused remainder is refunded
# at finalization, so the deposit overstates the cost by roughly 7x. Cost is
# not the constraint — these limits exist to stop one visitor flooding the
# network, and the global cap bounds the worst-case drain of the demo wallet
# (~0.04 GEN/hour).
RATE_LIMIT_PER_IP = 30         # real transactions per IP per rolling hour
GLOBAL_LIMIT_PER_HOUR = 400    # ~0.04 GEN/hour worst case
RATE_WINDOW_S = 3600
_validation_times: dict[str, list[float]] = defaultdict(list)
_global_starts: list[float] = []

EXAMPLES = [
    # A live Amazon lookalike, taken from the OpenPhish community feed. The
    # previous demo target (vardhan2k3.github.io) began returning 404 from
    # GitHub Pages, so it was still blocking — but by failing closed, not by
    # detecting anything. A demo that blocks a dead page demonstrates nothing,
    # which is why the URL was swapped rather than left. Phishing pages get
    # taken down fast: if this one starts 404ing, pull a replacement from
    # https://openphish.com/feed.txt (any live *.github.io Amazon clone)
    # instead of leaving a dead page wired into the demo.
    {"label": "Amazon checkout clone on github.io",
     "url": "https://sarthforge.github.io/amazon-clone/cart.html",
     "brand": "amazon", "expected": "blocked"},
    {"label": "Real Amazon cart",
     "url": "https://www.amazon.com/gp/cart/view.html",
     "brand": "amazon", "expected": "cleared"},
    {"label": "Best Buy cart",
     "url": "https://www.bestbuy.com/cart", "brand": "bestbuy",
     "expected": "cleared"},
    {"label": "Walmart cart",
     "url": "https://www.walmart.com/cart", "brand": "walmart",
     "expected": "cleared"},
    {"label": "Target cart",
     "url": "https://www.target.com/cart", "brand": "target",
     "expected": "cleared"},
    {"label": "Sephora (blocks validators → unverifiable)",
     "url": "https://sephora.com/checkout", "brand": "sephora",
     "expected": "unverifiable"},
]


# Verdict details decoded from the leader's on-chain output of the live
# consensus runs on this contract (demo transcript + v4 unverifiable
# verification).
# The on-chain cache stores only {domain, is_real}; these let the portal show
# the real reasoning for the pre-warmed example domains. Cache still wins:
# is_real is always taken from the chain, never from this table.
KNOWN_VERDICTS = {
    # The vardhan2k3.github.io entry was removed along with the URL swap above.
    # Its guard compares only `is_real`, and the domain now 404s — so it returns
    # `unverifiable` with is_real False, which matched this entry's is_real
    # False and attached wrong_seller reasoning to what was really a fail-closed
    # fetch failure. Do not add an entry for the new demo domain until a real
    # consensus run has produced its reasons: these are decoded on-chain output,
    # and writing them by hand would put fabricated evidence on the page.
    "www.amazon.com": {
        "is_real": True, "verdict": "real", "confidence": 99,
        "reasons": [
            "The checkout URL domain is 'amazon.com', which is the official domain for Amazon.",
            "The page content matches exactly with the official Amazon page content.",
            "The URL path '/gp/cart/view.html' is a well-known and legitimate Amazon cart URL structure.",
        ],
    },
    "www.bestbuy.com": {
        "is_real": True, "verdict": "real", "confidence": 99,
        "reasons": [
            "The checkout URL domain is bestbuy.com, which is the official domain of Best Buy.",
            "The page content clearly displays Best Buy branding, trademarks, and copyright notice.",
            "No typosquatting, homoglyphs, or subdomain tricks are present — the domain is exactly bestbuy.com.",
        ],
    },
    "www.walmart.com": {
        "is_real": True, "verdict": "real", "confidence": 100,
        "tx_id": "0x1f877f92bd84e0779090beddfb1c04dac380f24dcd74b6fd4b151801d2b2882d",
        "reasons": [
            "Domain matches official Walmart domain",
            "Page content displays Walmart branding and typical product listings",
        ],
    },
    "www.target.com": {
        "is_real": True, "verdict": "real", "confidence": 100,
        "tx_id": "0x45b87f106cc7ffa4b66ed8c97a9fbd802e962ff3e68f0c9287998b491b0da6c4",
        "reasons": [
            "The checkout URL's domain 'target.com' is the official primary domain for the Target retail corporation.",
        ],
    },
    "www.etsy.com": {
        "is_real": False, "verdict": "unverifiable", "confidence": 0,
        "tx_id": "0xc6f4e30316e628e63e866e1ada082215e8da85470370920f31963cdd1f12b877",
        "reasons": [
            "checkout page could not be fetched by validators (bot-blocking or offline): https://www.etsy.com/cart",
        ],
    },
    "sephora.com": {
        "is_real": False, "verdict": "unverifiable", "confidence": 0,
        "reasons": [
            "checkout page could not be fetched by validators (bot-blocking or offline): https://sephora.com/checkout",
        ],
    },
}


def _readonly() -> GenCheck:
    global _gc
    if _gc is None:
        _gc = GenCheck()
    return _gc


def _full() -> GenCheck | None:
    global _gc_full
    if not _private_key:
        return None
    if _gc_full is None:
        _gc_full = GenCheck(private_key=_private_key)
    return _gc_full


def _rate_state(ip: str) -> tuple[bool, bool]:
    """(ip_ok, global_ok) against the rolling-hour windows."""
    now = time.time()
    times = [t for t in _validation_times[ip] if now - t < RATE_WINDOW_S]
    _validation_times[ip] = times
    glob = [t for t in _global_starts if now - t < RATE_WINDOW_S]
    _global_starts[:] = glob
    return len(times) < RATE_LIMIT_PER_IP, len(glob) < GLOBAL_LIMIT_PER_HOUR


def _note_start(ip: str) -> None:
    _validation_times[ip].append(time.time())
    _global_starts.append(time.time())


class CheckRequest(BaseModel):
    url: str
    brand: str = ""


def _validate_input(req: CheckRequest):
    """URL/brand validation shared by /api/check and /api/submit.
    Returns (error_response | None, url, brand, domain).

    Deliberately does NOT consult the cache: every check must produce its own
    on-chain transaction, so there is no short-circuit here.
    """
    url = req.url.strip()
    brand = req.brand.strip().lower()
    if not url.lower().startswith(("http://", "https://")):
        return JSONResponse({"error": "URL must start with http:// or https://"}, 400), url, brand, ""
    if not brand:
        return JSONResponse({"error": "brand is required (e.g. 'amazon')"}, 400), url, brand, ""
    return None, url, brand, extract_domain(url)


def _verdict_response(url, brand, domain, verdict, status, is_cached, tx_id=None):
    """One verdict dict → the frontend's JSON shape (fail-closed).

    A transaction whose verdict came out of the contract's own domain cache
    still has its own real hash; where we know the original consensus run that
    filled that cache, it is attached as `original_tx_id` / `original_reasons`
    so the page can show the evidence behind a cached answer.
    """
    verdict = dict(verdict or {})
    reasons = [str(r) for r in (verdict.get("reasons") or [])]
    from_cache = is_cached or any("cache" in r.lower() for r in reasons)
    known = KNOWN_VERDICTS.get(domain)
    original_tx_id, original_reasons = None, []
    if known and known["is_real"] == verdict.get("is_real"):
        original_tx_id = known.get("tx_id")
        original_reasons = known.get("reasons") or []
    action, why = decide(verdict if verdict else None)
    conf = verdict.get("confidence")
    if isinstance(conf, float) and conf <= 1.0:
        conf = int(round(conf * 100))
    return {
        "url": url, "brand": brand, "domain": domain,
        "status": status, "is_cached": from_cache,
        "is_real": verdict.get("is_real"),
        "verdict": verdict.get("verdict"),
        "confidence": conf,
        "reasons": reasons[:4],
        "tx_id": tx_id or verdict.get("tx_id"),
        "original_tx_id": original_tx_id,
        "original_reasons": original_reasons[:4],
        "decision": action, "reason": why,
    }


@app.get("/api/examples")
def examples():
    return {"examples": EXAMPLES, "contract": _readonly().contract,
            "recent": list(reversed(_recent)),
            "explorer": "https://explorer-studio-dev.genlayer.com"}


@app.post("/api/check")
def check(req: CheckRequest, request: Request):
    """Blocking check: submits a real transaction and waits for consensus
    (holds the request open). Long-lived servers only — Vercel uses
    /api/submit + /api/status."""
    early, url, brand, domain = _validate_input(req)
    if early is not None:
        return early
    gc_full = _full()
    ip = request.client.host if request.client else "?"
    if gc_full is None:
        return JSONResponse(_no_key_response(url, brand, domain), 200)
    ip_ok, global_ok = _rate_state(ip)
    if not (ip_ok and global_ok):
        return JSONResponse(_rate_limited_response(url, brand, domain), 429)
    _note_start(ip)
    verdict = gc_full.validate(url, brand)
    return _verdict_response(url, brand, domain, verdict, "consensus", False)


@app.post("/api/submit")
def submit(req: CheckRequest, request: Request):
    """Submit a real `validate_checkout` transaction; returns in ~2s with the
    transaction hash to poll. There is no cache short-circuit — every check,
    including the example chips, is an on-chain transaction."""
    early, url, brand, domain = _validate_input(req)
    if early is not None:
        return early
    gc_full = _full()
    ip = request.client.host if request.client else "?"
    if gc_full is None:
        return JSONResponse(_no_key_response(url, brand, domain), 200)
    ip_ok, global_ok = _rate_state(ip)
    if not (ip_ok and global_ok):
        return JSONResponse(_rate_limited_response(url, brand, domain), 429)
    _note_start(ip)
    try:
        tx_id = gc_full.submit(url, brand)
    except Exception as e:  # noqa: BLE001 — errors must never look like an allow
        return JSONResponse({
            "url": url, "brand": brand, "domain": domain,
            "status": "error", "is_cached": False,
            "is_real": False, "decision": "BLOCK",
            "reason": f"could not submit the validation transaction: {e}",
        }, 200)
    _record(domain, brand, None, "submitted")
    return {"url": url, "brand": brand, "domain": domain,
            "status": "pending", "is_cached": False, "tx_id": tx_id,
            "submitted_at": int(time.time())}


@app.get("/api/status")
def status(tx_id: str, url: str = "", brand: str = ""):
    """Real chain state of a submitted validation — every field below comes
    straight from the node's get_transaction response.

    stage: "pending" (validators still working) | "final" (verdict ready)
    On final: the verdict plus the consensus detail — each validator's
    address, vote, and the LLM they ran.
    """
    gc = _readonly()
    try:
        tx = retry(lambda: gc.client.get_transaction(tx_id))
    except Exception:  # noqa: BLE001 — node hiccup; keep polling
        return {"stage": "pending", "tx": {"id": tx_id, "state": "UNKNOWN"}}

    state = tx.get("txExecutionResultName")
    if state != "FINISHED_WITH_RETURN":
        if state in ("FINISHED_WITH_ERROR", "REVERTED"):
            verdict = gc._cache_fallback(url)
            domain = extract_domain(url) if url else ""
            _record(domain, brand, verdict, "error")
            return {
                "stage": "final",
                "tx": {"id": tx_id, "state": state},
                "verdict": _verdict_response(url, brand, domain, verdict,
                                             "no_verdict", False, tx_id),
            }
        return {"stage": "pending", "tx": {"id": tx_id, "state": state or "UNKNOWN"}}

    verdict = gc.decode_verdict(tx_id)
    if verdict is None:
        verdict = gc._cache_fallback(url)
    domain = extract_domain(url) if url else ""
    _record(domain, brand, verdict, "consensus")
    return {
        "stage": "final",
        "tx": {"id": tx_id, "state": state,
               "created_at": tx.get("created_at")},
        "verdict": _verdict_response(url, brand, domain, verdict,
                                     "consensus", False, tx_id),
        "consensus": _consensus_detail(tx),
        "chain": _fee_detail(tx),
    }


def _consensus_detail(tx: dict) -> dict:
    """Real per-validator consensus data straight off the node.

    Every field is read from the transaction's own consensus data — the
    validator's address, its vote, the LLM that node actually ran, and how long
    it took. Nodes that never voted carry no model, and are reported with an
    empty model rather than a guess.

    The round's roster comes from `last_round.round_validators` — the nodes
    actually asked to vote, leader included — because a transaction read at the
    instant it finalizes can still come back with an empty vote map. Building
    the table from the roster keeps the jury whole while the votes fill in;
    `complete` says whether they have.
    """
    cd = tx.get("consensus_data") or {}
    votes = cd.get("votes") or {}
    lr = tx.get("last_round") or {}
    by_addr = {}
    for v in cd.get("validators") or []:
        nc = v.get("node_config") or {}
        pm = nc.get("primary_model") or {}
        by_addr[nc.get("address", "")] = {
            "model": pm.get("model", ""), "provider": pm.get("provider", ""),
            "processing_time": v.get("processing_time"),
        }
    # leader_receipt carries one entry per role the leader played in the round:
    # the proposal itself (mode "leader", which is the one holding the model and
    # the timing) plus a validator pass it was also asked to make — often an
    # idle/errored duplicate of the same address. Take the proposal entry.
    receipts = cd.get("leader_receipt") or []
    leader = next((r for r in reversed(receipts) if r.get("mode") == "leader"),
                  receipts[0] if receipts else {})
    lnc = leader.get("node_config") or {}
    lpm = lnc.get("primary_model") or {}
    leader_addr = lnc.get("address", "")
    try:
        leader_index = int(lr.get("leader_index") or 0)
    except (TypeError, ValueError):
        leader_index = 0

    roster = [a for a in (lr.get("round_validators") or []) if a]
    for addr in votes:
        if addr not in roster:
            roster.append(addr)
    if leader_addr and leader_addr not in roster:
        roster.append(leader_addr)
    if not leader_addr and roster:
        leader_addr = roster[leader_index] if leader_index < len(roster) else ""

    out = []
    for i, addr in enumerate(roster):
        info = by_addr.get(addr) or {}
        is_leader = (addr == leader_addr) if leader_addr else (i == leader_index)
        out.append({
            "address": addr, "vote": votes.get(addr, ""),
            "role": "leader" if is_leader else "validator",
            "model": info.get("model") or (lpm.get("model", "") if is_leader else ""),
            "provider": info.get("provider") or
                        (lpm.get("provider", "") if is_leader else ""),
            "processing_time": (leader.get("processing_time") if is_leader
                                else info.get("processing_time")),
        })
    # leader first, then the nodes that voted for the proposal, then the rest
    out.sort(key=lambda r: (0 if r["role"] == "leader" else 1,
                            0 if r["vote"] == "agree" else 1,
                            r["address"]))
    return {
        "validators": out,
        "quorum": {"agree": sum(1 for r in out if r["vote"] == "agree"),
                   "total": len(out)},
        "complete": bool(roster) and len(votes) >= len(roster),
        "leader": {"address": leader_addr, "model": lpm.get("model", ""),
                   "processing_time": leader.get("processing_time")},
    }


def _fee_detail(tx: dict) -> dict:
    """What the transaction actually cost, from the node's own fee accounting.

    `deposit` is the budget held at submit; `consumed` is what is really spent
    and the remainder is refunded. The cost shown is the consumed figure — the
    deposit would overstate it by roughly 7x.

    Fee accounting settles well *after* finality — measured at 35.4 s on
    studio-dev: read at the instant the transaction returns (and for the next
    half-minute), `consumed` is still all zeros. `settled` says whether the
    figures below are populated yet, so the caller can wait instead of
    reporting a cost of nothing.
    """
    f = tx.get("fees") or {}
    c = f.get("consumed") or {}
    wei = 10 ** 18
    spent = (int(c.get("executionConsumed") or 0)
             + int(c.get("storageFeeUsed") or 0)
             + int(c.get("messageFeesConsumed") or 0))
    held = int(f.get("deposit") or 0)
    return {
        "settled": bool(spent),
        "cost_gen": (spent / wei) if spent else None,
        "held_gen": (held / wei) if held else None,
        "refunded_gen": ((held - spent) / wei) if (held and spent) else None,
        "leader_timeunits": c.get("leaderTimeunitsUsed"),
        "validator_timeunits": c.get("validatorTimeunitsUsed"),
    }


# -- live activity feed (in-memory; per instance on serverless) ----------------
_recent: deque = deque(maxlen=10)


def _record(domain: str, brand: str, verdict: dict | None, status: str):
    if not domain:
        return
    try:
        _recent.append({
            "domain": domain, "brand": brand,
            "is_real": (verdict or {}).get("is_real"),
            "verdict": (verdict or {}).get("verdict") or
                       ("real" if (verdict or {}).get("is_real") else "blocked"),
            "status": status, "ts": int(time.time()),
        })
    except Exception:  # noqa: BLE001 — the feed must never break a check
        pass


def _no_key_response(url, brand, domain):
    return {
        "url": url, "brand": brand, "domain": domain,
        "status": "no_key", "is_cached": False,
        "is_real": False, "decision": "BLOCK",
        "reason": ("this portal has no funded key configured, so it cannot "
                   "submit validation transactions — every check here is a "
                   "real on-chain transaction, and there is no cached "
                   "shortcut to fall back on"),
    }


def _rate_limited_response(url, brand, domain):
    return {
        "url": url, "brand": brand, "domain": domain,
        "status": "rate_limited", "is_cached": False,
        "is_real": False, "decision": "BLOCK",
        "reason": ("rate limit reached for this visitor — each check submits "
                   "a real transaction, so the portal caps how many one "
                   "visitor can send per hour. Try again later."),
    }


_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
