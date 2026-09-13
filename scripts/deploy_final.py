"""Deploy the GenCheck contract to studio-dev.

Deploys contracts/shopping_validator_v5.py — the admin-gated build that closes
three unauthenticated paths to a permanent, immutable bad verdict: the
registry had no caller check, the cache key held no brand, and a fetch failure
was cached. See the v0.5.0 docstring in the contract for the full list.

Usage:
    set GENCHECK_PRIVATE_KEY=0x...
    .venv-deploy/Scripts/python scripts/deploy_final.py
"""

import json
import os

from genlayer_py import create_account, create_client
from genlayer_py.chains import studio_devnet


def main():
    account = create_account(os.environ["GENCHECK_PRIVATE_KEY"])
    client = create_client(chain=studio_devnet, account=account)
    print(f"deployer: {account.address}", flush=True)

    estimate = client.estimate_transaction_fees()
    tx_id = client.deploy_contract(
        code=open("contracts/shopping_validator_v5.py", encoding="utf-8").read(),
        fees={"distribution": estimate["distribution"],
              "feeValue": estimate["feeValue"]},
    )
    print(f"deploy tx: {tx_id}", flush=True)
    receipt = client.wait_for_finalization(tx_id, retries=150, interval=5000)
    contract = receipt.get("data", {}).get("contract_address")
    ok = (receipt.get("txExecutionResultName") == "FINISHED_WITH_RETURN"
          and receipt.get("result_name") == "MAJORITY_AGREE" and contract)
    print(f"result: {receipt.get('result_name')} / "
          f"{receipt.get('txExecutionResultName')}", flush=True)
    if not ok:
        raise RuntimeError("deploy failed")

    # smoke-test a seeded brand lookup on the live contract
    cached = client.read_contract(address=contract, function_name="is_site_validated",
                                  args=["www.amazon.com"])
    print(f"is_site_validated(www.amazon.com) -> {cached} (False expected, empty cache)",
          flush=True)

    info = {"contract": contract, "deploy_tx": tx_id,
            "prompt_version": "v5-admin-gated-cache-integrity",
            "network": "studio-dev", "result_name": receipt.get("result_name")}
    with open("final_contract.json", "w") as f:
        json.dump(info, f, indent=2)
    print(json.dumps(info, indent=2), flush=True)
    print(f"\nexplorer: https://explorer-studio-dev.genlayer.com/address/{contract}")


if __name__ == "__main__":
    main()
