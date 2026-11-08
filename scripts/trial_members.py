"""Clan members for the mainnet trial: real browsers, each with its own profile and passkey.

Each member is a Chromium profile in the trial folder, so their session, signing-key vault and
saved wallet checks survive between steps, as on a phone. The virtual passkey is exported to
the trial folder after sign-up and added back each time the browser opens.
"""

import json
import os
import re
import time
from pathlib import Path

PIN = "482916"
VIEWPORT = {"width": 390, "height": 844}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class Member:
    def __init__(self, playwright, trial: Path, origin: str, name: str):
        self.name, self.trial, self.origin = name, trial, origin
        self.key = slug(name)
        self.errors: list[str] = []
        self.shots = trial / "screens"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.context = playwright.chromium.launch_persistent_context(
            str(trial / "members" / self.key),
            headless=os.environ.get("TRIAL_HEADED") != "1",
            viewport=VIEWPORT,
            accept_downloads=True,
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(45_000)
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.cdp = self.context.new_cdp_session(self.page)
        self.cdp.send("WebAuthn.enable")
        self.authenticator = self.cdp.send(
            "WebAuthn.addVirtualAuthenticator",
            {
                "options": {
                    "protocol": "ctap2",
                    "transport": "internal",
                    "hasResidentKey": True,
                    "hasUserVerification": True,
                    "isUserVerified": True,
                    "automaticPresenceSimulation": True,
                }
            },
        )["authenticatorId"]
        for credential in self._saved_passkeys():
            self.cdp.send(
                "WebAuthn.addCredential",
                {"authenticatorId": self.authenticator, "credential": credential},
            )

    # ---------- helpers ----------

    @property
    def _passkey_file(self) -> Path:
        return self.trial / "secrets" / f"{self.key}-passkey.json"

    def _saved_passkeys(self) -> list:
        path = self._passkey_file
        return json.loads(path.read_text("utf-8")) if path.exists() else []

    def save_passkeys(self) -> None:
        found = self.cdp.send("WebAuthn.getCredentials", {"authenticatorId": self.authenticator})
        self._passkey_file.parent.mkdir(parents=True, exist_ok=True)
        self._passkey_file.write_text(json.dumps(found["credentials"]), "utf-8")

    def button(self, name: str, exact: bool = True):
        return self.page.get_by_role("button", name=name, exact=exact)

    def shot(self, label: str) -> Path:
        path = self.shots / f"{self.key}-{label}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return path

    def close(self) -> None:
        if self.errors:
            print(f"  ({self.name}: browser errors {self.errors[:3]})")
        self.context.close()

    def api(self, path: str):
        """Read the app's own API with this member's session, as the app does."""
        if not self.page.url.startswith(self.origin):
            self.home()
        return self.page.evaluate(
            """async (path) => {
                const r = await fetch('/api' + path, {credentials: 'same-origin'});
                return {status: r.status, body: await r.json().catch(() => null)};
            }""",
            path,
        )

    def post(self, path: str, body: dict) -> dict:
        """Send to the app's API the way the app does: session cookie, CSRF and a fresh
        idempotency key."""
        if not self.page.url.startswith(self.origin):
            self.home()
        return self.page.evaluate(
            """async ([path, body]) => {
                const session = await (await fetch('/api/session')).json();
                const r = await fetch('/api' + path, {
                    method: 'POST', credentials: 'same-origin', body: JSON.stringify(body),
                    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf,
                              'Idempotency-Key': crypto.randomUUID()}});
                return {status: r.status, body: await r.json().catch(() => null)};
            }""",
            [path, body],
        )

    def home(self) -> None:
        self.page.goto(self.origin)
        self.page.get_by_role("navigation", name="Main navigation").wait_for()

    def tab(self, name: str) -> None:
        self.page.get_by_role("navigation", name="Main navigation").get_by_role(
            "button", name=name, exact=True
        ).click()

    def close_sheet(self) -> None:
        dialog = self.page.get_by_role("dialog")
        if dialog.count():
            dialog.get_by_role("button", name="Close dialog", exact=True).click()
            dialog.wait_for(state="hidden")

    # ---------- account ----------

    def sign_up(self, username: str, invitation: str | None = None) -> dict:
        p = self.page
        p.goto(invitation or self.origin)
        self.button("Create my account").click()
        p.get_by_role("textbox", name="Your name", exact=True).fill(self.name)
        p.get_by_role("textbox", name="Choose a username", exact=True).fill(username)
        # A placeholder number: this app runs only on this PC and sends no messages.
        p.locator('input[name="phone"]').fill(f"7123456{len(username) % 10}{ord(username[0]) % 10}")
        p.locator('input[name="terms"]').check()
        self.button("Continue to security").click()
        with p.expect_response(
            lambda r: r.url.endswith("/api/auth/register/verify") and r.request.method == "POST"
        ) as registered:
            self.button("Create my passkey").click()
        kit = registered.value.json()
        assert kit.get("recovery_codes"), f"{self.name}: no recovery words came back"
        (self.trial / "secrets").mkdir(parents=True, exist_ok=True)
        (self.trial / "secrets" / f"{self.key}-account.json").write_text(
            json.dumps({"handle": kit.get("handle"), "recovery_codes": kit["recovery_codes"]}),
            "utf-8",
        )
        self.save_passkeys()
        p.get_by_role("checkbox", name="I saved my username and 12 words.").check()
        self.button("Continue to invitation" if invitation else "Continue to my account").click()
        return kit

    def accept_invitation(self, clan_name: str) -> None:
        p = self.page
        p.get_by_role(
            "checkbox", name="I choose to join this clan and acknowledge the custody terms."
        ).check()
        signer = p.get_by_role("checkbox", name=re.compile("I accept the signatory responsibility"))
        if signer.count():
            signer.check()
        self.button("Accept invitation").click()
        p.get_by_role("heading", name=clan_name, exact=True).first.wait_for()

    def create_clan(self, name: str, purpose: str) -> str:
        p = self.page
        self.button("Create a clan").click()
        p.get_by_role("textbox", name="Clan name", exact=True).fill(name)
        p.get_by_role("textbox", name="What brings you together?").fill(purpose)
        self.button("Choose who approves", exact=False).click()
        p.get_by_role("combobox", name="Number of signatories").select_option("3")
        p.get_by_role("checkbox", name="I also choose to be one of the signatories.").check()
        p.get_by_role(
            "checkbox", name="I acknowledge these custody terms and will share them with members."
        ).check()
        with p.expect_response(
            lambda r: r.url.endswith("/api/clans") and r.request.method == "POST"
        ) as created:
            self.button(f"Create {name}", exact=False).click()
        body = created.value.json()
        p.get_by_role("heading", name=name, exact=True).first.wait_for()
        return body.get("id") or body.get("clan_id") or body["clan"]["id"]

    def invitation(self, signer: bool = True) -> str:
        p = self.page
        self.home()
        self.tab("Clan")
        p.get_by_role("button", name=re.compile(r"^Invite")).first.click()
        box = p.get_by_role("checkbox", name=re.compile("Offer a signatory role"))
        if signer:
            box.check()
        self.button("Create private invitation").click()
        field = p.get_by_role("textbox", name="Invitation link", exact=True)
        field.wait_for()
        link = field.input_value()
        self.close_sheet()
        return link

    # ---------- clan wallet ----------

    def wallet_card(self):
        self.home()
        self.tab("Clan")
        card = self.page.get_by_role("region", name="Clan wallet", exact=True)
        card.wait_for()
        return card

    def unlock(self) -> None:
        self.page.get_by_label("Your signing key PIN", exact=True).fill(PIN)
        self.button("Unlock signing key").click()

    def create_signing_key(self) -> str:
        """The phone makes 12 words; they're saved to the trial folder before anything else."""
        p = self.page
        card = self.wallet_card()
        card.get_by_role("button", name="Create my signing key", exact=True).click()
        sheet = p.get_by_role("dialog")
        sheet.get_by_role("button", name="Create my signing key", exact=True).click()
        items = p.locator(".wallet-words li").all_text_contents()
        words = [re.sub(r"^\s*\d+\s*", "", w).strip() for w in items]
        assert len(words) == 12, f"{self.name}: couldn't read the signing words"
        path = self.trial / "secrets" / f"{self.key}-signing-words.txt"
        path.write_text(" ".join(words) + "\n", "utf-8")
        self.button("I wrote them down").click()
        fields = p.locator(".sheet input")
        for i in range(fields.count()):
            label = fields.nth(i).locator("..").inner_text()
            fields.nth(i).fill(words[int(re.search(r"\d+", label).group()) - 1])
        self.button("Check my words").click()
        p.get_by_label("Choose a signing key PIN", exact=True).fill(PIN)
        p.get_by_label("Enter the PIN again", exact=True).fill(PIN)
        self.button("Protect with a PIN").click()
        self.button("Add my signing key").click()
        p.get_by_text("Key added", exact=True).first.wait_for()
        self.shot("key-added")
        self.close_sheet()
        return " ".join(words)

    def compare_wallet_code(self) -> str:
        p = self.page
        card = self.wallet_card()
        card.get_by_role("button", name="Compare wallet code", exact=True).click()
        self.unlock()
        code_box = p.get_by_label("Phone wallet code")
        code_box.wait_for()
        code = re.sub(r"\s", "", code_box.inner_text())
        self.shot("wallet-code")
        self.button("All codes match").click()
        p.get_by_role("dialog").wait_for(state="hidden")
        return code

    def funding_address(self, amount_sats: int) -> tuple[str, Path]:
        p = self.page
        self.home()
        p.get_by_role("button", name="Add money", exact=True).click()
        p.get_by_label("Payment for").select_option("grant_funding")
        p.get_by_label("Amount (sats)").fill(str(amount_sats))
        self.button("Get payment address").click()
        p.locator("img.deposit-qr").wait_for()
        address = p.locator(".wallet-address").first.inner_text().strip()
        qr = self.shots / "deposit-qr.png"
        p.locator(".qr-frame").screenshot(path=str(qr))
        self.shot("deposit")
        return address, qr

    # ---------- grants ----------

    def open_grant(self, purpose: str) -> None:
        """Every grant is listed on the Activity tab, under Grant requests."""
        p = self.page
        self.home()
        self.tab("Activity")
        p.get_by_text("Grant requests", exact=True).click()
        p.get_by_text("Recent grant requests", exact=True).click()
        card = p.locator(".grant-card:visible").filter(has_text=purpose).first
        card.get_by_role("button", name=re.compile("Review request")).click()
        p.get_by_role("dialog").wait_for()

    def request_grant(self, local_amount: str, purpose: str) -> str:
        p = self.page
        self.home()
        p.locator(".paw-receive").click()
        p.locator('input[name="amount"]').fill(local_amount)
        p.locator('textarea[name="purpose"]').fill(purpose)
        self.button("Check amount", exact=False).click()
        with p.expect_response(
            lambda r: re.search(r"/api/clans/[^/]+/grants$", r.url) and r.request.method == "POST"
        ) as sent:
            self.button("Send request", exact=False).click()
        return sent.value.json()["grant_id"]

    def vote_approve(self, purpose: str) -> None:
        self.open_grant(purpose)
        self.button("Approve request").click()
        self.page.get_by_text("Your vote is recorded.").wait_for()

    def accept_grant(self, purpose: str) -> None:
        self.open_grant(purpose)
        self.button("Accept grant terms").click()
        self.page.get_by_text("Terms accepted", exact=False).wait_for()

    def give_address(self, purpose: str, address: str) -> dict:
        p = self.page
        self.open_grant(purpose)
        p.get_by_label("Bitcoin address", exact=True).fill(address)
        self.button("Check receiving amount").click()
        self.button("Use this Bitcoin address").wait_for()
        self.shot("receiving-quote")
        with p.expect_response(lambda r: r.url.endswith("/payout-address")) as saved:
            self.button("Use this Bitcoin address").click()
        p.get_by_text("Address added.", exact=False).wait_for()
        return saved.value.json()

    def sign_payout(self, purpose: str) -> str:
        p = self.page
        self.open_grant(purpose)
        payout = p.get_by_role("region", name="Clan wallet payout")
        payout.get_by_text("Checked on this phone", exact=True).wait_for(timeout=90_000)
        self.shot("payout-review")
        count = re.compile(r"(\d+) of \d+ signatories")
        before = int(count.search(payout.inner_text()).group(1))
        self.button("Sign payout").click()
        self.unlock()
        deadline = time.time() + 90
        while time.time() < deadline:
            alert = p.get_by_role("alert")
            if alert.count() and alert.first.is_visible():
                self.shot("sign-refused")
                raise RuntimeError("The phone refused to sign: " + alert.first.inner_text())
            found = count.search(payout.inner_text())
            if found and int(found.group(1)) > before:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("The signature count never went up")
        text = payout.inner_text()
        self.close_sheet()
        return text

    def repayment_address(self, purpose: str, amount_sats: int) -> str:
        p = self.page
        self.open_grant(purpose)
        self.button("Repay this grant").click()
        p.get_by_label("Amount (sats)").fill(str(amount_sats))
        self.button("Get payment address").click()
        p.locator("img.deposit-qr").wait_for()
        self.shot("repayment")
        return p.locator(".wallet-address").first.inner_text().strip()
