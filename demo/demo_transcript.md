> **Stale — recorded before the v5 deploy, and before the demo URL swap.** This
> is the captured output of a real run, so it is left intact rather than edited;
> editing a transcript by hand would make it a fabricated record. Two things in
> it no longer hold:
>
> - it names the **v4** contract `0x61153C8d…`, not the live v5 contract
> - its offer 1, `vardhan2k3.github.io`, now returns **404** from GitHub Pages,
>   so that block came from the contract failing closed, not from detection —
>   the demo appeared to work while demonstrating nothing. `shopping_agent.py`
>   now points at a live clone instead.
>
> Regenerate with a funded key:
> `.venv-deploy/Scripts/python demo/shopping_agent.py`

```text
========================================================================
GENCHECK SHOPPING AGENT — end-to-end demo (studio-dev, live consensus)
========================================================================
GenCheck contract: 0x61153C8d907eBa4Ea96d5955c7b05F67F2967e2D

Customer request: "Buy me the cheapest Amazon Echo Dot you can find"

Product search returned 2 offers (cheapest first):
  1. vardhan2k3.github.io         $19.99  found via product search — 60% below market
  2. www.amazon.com               $49.99  official Amazon cart

[offer 1] vardhan2k3.github.io — $19.99 (brand: amazon)
      asking GenCheck validators to fetch the page and judge...
      validator consensus took 56s
      verdict:   wrong_seller
      is_real:   False
      confidence:99
      reason:    The checkout URL's domain is vardhan2k3.github.io, which is not amazon.com nor a subdomain of amazon
      reason:    GitHub Pages (github.io) is a separate hosting service unrelated to Amazon.
      >>> DECISION: BLOCK — vardhan2k3.github.io (wrong_seller)

[offer 2] www.amazon.com — $49.99 (brand: amazon)
      asking GenCheck validators to fetch the page and judge...
      validator consensus took 78s
      verdict:   real
      is_real:   True
      confidence:99
      reason:    The checkout URL domain is 'amazon.com', which is the official domain for Amazon.
      reason:    The page content matches exactly with the official Amazon page content, including navigation, depart
      reason:    The URL path '/gp/cart/view.html' is a well-known and legitimate Amazon cart URL structure.
      >>> DECISION: PAY — $49.99 to www.amazon.com (real)

========================================================================
RESULT: purchased from www.amazon.com for $49.99.
Blocked offers cost the customer nothing. That is the point.
========================================================================
```
