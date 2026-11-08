"""A trial with real bitcoin, run on this PC: the whole clan wallet flow, end to end.

    python scripts/mainnet_trial.py laptop     # set up the oversight laptop (its own profile)
    python scripts/mainnet_trial.py serve      # the Clans app and chain watcher, on mainnet
    python scripts/mainnet_trial.py <step>     # see STEPS; each picks up where it left off

Everything is local: the app on http://localhost:8420 with PostgreSQL in Docker, the chain
watcher on a public Esplora server, the oversight app in a throwaway Windows profile, and members as
browsers with virtual passkeys. Nothing on the pilot or production servers is touched.

The trial folder (.local/mainnet-trial, ignored by Git) holds every key's backup words in
plain text, so the money can always be recovered (python -m clans.recover). Keep amounts
small, and delete the folder once the money has been sent back.
"""

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "scripts")]

TRIAL = ROOT / ".local" / "mainnet-trial"
STATE = TRIAL / "state.json"
PORT = 8420
ORIGIN = f"http://localhost:{PORT}"
ESPLORA = os.environ.get("TRIAL_ESPLORA", "https://blockstream.info/api")
PROFILE = TRIAL / "laptop-profile"
HOME = PROFILE / "AppData" / "Local" / "AfribitOversight"
PASSPHRASE_FILE = TRIAL / "laptop-passphrase.txt"


def step(text: str) -> None:
    print(f"\n=== {text}", flush=True)


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save(state: dict) -> None:
    TRIAL.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def keep_secret(name: str, text: str) -> Path:
    """Backup words and passphrases, saved so the trial's money is never stuck."""
    path = TRIAL / "secrets" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


# ---------- the oversight laptop ----------


def laptop_console(log_name: str):
    from e2e_oversight import Console, laptop_env

    env = laptop_env(PROFILE)
    env["PYTHONPATH"] = str(ROOT / "backend" / "src")
    command = [sys.executable, "-m", "clans.oversight", "--url", ORIGIN]
    return Console(command, env, TRIAL / log_name)


def laptop() -> None:
    state = load()
    if (HOME / "oversight-key.json").exists():
        print("The laptop is already set up.")
        return
    passphrase = "trial " + secrets.token_urlsafe(18)
    keep_secret("laptop-passphrase.txt", passphrase)
    step("Oversight laptop: first start")
    app = laptop_console("laptop-setup.log")
    app.expect("Press Enter to create your key.")
    app.expect("(If you already have 12 backup words")
    app.type("")
    app.expect("Passphrase:")
    app.type(passphrase)
    app.expect("Type it again:")
    app.type(passphrase)
    app.expect("YOUR 12 BACKUP WORDS", timeout=120)
    screen = app.expect("Press Enter once they're written down.")
    words = {int(n): word for n, word in re.findall(r"(\d+)\. ([a-z]+)", screen)}
    assert sorted(words) == list(range(1, 13)), "Couldn't read the words"
    keep_secret("laptop-words.txt", " ".join(words[n] for n in range(1, 13)))
    app.type("")
    for _ in range(2):
        app.expect("Word number ")
        app.type(words[int(app.expect(":"))])
    app.expect("That's right.")
    app.expect("Press Enter once you've sent it.")
    sent = (PROFILE / "Desktop" / "Send to the Clans administrator.txt").read_text("utf-8")
    print(sent)
    state["oversight_key"] = re.search(r"Mainnet oversight public key: (\S+)", sent).group(1)
    state["token_hash"] = re.search(r"Connection line: (\S+)", sent).group(1)
    save(state)
    app.type("")
    app.expect("Type a number, or press Enter for 1:", timeout=60)
    app.process.terminate(force=True)
    print("Saved the mainnet oversight key and connection line for the server settings.")


# ---------- the server ----------


def server_env(state: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLANS_")}
    env.update(
        PYTHONPATH=str(ROOT / "backend" / "src"),
        CLANS_ENVIRONMENT="test",
        # A local PostgreSQL in Docker, like production:
        #   docker run -d --name mainnet-trial-db -e POSTGRES_PASSWORD=trial-local-only
        #     -e POSTGRES_USER=clans -e POSTGRES_DB=clans -p 127.0.0.1:5442:5432
        #     -v mainnet-trial-db:/var/lib/postgresql/data postgres:16
        CLANS_DATABASE_URL="postgresql+psycopg://clans:trial-local-only@127.0.0.1:5442/clans",
        CLANS_SESSION_SECRET=state["session_secret"],
        CLANS_PUBLIC_ORIGIN=ORIGIN,
        CLANS_RP_ID="localhost",
        CLANS_STATIC_DIRECTORY=str(ROOT / "frontend" / "dist"),
        CLANS_RECEIVING_ENABLED="false",
        CLANS_PAYOUTS_ENABLED="false",
        CLANS_PROVIDER_NAMESPACE="clans-mainnet-trial",
        CLANS_CLAN_WALLETS_ENABLED="true",
        CLANS_CLAN_WALLET_NETWORK="bitcoin",
        CLANS_CLAN_WALLET_OVERSIGHT_KEYS=state["oversight_key"],
        CLANS_CLAN_WALLET_OVERSIGHT_TOKEN_HASHES=state["token_hash"],
        CLANS_CLAN_WALLET_RECOVERY_BLOCKS="4320",
        CLANS_CLAN_WALLET_CONFIRMATIONS="1",
        # mempool.space was unreachable from this PC on the trial day.
        CLANS_CLAN_WALLET_ESPLORA_URL=ESPLORA,
    )
    return env


def serve() -> None:
    state = load()
    if "oversight_key" not in state:
        raise SystemExit("Set up the laptop first: python scripts/mainnet_trial.py laptop")
    state.setdefault("session_secret", secrets.token_urlsafe(64))
    save(state)
    env = server_env(state)
    backend = ROOT / "backend"
    subprocess.run([sys.executable, "-m", "clans.migrate"], env=env, cwd=backend, check=True)
    web = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "clans.live_app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--log-level",
            "warning",
        ],
        env=env,
        cwd=backend,
    )
    watcher = subprocess.Popen(
        [sys.executable, "-u", "-m", "clans.chain_watcher"], env=env, cwd=backend
    )
    print(f"Clans on {ORIGIN} (mainnet), chain watcher on {ESPLORA}", flush=True)
    try:
        while web.poll() is None and watcher.poll() is None:
            time.sleep(1)
    finally:
        for process in (web, watcher):
            process.terminate()
    raise SystemExit("The app or the chain watcher stopped")


# ---------- members, in browsers ----------

CLAN = "Kibera Real Sats"
# Amina organizes; all three are signatories (2 of 3 sign each payout).
MEMBERS = {
    "Amina Organizer": "amina_trial",
    "Juma Trader": "juma_trial",
    "Wanjiru Tailor": "wanjiru_trial",
}


_PLAYWRIGHT = None


class browsers:
    """Open the named members' browsers, and close them afterwards."""

    def __init__(self, *names: str):
        self.names = names

    def __enter__(self):
        global _PLAYWRIGHT
        from playwright.sync_api import sync_playwright
        from trial_members import Member

        if _PLAYWRIGHT is None:
            _PLAYWRIGHT = sync_playwright().start()
        self.open = [Member(_PLAYWRIGHT, TRIAL, ORIGIN, name) for name in self.names]
        return self.open if len(self.open) > 1 else self.open[0]

    def __exit__(self, kind, error, trace):
        for member in self.open:
            if kind:
                print(f"  {member.name}'s screen: {member.shot('failed')}")
            member.close()


def policy_of(view: dict):
    from clans.clan_wallet import ClanPolicy

    p = view["policy"]
    return ClanPolicy.create(
        network=p["network"],
        oversight=p["oversight"],
        signers=p["signers"],
        recovery_threshold=p["recovery_threshold"],
        recovery_blocks=p["recovery_blocks"],
    )


def members() -> None:
    state = load()
    names = list(MEMBERS)
    with browsers(names[0]) as owner:
        if "clan_id" not in state:
            step(f"{names[0]} signs up with a passkey and creates {CLAN}")
            owner.sign_up(MEMBERS[names[0]])
            state["clan_id"] = owner.create_clan(
                CLAN, "A savings clan testing grants with real bitcoin."
            )
            save(state)
            owner.shot("clan-created")
        for name in names[1:]:
            if name in state.get("joined", []):
                continue
            step(f"{name} is invited as a signatory, signs up and accepts")
            link = owner.invitation(signer=True)
            with browsers(name) as member:
                member.sign_up(MEMBERS[name], link)
                member.accept_invitation(CLAN)
                member.shot("joined")
            state.setdefault("joined", []).append(name)
            save(state)
    print(f"{CLAN} ({state['clan_id']}) has {len(MEMBERS)} members, all signatories.")


def keys() -> None:
    state = load()
    clan = state["clan_id"]
    codes = {}
    for name in MEMBERS:
        with browsers(name) as member:
            view = member.api(f"/clans/{clan}/wallet")["body"]
            if not view["me"]["key"]:
                step(f"{name} makes a signing key on their phone")
                member.create_signing_key()
    for name in MEMBERS:
        with browsers(name) as member:
            step(f"{name} compares the wallet code")
            codes[name] = member.compare_wallet_code()
            view = member.api(f"/clans/{clan}/wallet")["body"]
    assert len(set(codes.values())) == 1, f"The phones disagree: {codes}"
    (code,) = set(codes.values())
    policy = policy_of(view)
    assert policy.wallet_code() == code, "This PC computes a different wallet code"
    assert view["status"] == "active", view["status"]
    assert view["policy"]["oversight"] == [state["oversight_key"]]
    state["wallet_code"] = code
    save(state)
    print(f"Clan wallet active. All three phones and this PC agree on code {code}.")


def deposit() -> None:
    from clans.clan_wallet import ClanWallet

    state = load()
    amount = int(os.environ.get("TRIAL_DEPOSIT", "30000"))
    with browsers(list(MEMBERS)[0]) as owner:
        view = owner.api(f"/clans/{state['clan_id']}/wallet")["body"]
        address, qr = owner.funding_address(amount)
    expected = ClanWallet(policy_of(view)).address(0)
    assert address == expected, f"The phone showed {address}, this PC derives {expected}"
    state["funding_address"] = address
    save(state)
    step(f"Send {amount:,} sats to the clan wallet")
    print(f"Address: {address}")
    print(f"QR code: {qr}")
    print("This PC derived the same address from the three phone keys and the laptop key.")


OWNER, JUMA, WANJIRU = MEMBERS
GRANTS = {
    # Juma's grant is paid to his own wallet, then repaid from it.
    "kiosk": {
        "beneficiary": JUMA,
        "voters": [OWNER, WANJIRU],
        "purpose": "Stock for my kiosk: real sats trial",
        "local_amount": "250",
    },
    # Wanjiru's grant sends what's left back to the person who funded the trial.
    "return": {
        "beneficiary": WANJIRU,
        "voters": [OWNER, JUMA],
        "purpose": "Send the trial money back to its funder",
    },
}


def wait_for(what: str, check, every: int = 30, timeout: int = 4 * 3600):
    print(f"Waiting: {what}", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = check()
        if found:
            return found
        time.sleep(every)
    raise SystemExit(f"Gave up waiting: {what}")


def beneficiary_wallet():
    from trial_beneficiary import BeneficiaryWallet

    return BeneficiaryWallet(TRIAL / "secrets" / "beneficiary-words.txt", ESPLORA)


def funded() -> None:
    state = load()
    clan = state["clan_id"]
    seen = set()
    with browsers(OWNER) as owner:

        def check():
            route = f"/clans/{clan}/wallet/receipts?address={state['funding_address']}"
            receipts = owner.api(route)["body"] or []
            for r in receipts:
                if (r["txid"], r["status"]) not in seen:
                    seen.add((r["txid"], r["status"]))
                    print(f"  {r['amount_sats']:,} sats in {r['txid']}: {r['status']}", flush=True)
            return [r for r in receipts if r["status"] == "confirmed"]

        receipts = wait_for("the deposit to confirm", check)
        owner.home()
        owner.page.locator(".home-balance-number").first.wait_for()
        balance = owner.page.locator(".home-balance-number").first.inner_text()
        owner.shot("home-funded")
    state["deposit_sats"] = sum(r["amount_sats"] for r in receipts)
    state["deposit_txids"] = [r["txid"] for r in receipts]
    save(state)
    print(f"The clan's balance on Amina's home screen: {balance}")


def clan_balance(member) -> int:
    clan = member.api(f"/clans/{load()['clan_id']}")["body"]
    return int(clan["available_msat"]) // 1000


def grant(which: str) -> None:
    state = load()
    plan = GRANTS[which]
    record = state.setdefault("grants", {}).setdefault(which, {})
    clan = state["clan_id"]
    if "id" not in record:
        step(f"{plan['beneficiary']} asks the clan for a grant")
        with browsers(plan["beneficiary"]) as member:
            if "local_amount" in plan:
                record["id"] = member.request_grant(plan["local_amount"], plan["purpose"])
            else:
                # Everything left, less 1,000 sats kept as change for the network fee.
                amount = clan_balance(member) - 1_000
                sent = member.post(
                    f"/clans/{clan}/grants", {"purpose": plan["purpose"], "amount_sats": amount}
                )
                assert sent["status"] == 200, sent
                record["id"] = sent["body"]["grant_id"]
            member.shot(f"{which}-requested")
        save(state)
    for voter in plan["voters"]:
        if voter in record.get("votes", []):
            continue
        step(f"{voter} reviews and approves the request")
        with browsers(voter) as member:
            member.vote_approve(plan["purpose"])
        record.setdefault("votes", []).append(voter)
        save(state)
    with browsers(plan["beneficiary"]) as member:
        if not record.get("accepted"):
            step(f"{plan['beneficiary']} accepts the grant terms")
            member.accept_grant(plan["purpose"])
            record["accepted"] = True
            save(state)
        if "address" not in record:
            address = (
                beneficiary_wallet().address()
                if which == "kiosk"
                else os.environ.get("TRIAL_RETURN_ADDRESS", "")
            )
            assert address, "Set TRIAL_RETURN_ADDRESS to the funder's Bitcoin address"
            step(f"{plan['beneficiary']} gives a Bitcoin address: {address}")
            preview = member.give_address(plan["purpose"], address)
            record.update(address=address, amount_sats=preview["approved_sats"])
            print(
                f"  Approved {preview['approved_sats']:,} sats; estimated fee "
                f"{preview['estimated_fee_sats']:,}; receives about "
                f"{preview['estimated_received_sats']:,}"
            )
            save(state)


def payout_of(member, which: str) -> dict | None:
    state = load()
    record = state["grants"][which]
    found = member.api(f"/clans/{state['clan_id']}/wallet/payouts?grant_id={record['id']}")
    live = [p for p in found["body"] or [] if p["status"] not in ("expired", "replaced")]
    return live[0] if live else None


def sign(which: str) -> None:
    plan = GRANTS[which]
    with browsers(plan["voters"][0]) as member:
        payout = wait_for("the chain watcher to build the payout", lambda: payout_of(member, which))
    print(f"  Payout {payout['txid']}: fee {payout['fee_sats']:,} sats, {payout['status']}")
    for signer in plan["voters"]:
        if payout["status"] != "awaiting_signatures":
            break
        step(f"{signer} checks the payout on their phone and signs it")
        with browsers(signer) as member:
            text = member.sign_payout(plan["purpose"])
            payout = payout_of(member, which)
        print("  " + " | ".join(line for line in text.splitlines() if line.strip())[:400])
    print(f"Payout status: {payout['status']}")


def expect_any(app, wanted: list[str], timeout: float = 300) -> tuple[str, str]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        text = app.text()
        hits = [(text.find(w, app.seen), w) for w in wanted if text.find(w, app.seen) >= 0]
        if hits:
            at, which = min(hits)
            before = text[app.seen : at]
            app.seen = at + len(which)
            return which, before
        if not app.process.isalive():
            break
        time.sleep(0.2)
    raise RuntimeError("The laptop app stopped or stalled:\n" + app.text()[-2500:])


def approve(which: str) -> None:
    from clans import oversight as ov

    state = load()
    record = state["grants"][which]
    passphrase = (TRIAL / "secrets" / "laptop-passphrase.txt").read_text("utf-8").strip()
    start, end = ov.check_characters(record["address"])
    answers = {
        "Wallet code they read": state["wallet_code"],
        "Type the 12 characters they read:": f"{start} {end}",
        "Type the total approved sats": str(record["amount_sats"]),
        "Passphrase (hidden):": passphrase,
        "Press Enter to go on.": "",
    }
    menu = "Type a number, or press Enter for 1:"
    step("The oversight laptop goes through what's waiting")
    app = laptop_console(f"laptop-approve-{which}.log")
    approved = False
    try:
        for _ in range(40):
            found, before = expect_any(app, [*answers, menu, "Approved and sent."])
            if found == "Approved and sent.":
                approved = True
            elif found == menu:
                if approved:
                    break
                if "Waiting for you:" not in before:
                    time.sleep(60)
                app.type("")
            else:
                if found == "Passphrase (hidden):":
                    print("  The laptop showed:\n" + before.strip()[-1800:])
                elif found == "Type the 12 characters they read:":
                    print(f"  The beneficiary reads {start} {end} from their own wallet.")
                elif found == "Wallet code they read":
                    print(f"  A signatory reads the wallet code {state['wallet_code']}.")
                app.type(answers[found])
    finally:
        app.process.terminate(force=True)
    assert approved, "The laptop didn't approve the payout"
    print("Approved on the laptop and sent to Clans.")


def sent(which: str) -> None:
    plan = GRANTS[which]
    record = load()["grants"][which]
    last = {}
    with browsers(plan["voters"][0]) as member:

        def check():
            payout = payout_of(member, which)
            status = (payout["status"], payout.get("confirmations"))
            if status != last.get("status"):
                last["status"] = status
                print(
                    f"  {payout['status']} · {payout.get('confirmations', 0)} confirmations"
                    f" · {payout.get('broadcast_txid') or payout['txid']}",
                    flush=True,
                )
            return payout if payout["status"] == "confirmed" else None

        payout = wait_for("the payout to confirm", check)
        member.open_grant(plan["purpose"])
        member.shot(f"{which}-paid")
    (line,) = [r for r in payout["recipients"] if r["grant_id"] == record["id"]]
    if which == "kiosk":
        got = beneficiary_wallet().sync()
        assert got == line["received_sats"], (got, line)
        print(f"Juma's own wallet received {got:,} sats; the fee was {payout['fee_sats']:,}.")
    else:
        print(
            f"Sent {line['received_sats']:,} sats to {record['address']};"
            f" fee {payout['fee_sats']:,}."
        )


def repay() -> None:
    from clans.clan_wallet import ClanWallet

    state = load()
    record = state["grants"]["kiosk"]
    clan = state["clan_id"]
    wallet = beneficiary_wallet()
    if "repayment_txid" not in record:
        have = wallet.sync()
        step(f"Juma repays from his own wallet ({have:,} sats there)")
        with browsers(JUMA) as juma:
            view = juma.api(f"/clans/{clan}/wallet")["body"]
            address = juma.repayment_address(GRANTS["kiosk"]["purpose"], have - 300)
        clan_wallet = ClanWallet(policy_of(view))
        assert address in {clan_wallet.address(i) for i in range(100)}, "Not the clan's address"
        record["repayment_address"] = address
        record["repayment_txid"] = wallet.send(address, None)
        save(state)
        print(f"  Sent everything in Juma's wallet to {address}: {record['repayment_txid']}")
    with browsers(JUMA) as juma:

        def check():
            route = f"/clans/{clan}/wallet/receipts?address={record['repayment_address']}"
            receipts = juma.api(route)["body"] or []
            return [r for r in receipts if r["status"] == "confirmed"]

        receipts = wait_for("the repayment to confirm", check)
        summary = juma.api(f"/clans/{clan}")["body"]
        juma.open_grant(GRANTS["kiosk"]["purpose"])
        juma.shot("kiosk-repaid")
    print(f"Repaid {sum(r['amount_sats'] for r in receipts):,} sats.")
    (g,) = [g for g in summary["grants"] if g["id"] == record["id"]]
    outstanding = int(g["outstanding_msat"]) // 1000
    print(f"Grant status {g['status']}, still owed {outstanding:,} sats")


def activity() -> None:
    for name in MEMBERS:
        with browsers(name) as member:
            member.home()
            member.shot("home")
            member.tab("Activity")
            member.page.wait_for_timeout(1500)
            member.shot("activity")
    print(f"Screens saved in {TRIAL / 'screens'}")


STEPS = {
    "laptop": laptop,
    "serve": serve,
    "members": members,
    "keys": keys,
    "deposit": deposit,
    "funded": funded,
    "grant": grant,
    "sign": sign,
    "approve": approve,
    "sent": sent,
    "repay": repay,
    "activity": activity,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in STEPS:
        print(__doc__)
        print("Steps:", ", ".join(STEPS), "(grant, sign, approve and sent take kiosk or return)")
        return 2
    STEPS[sys.argv[1]](*sys.argv[2:])
    return 0


if __name__ == "__main__":
    threading.excepthook = lambda args: None
    sys.exit(main())
