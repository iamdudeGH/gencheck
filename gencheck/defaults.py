"""Values the installed package needs that used to live only at the repo root.

`client.py` reads the deployed contract address and the fee distribution from
JSON files next to the repository root. That works from a checkout — but a
`pip install` ships only the `gencheck/` package, so those files are absent and
`GenCheck()` raises FileNotFoundError the first time anyone uses it.

The same two values are duplicated here as the fallback. Precedence is:

    GENCHECK_CONTRACT env var  >  repo-root JSON (a checkout)  >  these

Keep them in sync with `final_contract.json` and `benchmark_fees.json`.
"""

# GenCheck on studio-dev (chain 61997). v5, deployed 13 Sept 2026 — the
# admin-gated build. Deliberately not the earlier deployments recorded in the
# benchmark lineage: they are immutable and still carry the unauthenticated
# registry write / brand-less cache key / cached-fetch-failure defects.
DEFAULT_CONTRACT = "0xD914Bf44b78df2CC3FeFf343769800E11690288B"

# Fee distribution for validate_checkout. The SDK's own defaults
# (`estimate_transaction_fees`) hit BudgetTooLow / FeesDistributionMissing on
# studio-dev, so the allocation proven across the benchmark runs is pinned.
#
# This is the *budget*, not the price: `paid_fee_value` is held at submit and
# mostly refunded at finalization. The real measured cost is ~0.00008 GEN per
# validation. Read `fees.consumed`, never `fees.deposit` — the deposit
# overstates the cost by roughly 7x.
DEFAULT_FEES = {
    "distribution": {
        "rotations": [3],
        "appealRounds": 0,
        "totalMessageFees": 0,
        "executionConsumed": 0,
        "receiptFeeMaxGasPrice": 300000000,
        "storageFeeMaxGasPrice": 300000000,
        "maxPriceGenPerTimeUnit": 2,
        "executionBudgetPerRound": 156987300000000,
        "leaderTimeunitsAllocation": 100,
        "validatorTimeunitsAllocation": 200,
    },
    "paid_fee_value": 627949200010352,
    "primary_fee_spent": 83236750000823,
    "total_refunded": 544712450009529,
}
