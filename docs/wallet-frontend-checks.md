# Clan wallet frontend checks

Integration branch: `feat/multisig-treasury`. This work is not deployed and does not target `main`.

The F0–F7 sections record their original PR checks. F8 below records the 5 November API integration and supersedes the earlier planned-route limitations. The backend team merged #7–#10 into the integration branch in `333917d`.

## F0–F1: API and signing key setup

- Typed clients cover implemented and planned routes. `toClanPolicy` preserves both key lists' order. The actual setup API returns a null generation before setup; the type allows it.
- The setup saves through the supplied store interface before registering a public key. Full backup words are visible only on the backup step. PIN and backup words are never request fields.
- The backend team's real `vault/store.ts` landed in commit `2230cf2`. The adapter picks it up automatically. The development preview uses an isolated memory-only store; refreshing loses those synthetic keys. No encryption or persistent private-key storage was implemented by these frontend jobs.
- The development preview is `/__wallet_preview` on the Vite dev server. It and its test-network fixtures are removed from the production build. Valid and altered unsigned payout fixtures come from the existing backend interop helpers; no network is used to generate them.

Checks: TypeScript/Vite build passed; `backend/tests/test_clan_wallet_interop.py`: 3 passed. Eleven local browser checks passed, including five widths (320, 390, 430, 768, 1366), backup checks, PIN mismatch and public-only registration. Saved-key screenshots at 390×844 in both themes were inspected: `output/playwright/clan-wallet-key-saved-{dark,light}.png`. Backup-word and PIN screens are deliberately not captured. No actionable P0/P1/P2 layout issues.

Production bundle inspection found no preview route, preview-store module, fixture payout ID or development warning text. No changes to `vault/policy.ts`, `vault/sign.ts`, `vault/keys.ts`, backend routes or public custody text.

## F2–F3: phone wallet code and status

The unlocked key must match `me.key` and appear in the policy. The displayed/submitted code is computed on the phone; the server's code is never used. A fresh wallet read binds confirmation to the same generation and public rules. Mismatch, missing membership and a 409 confirmation refusal stop the flow. Wrong PIN allows another unlock attempt. Public-only checked wallet rules are saved for later payout checks; no words or PIN enter that record.

Build and 3 interop tests passed. Twenty-one comparison/security browser checks and fifty status/theme/width checks passed. Code and all status cards were captured at 390×844 in both themes under `output/playwright/clan-wallet-*.png`; code and key screenshots were inspected. No actionable P0/P1/P2 findings. Test cases cover an incorrect server code, wrong phone key, key missing from policy, 409 refusal, member disagreement, read-only members and the disabled gate.

The status sweep initially timed out because the select's accessible name included its option text. An explicit accessible label fixes the harness; all fifty checks were then rerun successfully. The timeout did not count as a passed run.

## F4–F5: payout review and receiving address

Active wallets use phone-reviewed Bitcoin payments; known inactive/disabled wallets retain the existing Lightning flow. Unknown wallet errors show retry instead of falling back to spending. Payouts also respect the existing payment pause. The phone checks the fee, fee payer and each received amount against `amountsReceived()`, and requires its previously compared public wallet rules before signing. It rereads the draft and wallet before unlocking and signing; changed drafts require a fresh review. Only the signed payment copy is posted. Words are dropped before that request.

Receiving addresses decode locally on the test network. Invalid and mainnet addresses cause no address POST. The estimate response must match the address, grant amount and approved-minus-fee calculation; inconsistent responses stop the flow. The planned contract provides the estimate only in the address POST response, so the screen explicitly adds the address first and then shows that estimate, before any payout signatures. A quote-only route is requested in the PR.

Synthetic payout fixtures are reproducible with `scripts/build_wallet_fixtures.py`; the generator preserves the preview policy's key order. The initial fixtures had a different order and were correctly refused by phone review. No wallet maths files were changed.

Build passed; interop: 3 passed. Thirty-five browser checks passed, including valid signing, tampered outputs, altered fee display, replaced drafts, every payout status, invalid/mainnet address rejection and inconsistent estimate rejection. Payout and receiving screens were checked at all five widths in both themes. Screenshots at 390×844 are `clan-wallet-payout-{dark,light}.png` and `clan-wallet-receiving-{dark,light}.png`. Dark payout and light receiving screenshots were inspected; no actionable P0/P1/P2 layout issues. No backup-word or PIN screen was captured.

## F6–F7: contributions, repayments and a new phone

The phone checks the external address, index, purpose and grant binding before creating a QR, showing an address, enabling copy or opening a wallet. Bitcoin URI amounts use integer arithmetic. Signatories use their compared public wallet rules. Members see the test-network warning, send-fee explanation and advice for amounts below 5,000 sats. Lightning is offered only when the till says it is available; till invoice responses must explicitly identify the Lightning method. A full-till response cannot accidentally display an old Lightning invoice as a clan-wallet payment.

At F6–F7, the contract did not specify an incoming-payment confirmation route. That version demonstrated pending/received states with isolated fixtures. F8 below now uses the implemented receipts route. The full-till redirect still belongs to the planned Lightning till integration.

Restore uses twelve password inputs with local BIP-39 word suggestions. It rejects a different public key before protection or saving. Correct words are passed only to the supplied key-store interface, input references are removed before protection, and references are dropped after saving/closing. Restore sends no API request. It clears the phone's old public wallet comparison and requires comparison again before signing. Public-key derivation in setup/restore wipes its temporary account private data.

Final checks:

- TypeScript/Vite production build passed. Existing country-lookup chunk size warning remains.
- Wallet interoperability and the backend team's encrypted-store check: **4 passed**.
- `scripts/check_wallet_browser.py`: **162 passed**, run serially against the isolated Vite preview. This includes setup 11, comparison 21, status 50, payouts/receiving 35, deposits/restore 37 and existing-flow routing 8.
- Every new screen was checked at 320/390/430/768/1366 in both themes. At 390×844, deposit, empty restore and restored-key captures are `clan-wallet-deposit-{dark,light}.png`, `clan-wallet-restore-empty-{dark,light}.png` and `clan-wallet-restored-{dark,light}.png`. Empty restore/light, restored/dark and deposit/both themes were inspected. A cramped estimate was fixed by placing it below the sats amount. No outstanding P0/P1/P2 layout finding.
- No backup words or PINs were captured in screenshots or test output. Word-entry screenshots are empty. The preview route, payout fixtures and preview store are absent from production assets; the real encrypted store is present.
- `git diff --check` passed. No changes to the three protected wallet maths modules, backend routes, database or public custody copy.

PR merge order into `feat/multisig-treasury`: [F0–F1 #7](https://github.com/Afribit-Kibera/afribit-clans/pull/7), then [F2–F3 #8](https://github.com/Afribit-Kibera/afribit-clans/pull/8), then [F4–F5 #9](https://github.com/Afribit-Kibera/afribit-clans/pull/9), then the F6–F7 PR. These are cumulative branches; do not squash/cherry-pick the same earlier work twice. Nothing has been merged into main or deployed by these jobs.

To review locally, run the frontend Vite dev server and open `/__wallet_preview`. It is synthetic test-network data, separate from app accounts and the real vault. Run `scripts/check_wallet_browser.py` with that server on port 5182 and a Playwright CLI session named `clans-wallet`. `scripts/build_wallet_fixtures.py` rebuilds unsigned fixtures offline using the backend test environment.

## F8: real API integration, 5 November 2026

Started from `828b7b5`, then rebased onto `a613dae` when the backend team added higher-fee versions to F8. Branch: `feat/clan-wallet-screens-f8`. All money calls use the real typed API client; development fixtures have the same updated shapes.

- The beneficiary obtains a read-only fee quote, checks it and explicitly confirms the address. Changing an address refreshes the payout section. Temporary network failures and insufficient confirmed funds have retry instructions. A changed fee in a successful save is reported as saved with an updated estimate; it does not pretend the POST was read-only.
- Payouts use one grant-filtered list instead of six status requests, follow `replaced_by` with clan/grant checks and cycle protection, and distinguish Sending, Sent and Confirmed. Expired/replaced versions link to the latest version and cannot be signed. The phone reviews the API's copy including existing signatures and adds its own. A rejected signature remains unsigned with the backend message visible until an explicit retry/review.
- A delayed sent payment checks for a waiting higher-fee version every 30 seconds and links to it. The new draft shows its fee and lower received amount, with a link to the earlier payment; the phone reviews it again and it needs fresh clan and oversight signatures. The real watcher check exercised both versions and confirmed only the replacement.
- Contributions, clan funding (index zero) and grant repayments derive/check their addresses before display. Repayment entry is limited to grants in recovery with an outstanding balance. Receipts poll every 30 seconds; focus and manual checks can refresh sooner. New confirmations reload the wallet and current grant.
- Receipt identity is `txid:vout`. Conflicting duplicates, a different address/purpose/grant, and a confirmed flag below three confirmations are rejected. Identical duplicates count once. Payments already confirmed when a reused address is reopened are shown as earlier address history; they cannot complete a new amount request. Dropped payments are explained without crediting them.
- The app recognises active Bitcoin wallets independently of Lightning worker readiness while retaining the existing receiving/payout pause controls. Wallet grants needing an address or signature appear in Vote & approve and the activity action list. Open grant details refresh with the backend.
- Till availability is still planned. A missing till endpoint is quiet; no Lightning invoice is invented. The earlier checked-address path remains the fallback for full-till redirects once that backend ships.

### Reproduce the local API check

The following harness uses the real app, SQLite ledger, encrypted browser key store, signature checks and chain watcher. Only the external Bitcoin network and display-rate service are simulated. It creates a new isolated database and synthetic accounts each time; it reads no deployment secrets and never contacts a Bitcoin node or BTCPay.

1. Start `.venv/Scripts/python.exe scripts/wallet_backend_preview.py`. It binds only `127.0.0.1:8418` and sets `LiveSettings(clan_wallets_enabled=True)`, equivalent to `CLANS_CLAN_WALLETS_ENABLED=true`. Local session/control details stay in ignored `.local/wallet-f8-session.json` and are never printed.
2. In another PowerShell terminal, set `$env:CLANS_DEV_API_TARGET='http://127.0.0.1:8418'`, then run `npm.cmd --prefix frontend run dev -- --port 5183`. The dev-only proxy override leaves the default target unchanged. The key-store dependency is prebundled so its first unlock does not reload the development page.
3. Open a Playwright CLI session named `clans-wallet` on `http://localhost:5183` and run `.venv/Scripts/python.exe scripts/run_wallet_browser.py scripts/wallet_backend_browser.js .local/wallet-f8-live-checks.json .local/wallet-f8-session.json`.
4. For the isolated failure fixtures, run Vite on port 5182 and run `.venv/Scripts/python.exe scripts/check_wallet_browser.py`. Keep browser scripts serial because they use one browser session. No backup words or PIN fields are included in screenshots or printed results.

The real API check covers contributions at zero/two/three confirmations, ledger crediting, dropped payments, reused addresses, the main funding address, read-only quotes, real 503 retry, address changes, preserving an existing signature, phone signing, oversight approval, broadcast/confirmation, higher-fee versions with fresh signatures, and partial/full repayment. The worker broadcasts only into the synthetic network.

Visual checks use 320/390/430/768/1366 widths in both themes. Live receipt, quote, signing and higher-fee captures at 390×844 are under `output/playwright/clan-wallet-live-{received,quote,signing,higher-fee}-{dark,light}.png`. Quote, receipt and higher-fee captures in both themes and the light signing capture were opened and reviewed. Fixed an old “Ready for an invoice” heading on Bitcoin grants and a receipt caption sitting beside the currency estimate. No outstanding P0/P1/P2 findings.

Validation against `a613dae`: production build passed; interoperability, encrypted-store and wallet-payment tests: **21 passed**. The real backend browser run passed **58 checks**, including higher-fee signing and partial/full repayment. The seven isolated browser suites passed **183 checks** (11 setup, 21 comparison, 50 status, 37 payout/quote, 37 deposit/restore, 8 routing, 19 F8 failure cases). Production assets exclude the preview, test receipts, test store and local control routes. Ruff and whitespace checks passed. Live browser requests contained neither the restored backup words nor the PIN.

The earlier F0–F7 wallet-maths/key-store boundaries remain: no edits to `vault/policy.ts`, `vault/sign.ts`, `vault/keys.ts`, encryption, production backend routes or the public custody page. No new dependencies. This is test-network integration, with no mainnet transactions or production deployment.

## F9: public wallet backup, 5 November 2026

Based on `02a0d92` on `feat/multisig-treasury`, after F8 was merged. Branch: `feat/clan-wallet-screens-f9`.

Active-wallet signatories who have compared the code on this phone can open **Save wallet backup** on the clan wallet card. The phone builds the JSON from its stored, checked public policy. It recomputes the code, majority and both checksummed descriptors with the existing wallet helpers, preserving key order. It takes no backup file from the server, does not unlock the key and sends no request when exporting.

The file uses the real clan name, with filename path/control characters removed. The screen explains why words alone are insufficient and that the recovery wait still applies. A download attempt does not clear the reminder: the user checks Downloads/Files and selects **I've saved the file**. That acknowledgement is stored locally against the exact public backup, including clan and generation. Another wallet generation needs another backup. Blocked storage and failed download startup have retry instructions; they do not claim the file was saved.

The browser script writes its actual synthetic download to `.local/wallet-f9-backup.json`. Run the checks serially with the existing Vite preview on port 5182 and Playwright CLI session `clans-wallet`:

```powershell
.venv/Scripts/python.exe scripts/run_wallet_browser.py scripts/wallet_backup_browser.js .local/wallet-f9-checks.json
.venv/Scripts/python.exe scripts/check_wallet_backup.py
.venv/Scripts/python.exe -m pytest backend/tests/test_clan_wallet_interop.py backend/tests/test_recover.py -o addopts= -q
```

The downloaded file equals the independent backend fixture field for field and passes `python -m clans.recover check`. The focused browser run passed **58 checks**: download/acknowledgement, retry, checked-policy/key-order boundaries, no export requests, generation changes, and both themes at 320/390/430/768/1366 widths. Invalid comparison state, changed policies, ordinary members and inactive/disabled wallets cannot export. The interoperability and recovery tests passed **18 tests**. Production build passed.

The full serial browser suite passed **241 checks** (the earlier 183 plus 58 backup checks). Production assets exclude development previews, fixtures, the test store and local control routes. Ruff and whitespace checks passed.

Screenshots at 390×844: `output/playwright/clan-wallet-backup-{dark,light}.png`, `clan-wallet-backup-downloaded-{dark,light}.png` and `clan-wallet-backup-saved-{dark,light}.png`. All six were opened and reviewed; no outstanding P0/P1/P2 layout findings. No words or PIN fields were captured. Native phone download handling still needs physical-device checking; the app asks the user to confirm that the file was saved rather than assuming a browser click completed a download.

No new dependencies, wallet maths, encryption, production backend or public custody changes. No real funds, main merge or deployment.

## F10: new wallet generation, moves and refreshes, 5 November 2026

Branch `feat/clan-wallet-screens-f10`, merged with `feat/multisig-treasury` after F9 (clan wallet signing doesn't depend on Lightning's switches).

- Wallet checks are stored per clan and generation (`clans-public-wallet-check-v2:<clan>:<generation>`). Old `v1` records read as the generation they name. No record is deleted; restoring a key marks only that generation for a fresh comparison.
- Signatories can start a new wallet with a reason, reuse their current key, compare the new code against `next.policy`, or stop the setup. After the switch the card shows each old wallet's balance still to move and asks for the new backup while keeping the old one.
- Moves and refreshes are reviewed in `wallet-review.ts` with `reviewSweep()` and signed with `signSweep()`, using only this phone's saved checks for `generation` and `destination.generation` and the server's `destination.index`. `destination.address` is never used. Amount and fee come from the review.

Checks:

```powershell
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run check:sweeps      # 24 fixture checks with reviewSweep()/signSweep()
.venv/Scripts/python.exe scripts/check_wallet_browser.py   # includes wallet_f10_browser.js (46 checks)
```

Screenshots at 390×844: `output/playwright/clan-wallet-{next,move,refresh}-{dark,light}.png`.
