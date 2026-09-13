```text
========================================================================
GENCHECK SHOPPING AGENT — end-to-end demo (studio-dev, live consensus)
========================================================================
GenCheck contract: 0xD914Bf44b78df2CC3FeFf343769800E11690288B

Customer request: "Buy me the cheapest Amazon Echo Dot you can find"

Product search returned 2 offers (cheapest first):
  1. sarthforge.github.io         $19.99  found via product search — 60% below market
  2. www.amazon.com               $49.99  official Amazon cart

[offer 1] sarthforge.github.io — $19.99 (brand: amazon)
      asking GenCheck validators to fetch the page and judge...
      validator consensus took 13s
      verdict:   scam
      is_real:   False
      confidence:99
      reason:    The checkout URL domain is 'sarthforge.github.io', which is a GitHub Pages hosting domain and has …
      reason:    The page is an 'amazon-clone' explicitly named as such in the URL path ('/amazon-clone/cart.html'), …
      reason:    The page copies Amazon's branding, layout, and design elements (logo, navigation, footer text …
      >>> DECISION: BLOCK — sarthforge.github.io (scam)

[offer 2] www.amazon.com — $49.99 (brand: amazon)
      asking GenCheck validators to fetch the page and judge...
      cache hit: domain already validated for this brand (instant, free)
      verdict:   real
      is_real:   True
      confidence:99
      reason:    cached consensus verdict for brand 'amazon' (confidence 99); the specific verdict and its reasoning …
      >>> DECISION: PAY — $49.99 to www.amazon.com (real)

========================================================================
RESULT: purchased from www.amazon.com for $49.99.
Blocked offers cost the customer nothing. That is the point.
========================================================================
```
