"""GenCheck client — the fail-closed payment gate for shopping agents.

Everything here is the code path proven live in the benchmark runs and the
demo agent: cache reads via `get_cached_result`, full validation via
`validate_checkout` through real validator consensus, verdict decode from
the leader's on-chain output.
"""

import base64
import json
import os
import time
from typing import Optional

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet

from .defaults import DEFAULT_CONTRACT, DEFAULT_FEES

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# get_transaction result names that mean "finished, no verdict coming" —
# anything else means consensus is still running.
_TERMINAL_RESULTS = {"FINISHED_WITH_ERROR", "REVERTED"}


def _verdict_from_payload(receipt: dict) -> Optional[dict]:
    """The leader's verdict out of a receipt's `result.payload.readable`.

    The runtime hands the output back already decoded, as a JSON string. Only a
    dict carrying `is_real` counts as a verdict, so a receipt whose payload is
    something else falls through to the eq_outputs path instead of returning
    noise that `decide()` would then have to rule on.
    """
    payload = (receipt.get("result") or {}).get("payload") or {}
    readable = payload.get("readable")
    if not isinstance(readable, str):
        return None
    try:
        data = json.loads(readable)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and "is_real" in data:
        return data
    return None


def load_contract_address() -> str:
    """The deployed GenCheck contract.

    `GENCHECK_CONTRACT` wins; then `final_contract.json` when running from a
    checkout, where the deploy script records provenance; then the address
    baked into the package — which is the only one available after a
    `pip install`, since the repo-root JSON is not part of the wheel.
    """
    env = os.environ.get("GENCHECK_CONTRACT")
    if env:
        return env
    path = os.path.join(_ROOT, "final_contract.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)["contract"]
    return DEFAULT_CONTRACT


def load_fees() -> dict:
    """Fee distribution for writes — the repo-root JSON on a checkout,
    otherwise the allocation pinned in `defaults.py`."""
    path = os.path.join(_ROOT, "benchmark_fees.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return DEFAULT_FEES


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
    """Retry transient RPC failures (Cloudflare challenges, JSON hiccups)."""
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
            time.sleep(base_delay * attempt)


class GenCheck:
    """The agent's trust layer: GenLayer validator consensus on checkout URLs.

    With a private key: full mode (can run consensus validations).
    Without: read-only mode (cache checks + registry lookups, free).
    """

    def __init__(self, private_key: Optional[str] = None):
        self.account = create_account(private_key) if private_key else create_account()
        self.client = create_client(chain=studio_devnet, account=self.account)
        self.contract = load_contract_address()
        self._fees = load_fees() if private_key else None

    # -- reads (free, instant) -------------------------------------------------

    def check_cache(self, domain: str) -> Optional[dict]:
        """Cached consensus verdict for a domain, or None if never validated."""
        try:
            return retry(lambda: self.client.read_contract(
                address=self.contract, function_name="get_cached_result",
                args=[domain]))
        except Exception:  # noqa: BLE001  (UserError = not yet validated)
            return None

    def official_domain(self, brand: str) -> str:
        """Registered official domain for a brand ('' if unregistered)."""
        return retry(lambda: self.client.read_contract(
            address=self.contract, function_name="get_official_domain",
            args=[brand]))

    # -- writes (real consensus) -----------------------------------------------

    def submit(self, checkout_url: str, brand: str) -> str:
        """Submit a validate_checkout transaction; returns the tx_id after
        ~2-5s, without waiting for consensus. Pair with poll() — designed for
        serverless hosts (Vercel) that kill long-running requests."""
        if self._fees is None:
            raise PermissionError(
                "GenCheck(private_key=...) is required to run validations")
        return retry(lambda: self.client.write_contract(
            address=self.contract, function_name="validate_checkout",
            args=[checkout_url, brand], account=self.account,
            fees={"distribution": self._fees["distribution"],
                  "feeValue": self._fees["paid_fee_value"]},
        ))

    def poll(self, tx_id: str, checkout_url: str = ""):
        """Non-blocking check of a submitted validation. Returns:
            dict      — consensus final, decoded verdict
            "pending" — consensus still running
            None      — finalized without a usable verdict (block by default)
        """
        tx = retry(lambda: self.client.get_transaction(tx_id))
        if tx.get("txExecutionResultName") != "FINISHED_WITH_RETURN":
            result = tx.get("txExecutionResultName")
            if result in _TERMINAL_RESULTS:  # finished, but badly
                return self._cache_fallback(checkout_url)
            return "pending"  # not finalized yet
        verdict = self.decode_verdict(tx_id)
        if verdict is None:
            # consensus returned but eq_output decode failed; fall back to cache
            return self._cache_fallback(checkout_url)
        return verdict

    def validate(self, checkout_url: str, brand: str) -> Optional[dict]:
        """Run full validator consensus on a checkout URL (blocking).

        Returns the verdict dict (is_real, verdict, confidence, reasons,
        evidence), or None if no verdict was produced (fetch failure beyond
        the contract's unverifiable handling, consensus timeout, tx error).
        The caller must treat None as BLOCK — see decide().
        """
        tx_id = self.submit(checkout_url, brand)
        for _ in range(150):  # ~12.5 min, matches the proven demo timings
            verdict = self.poll(tx_id, checkout_url)
            if verdict != "pending":
                return verdict
            time.sleep(5)
        return None

    def _cache_fallback(self, checkout_url: str) -> Optional[dict]:
        if not checkout_url:
            return None
        cached = self.check_cache(extract_domain(checkout_url))
        if cached is not None:
            return {"is_real": cached["is_real"],
                    "verdict": "real" if cached["is_real"] else "blocked",
                    "confidence": 100, "reasons": ["read from domain cache"],
                    "evidence": []}
        return None

    def decode_verdict(self, tx_id: str) -> Optional[dict]:
        """Full verdict (reasons, verdict, confidence) from the leader's
        on-chain output; the cache only stores is_real.

        Two receipt shapes are in circulation and both have to be handled:

        * `result.payload.readable` — the output the runtime already decoded
          to a JSON string. Present on old and new receipts alike.
        * `eq_outputs` — base64 of a blob with the JSON verdict embedded in
          it. Only the older rounds populate this.

        Reading `eq_outputs` alone is what broke the live portal: on rounds run
        after the network changed that field comes back EMPTY, so every fresh
        validation decoded to None and failed closed to BLOCK — the contract
        returned `is_real: true` while the page said "unverifiable".
        """
        tx = retry(lambda: self.client.get_transaction(tx_id))
        for receipt in tx["consensus_data"]["leader_receipt"]:
            from_payload = _verdict_from_payload(receipt)
            if from_payload is not None:
                return from_payload
            for val in (receipt.get("eq_outputs") or {}).values():
                raw = val.get("raw", "")
                data = base64.b64decode(raw + "=" * (-len(raw) % 4))
                start = data.find(b"{")
                if start != -1:
                    try:
                        return json.loads(data[start:])
                    except json.JSONDecodeError:
                        continue
        return None


def decide(verdict: Optional[dict]) -> tuple:
    """The agent's pay/block policy. FAILS CLOSED: anything that is not an
    explicit consensus-backed `is_real: true` gets blocked.

    Returns ("PAY" | "BLOCK", reason).
    """
    if verdict is None:
        return "BLOCK", "no verdict came back, so we can't confirm this page — blocked by default"
    if verdict.get("is_real") is True:
        return "PAY", verdict.get("verdict", "real")
    return "BLOCK", verdict.get("verdict", "unknown")
