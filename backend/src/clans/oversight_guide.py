"""The guided oversight app: one window that walks a person through every step.

Start it with no command (`python -m clans.oversight`, or the desktop shortcut from the
install kit). The first time, it creates the oversight key and connects to Clans. After that,
opening it goes straight through everything waiting: alarms first, then new clan wallets, new
beneficiary addresses and payouts. Each check that needs a phone call says who to call and
what to ask. Typing the passphrase is the approval; pressing Enter skips.

All the checks are the ones in clans.oversight. This module only asks the questions.
"""

import getpass
import hashlib
import json
import os
import secrets
import socket
import subprocess
from pathlib import Path

from clans import oversight as ov

ADMIN_FILE = "Send to the Clans administrator.txt"
RULE = "=" * 64


class Stop(Exception):
    """The person chose to stop this step. Nothing was signed."""


def say(text: str = "") -> None:
    print(text, flush=True)


def ask(prompt: str) -> str:
    return input(prompt).strip()


def heading(text: str) -> None:
    say(f"\n{RULE}\n  {text}\n{RULE}")


def pause() -> None:
    input("\nPress Enter to go on.")


def clear_screen() -> None:
    """Hide the backup words once they're written down."""
    os.system("cls" if os.name == "nt" else "clear")


def yes(prompt: str) -> bool:
    return ask(prompt + " Type yes or no: ").lower() in {"yes", "y"}


def choose(options: list[tuple[str, str]]) -> str:
    """Numbered options. Pressing Enter picks the first."""
    for number, (_, label) in enumerate(options, 1):
        say(f"  {number}. {label}" + ("   (press Enter)" if number == 1 else ""))
    while True:
        picked = ask("\nType a number, or press Enter for 1: ") or "1"
        if picked.isdigit() and 1 <= int(picked) <= len(options):
            return options[int(picked) - 1][0]
        say(f"Type a number from 1 to {len(options)}.")


def desktop() -> Path:
    """Where the file for the administrator goes, so it's easy to find and send."""
    for base in (os.environ.get("OneDrive"), os.environ.get("USERPROFILE"), str(Path.home())):
        if base and (Path(base) / "Desktop").is_dir():
            return Path(base) / "Desktop"
    return Path.home()


def copy_to_clipboard(text: str) -> bool:
    if os.name != "nt":
        return False
    try:
        subprocess.run(["clip"], input=text.encode("utf-16"), check=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ---------- what the administrator needs ----------


def token_hash(home: Path) -> str | None:
    path = home / ov.SERVER_FILE
    if not path.exists():
        return None
    token = json.loads(path.read_text(encoding="utf-8"))["token"]
    return hashlib.sha256(token.encode()).hexdigest()


def admin_text(home: Path) -> str:
    """The two public lines Clans needs from this laptop. Neither one is a secret."""
    lines = [f"Oversight laptop: {socket.gethostname()}"]
    if (home / ov.KEY_FILE).exists():
        lines.append(f"Oversight public key: {ov.public_key(home)}")
        if "mainnet_public_key" in ov._key_file(home):
            lines.append(f"Mainnet oversight public key: {ov.public_key(home, 'bitcoin')}")
    digest = token_hash(home)
    if digest:
        lines.append(f"Connection line: {digest}")
    lines.append("These lines are safe to send. They hold no secret and can't approve anything.")
    return "\n".join(lines) + "\n"


def hand_to_admin(home: Path) -> None:
    text = admin_text(home)
    path = desktop() / ADMIN_FILE
    path.write_text(text, encoding="utf-8")
    copied = copy_to_clipboard(text)
    say("\nSend this to the Clans administrator:\n")
    say(text)
    say(f"It's saved on your desktop as '{ADMIN_FILE}'.")
    if copied:
        say("It's also copied, so you can paste it straight into a message.")


# ---------- first-time setup ----------


def new_passphrase() -> str:
    say(f"\nChoose a passphrase of at least {ov.MIN_PASSPHRASE} characters. Four or five")
    say("random words is a good choice. You'll type it each time you approve.")
    say("What you type stays hidden.")
    while True:
        first = getpass.getpass("\nPassphrase: ")
        if len(first) < ov.MIN_PASSPHRASE:
            say(f"That's {len(first)} characters. Use at least {ov.MIN_PASSPHRASE}.")
            continue
        if getpass.getpass("Type it again: ") != first:
            say("The two didn't match. Let's try again.")
            continue
        return first


def show_backup_words(words: str) -> None:
    """Show the words once, then check two of them were written down."""
    listed = words.split()
    while True:
        clear_screen()
        heading("YOUR 12 BACKUP WORDS")
        say("Write these on paper now, in order, with their numbers.\n")
        for row in range(4):
            say("   ".join(f"{n + 1:>2}. {listed[n]:<10}" for n in (row, row + 4, row + 8)))
        say("\nKeep the paper somewhere safe, away from this laptop.")
        say("Never photograph the words or type them anywhere else.")
        say("Anyone with them can approve payouts as you.")
        input("\nPress Enter once they're written down.")
        clear_screen()
        say("Let's check the paper. Look at your paper, not the screen.\n")
        picks = sorted(secrets.SystemRandom().sample(range(12), 2))
        if all(ask(f"Word number {n + 1}: ").lower() == listed[n] for n in picks):
            say("\nThat's right.")
            return
        say("\nThat doesn't match the words. Let's show them again.")
        pause()


def set_up_key(home: Path) -> None:
    heading("STEP 1 OF 2: YOUR OVERSIGHT KEY")
    say("Every clan payout needs the clan's signatories and one approval from your")
    say("community's oversight.")
    say("This key is your approval. It stays on this laptop, locked with your passphrase.")
    restore = (
        ask(
            "\nPress Enter to create your key.\n"
            "(If you already have 12 backup words for this key, type R and press Enter.) "
        ).lower()
        == "r"
    )
    words = None
    if restore:
        words = getpass.getpass("\nType your 12 backup words with spaces between (hidden): ")
    while True:
        try:
            words, _ = ov.create_key(home, new_passphrase(), words)
            break
        except ov.OversightError as exc:
            say(f"\n{exc}.")
            if restore:
                words = getpass.getpass("Type your 12 backup words again (hidden): ")
    if not restore:
        show_backup_words(words)
    say("\nYour oversight key is ready.")


def set_up_connection(home: Path, url: str | None) -> None:
    heading("STEP 2 OF 2: CONNECT TO CLANS")
    while True:
        answer = url or ask("Clans address, for example https://clans.example.org: ")
        try:
            ov.connect(home, answer)
            break
        except ov.OversightError as exc:
            say(f"{exc}.")
            url = None
    say(f"Connected to {json.loads((home / ov.SERVER_FILE).read_text())['url']}.")
    say("The laptop can see payouts that wait for you. It can't approve anything alone.")
    hand_to_admin(home)
    input("\nPress Enter once you've sent it.")


# ---------- the phone checks ----------


def register_wallet(home: Path, item: dict) -> bool:
    """Register one clan wallet after a signatory reads its code by phone."""
    name = item.get("clan_name") or f"clan {item['clan_id']}"
    heading(f"NEW CLAN WALLET: {name}")
    if item.get("generation", 1) > 1:
        say(f"The clan has moved to a new wallet (wallet {item['generation']}).")
    say("Phone one of the clan's signatories. Ask them to open Clans, go to the clan")
    say("wallet, and read you the 8-character wallet code.\n")
    for attempt in range(2):
        code = ask("Wallet code they read (or press Enter to do this later): ")
        if not code:
            say("Skipped. Payouts for this clan wait until its wallet is registered.")
            return False
        try:
            policy = ov.add_wallet(home, item["clan_id"], item, code)
        except ov.OversightError as exc:
            if attempt == 0 and "doesn't match" in str(exc):
                say("\nThat code doesn't match. Ask them to read it again, slowly.")
                continue
            say(f"\nNot registered: {exc}.")
            return False
        say(f"\nRegistered. {name} needs {policy.threshold} of {len(policy.signers)} signatories.")
        return True
    return False


def confirm_address(home: Path, name: str, address: str, network: str) -> bool:
    """Save a beneficiary's address after they read parts of it from their own wallet."""
    who = name or "the beneficiary"
    heading(f"NEW ADDRESS FOR {who}")
    say("This is the first payment to this address, so check it with them by phone.")
    say(f"Phone {who}. Ask them to open their own wallet app, find the address they")
    say("gave for this payment, and read you the 6 characters right after the start")
    say(f"({ov.fixed_start(address)}), then the last 6 characters.\n")
    while True:
        read = "".join(ask("Type the 12 characters they read: ").split())
        if len(read) == 2 * ov.CHECK_CHARACTERS:
            break
        say(f"That's {len(read)} characters. Type all 12: the first 6, then the last 6.")
    try:
        ov.confirm_address(home, address, name, read[:6], read[6:], network)
    except ov.OversightError as exc:
        say(f"\n{exc}.")
        return False
    say("The address matches and is saved.")
    return True


# ---------- payouts ----------


def approved_with_passphrase(home: Path, item: ov.Review) -> str | None:
    """The person's approval: the total for large payouts, then the passphrase. None skips."""
    if item.large:
        typed = ask(
            "\nThis is a large payout. Type the total approved sats, or press Enter to skip: "
        )
        if not typed:
            return None
        if typed.replace(",", "").replace(" ", "") != str(item.total_sats):
            say("That isn't the total. Nothing was signed.")
            return None
    say("\nTo approve, type your passphrase and press Enter. To skip, just press Enter.")
    for _ in range(3):
        passphrase = getpass.getpass("Passphrase (hidden): ")
        if not passphrase:
            return None
        try:
            ov.unlock(home, passphrase)
            return passphrase
        except ov.OversightError:
            say("That passphrase is wrong. Try again, or press Enter to skip.")
    say("Wrong three times. Nothing was signed.")
    return None


def prepare(home: Path, client, payout: dict) -> ov.Review | None:
    """Do the phone checks a payout needs, then check it. None if it can't be approved."""
    clan_id = str(payout.get("clan_id", ""))
    saved = ov.load_register(home)["wallets"].get(clan_id)
    known = {item["generation"] for item in [saved, *saved.get("earlier", [])]} if saved else set()
    destination = payout.get("destination") or {}
    needed = {payout.get("generation"), destination.get("generation")} - {None}
    if not needed <= known:
        for item in ov.unregistered(home, client, clan_id):
            if not register_wallet(home, item):
                return None
        saved = ov.load_register(home)["wallets"].get(clan_id)
    if payout.get("kind", "grant") == "grant" and saved:
        network = saved["policy"]["network"]
        for line in payout.get("recipients", []):
            address = str(line.get("address", ""))
            if address and address not in ov.load_register(home)["addresses"]:
                if not confirm_address(home, str(line.get("name") or ""), address, network):
                    say("Don't approve this payout. Tell the clan and the team.")
                    return None
    try:
        return ov.review(home, payout)
    except ov.OversightError as exc:
        say(f"\nThis payout can't be approved: {exc}.")
        say("Nothing was signed. Don't work around this; check with the clan and the team.")
        return None


def show_alarms_first(home: Path, client) -> None:
    unread = ov.unread_alarms(home, client)
    if not unread:
        return
    heading(f"{len(unread)} NEW ALARM(S): READ THESE FIRST")
    ov._show_alarms(unread)
    if any(item["kind"] == "unapproved_spend" for item in unread):
        say("\n'unapproved_spend' means money left a clan wallet without going through Clans.")
        say("Someone may hold enough of that clan's keys. Don't approve anything for that")
        say("clan until the team has found out what happened.")
    if not yes("\nHave you read them, and is it safe to go on?"):
        raise Stop("You stopped at the alarms. They stay unread")
    ov.mark_alarms_read(home, unread)


def go_through_everything(home: Path) -> None:
    """Alarms, new clan wallets, then each waiting payout, one at a time."""
    with ov.server(home) as client:
        show_alarms_first(home, client)
        for item in ov.unregistered(home, client):
            register_wallet(home, item)
        waiting = ov.pending(client)
        signed = 0
        for number, payout in enumerate(waiting, 1):
            name = payout.get("clan_name") or f"clan {payout.get('clan_id')}"
            heading(f"PAYOUT {number} OF {len(waiting)}: {name}")
            item = prepare(home, client, payout)
            if item is None:
                continue
            ov._show(item, payout.get("clan_name"))
            if item.kind == "grant":
                say("\nCheck these details match what you know about this grant.")
            passphrase = approved_with_passphrase(home, item)
            if passphrase is None:
                say("Skipped. Nothing was signed.")
                continue
            try:
                signed_psbt, _ = ov.sign(home, payout, passphrase)
                result = ov.upload(client, ov.signed_file(payout, item, signed_psbt))
            except ov.OversightError as exc:
                say(f"\n{exc}.")
                continue
            finally:
                del passphrase
            got = result.get("signatures", {})
            say("\nApproved and sent. Clans sends the payment within a minute.")
            say(f"(Clan signatures: {got.get('count')} of {got.get('required')}.)")
            signed += 1
        if waiting:
            say(f"\nDone: {signed} of {len(waiting)} payout(s) approved.")


# ---------- the main window ----------


def overview(home: Path) -> tuple[str, bool, bool]:
    """A summary of what's waiting, whether Clans answered, and whether anything waits."""
    try:
        with ov.server(home) as client:
            waiting = ov.pending(client)
            unread = ov.unread_alarms(home, client)
            new_wallets = ov.unregistered(home, client)
            community = community_name(client)
    except ov.OversightError as exc:
        text = str(exc)
        if "(401)" in text or "(503)" in text:
            return (
                "Clans isn't ready for this laptop yet. If you haven't, send the administrator "
                f"the file '{ADMIN_FILE}' from your desktop. Then check again.",
                False,
                False,
            )
        return f"{text}.", False, False
    parts = [
        f"{len(unread)} new alarm(s)" if unread else "",
        f"{len(new_wallets)} clan wallet(s) to register" if new_wallets else "",
        f"{len(waiting)} payout(s) to approve" if waiting else "",
    ]
    found = [part for part in parts if part]
    whose = f"Oversight for {community}.\n" if community else ""
    if found:
        return whose + "Waiting for you: " + ", ".join(found) + ".", True, True
    return whose + "Nothing is waiting for you.", True, False


def community_name(client) -> str | None:
    """The community this laptop oversees. Older servers don't say; that's fine."""
    try:
        response = client.get("/api/oversight/community")
        return str(response.json()["name"]) if response.status_code == 200 else None
    except Exception:
        return None


def funding_address(home: Path) -> None:
    """The clan address the community sends grant funding to, from this laptop's records."""
    wallets = ov.load_register(home)["wallets"]
    if not wallets:
        say("\nNo clan wallet is registered on this laptop yet.")
        return
    clans = sorted(wallets.items(), key=lambda pair: pair[1].get("clan_name") or pair[0])
    heading("CLAN ADDRESS FOR AFRIBIT FUNDING")
    if len(clans) == 1:
        clan_id, saved = clans[0]
    else:
        clan_id = choose([(cid, saved.get("clan_name") or cid) for cid, saved in clans])
        saved = wallets[clan_id]
    address = ov.clan_address(home, clan_id)
    start, end = ov.check_characters(address)
    say(f"{saved.get('clan_name') or clan_id}:\n\n  {address}\n")
    say("Send the funding only to this address. On the sending wallet, check that")
    say(f"the 6 characters after {ov.fixed_start(address)} are {start}, and the last 6 are {end}.")
    if copy_to_clipboard(address):
        say("It's copied, so you can paste it into the sending wallet.")


def show_records(home: Path) -> None:
    register = ov.load_register(home)
    heading("THIS LAPTOP'S RECORDS")
    say("Clan wallets:")
    for clan_id, saved in register["wallets"].items():
        name = saved.get("clan_name") or f"clan {clan_id}"
        say(f"  {name}: wallet {saved['generation']}, code {saved['wallet_code']}")
    if not register["wallets"]:
        say("  none yet")
    say("Confirmed beneficiary addresses:")
    for address, saved in register["addresses"].items():
        say(f"  {saved['name']}: {address}")
    if not register["addresses"]:
        say("  none yet")
    say("Latest approvals:")
    for payout in register["payouts"][-10:]:
        say(f"  {payout['signed_at'][:16]}  {payout['total_sats']:,} sats")
    if not register["payouts"]:
        say("  none yet")
    settings = register["settings"]
    say(
        f"Limits: network fee {settings['max_fee_sats']:,} sats, moves "
        f"{settings['max_sweep_fee_sats']:,} sats, large payout {settings['large_payout_sats']:,}"
    )
    say(f"\nCopy {home / ov.REGISTER_FILE} to a USB stick now and then.")


def recent_alarms(home: Path) -> None:
    with ov.server(home) as client:
        found = ov.alarms(client)[:20]
    ov._show_alarms(found)
    say(f"\n{len(found)} recent alarm(s).")


def run(home: Path, url: str | None = None) -> int:
    try:
        with ov.only_one_app(home):
            return _run(home, url)
    except ov.OversightError as exc:
        say(f"\n{exc}.")
        try:
            pause()
        except (KeyboardInterrupt, EOFError):
            pass
        return 1


def _run(home: Path, url: str | None) -> int:
    heading("AFRIBIT OVERSIGHT")
    try:
        if not (home / ov.KEY_FILE).exists():
            set_up_key(home)
        if not (home / ov.SERVER_FILE).exists():
            set_up_connection(home, url)
        first = True
        while True:
            summary, answered, busy = overview(home)
            heading("AFRIBIT OVERSIGHT")
            say(summary)
            try:
                if busy and first:
                    # Opening the app goes straight to what's waiting.
                    go_through_everything(home)
                    first = False
                    continue
                first = False
                say("")
                picked = choose(
                    [
                        ("work" if busy else "check", "Go through it" if busy else "Check again"),
                        ("funding", "Clan address for funding"),
                        ("alarms", "Recent alarms"),
                        ("records", "This laptop's records"),
                        ("admin", "What to send the Clans administrator"),
                        ("close", "Close"),
                    ]
                )
                if picked == "close":
                    return 0
                if picked == "work":
                    go_through_everything(home)
                elif picked == "funding":
                    funding_address(home)
                    pause()
                elif picked == "alarms" and answered:
                    recent_alarms(home)
                    pause()
                elif picked == "records":
                    show_records(home)
                    pause()
                elif picked == "admin":
                    hand_to_admin(home)
                    pause()
            except Stop as exc:
                say(f"\n{exc}. Nothing was signed.")
                pause()
            except ov.OversightError as exc:
                say(f"\n{exc}.")
                pause()
            except Exception as exc:  # never close the window on a surprise
                say(f"\nSomething went wrong ({type(exc).__name__}: {exc}).")
                say("Nothing was signed unless it said 'Approved and sent'. Tell the team.")
                pause()
    except (KeyboardInterrupt, EOFError):
        say("\nClosed. Nothing was signed unless it said 'Approved and sent'.")
        return 1
