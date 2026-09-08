# Security Policy

## Strict public boundary

**THIS IS A PUBLIC REPOSITORY — NEVER SUBMIT PRIVATE SUBSCRIPTION URLS, CREDENTIALS, TOKENS, PRIVATE KEYS, OR PERSONAL ACCESS/PROXY CONFIGURATIONS.**

The catalog accepts only public HTTP/HTTPS subscription candidates. URLs containing userinfo credentials, suspicious authentication/query parameters, or credential-like secret material must be rejected before publication.

Private WireGuard inventories are explicitly out of scope. Do not publish or feed into this repository personal/provider WireGuard profiles, including ProtonVPN/FastestVPN account-derived nodes, `PrivateKey`, `PresharedKey`, complete client profiles, or any representation from which private access material can be reconstructed.

Discovery also applies a content guard to candidate payload files: actionable WireGuard secret assignments and `wg://` payloads are rejected before they can become catalog candidates. `PublicKey`, endpoint and country metadata alone are not treated as secrets, but they still must not be used as a path for exporting a user's private inventory.

The allowed direction is one-way: this public catalog may provide sanitized candidate metadata to a private monitoring VPS. The private VPS must never upload its trusted/provider inventory back into this repository.

If a candidate is ambiguous, reject it rather than publish it.

Do not report secrets in issues, pull requests, Actions logs, or catalog notes.
