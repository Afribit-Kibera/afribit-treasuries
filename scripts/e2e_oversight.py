"""End-to-end run of the oversight laptop app against a private signet. Windows only.

    python scripts/e2e_oversight.py --kit .local/afribit-oversight-<commit>.zip

What it does, with nothing faked on the money path:
  * a private signet: bitcoind and electrs in Docker (see --help for the names), where this
    script mines blocks and plays the outside world (Afribit's funding, the beneficiary);
  * the Clans server on http://localhost:8410, with its chain watcher on that electrs;
  * three signatories who sign with the same algorithm the phones use;
  * the oversight laptop: the install kit, installed into a throwaway Windows profile and
    driven through a real Windows console, the way a person types into it.

The run sets up the laptop, creates and funds a clan wallet, passes a grant, signs it on
two phones, approves it on the laptop, and checks the beneficiary got the money on chain.
Without --kit it runs the app from this checkout instead of an installed kit.

Start the signet first (once):
    docker network create e2e-signet
    docker run -d --name e2e-bitcoind --network e2e-signet bitcoin/bitcoin:28.1 -signet \
        -signetchallenge=51 -txindex=1 -server=1 -rpcbind=0.0.0.0 -rpcallowip=0.0.0.0/0 \
        -rpcuser=e2e -rpcpassword=e2e -fallbackfee=0.0002 -listen=0 -printtoconsole=0
    docker run -d --name e2e-electrs --network e2e-signet -p 3002:3002 mempool/electrs \
        --network signet --daemon-rpc-addr e2e-bitcoind:38332 --cookie e2e:e2e \
        --jsonrpc-import --http-addr 0.0.0.0:3002 --db-dir /tmp/db --address-search
The script creates and funds the "miner" wallet itself.

Needs the dev requirements plus pywinpty (pip install pywinpty).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "backend" / "tests")]

ESPLORA = "http://localhost:3002"
SERVER = "http://localhost:8410"
PASSPHRASE = "pilot test passphrase one"
GRANT_SATS = 40_000


def step(text: str) -> None:
    print(f"\n=== {text}", flush=True)


# ---------- the private signet ----------


def cli(*args: str) -> str:
    command = [
        "docker",
        "exec",
        "e2e-bitcoind",
        "bitcoin-cli",
        "-signet",
        "-rpcuser=e2e",
        "-rpcpassword=e2e",
        *args,
    ]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"bitcoin-cli {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def miner(*args: str) -> str:
    return cli("-rpcwallet=miner", *args)


def esplora_height() -> int:
    with urllib.request.urlopen(ESPLORA + "/blocks/tip/height", timeout=10) as response:
        return int(response.read())


def mine(blocks: int) -> None:
    target = int(cli("getblockcount")) + blocks
    miner("generatetoaddress", str(blocks), miner("getnewaddress"), "1000000000")
    for _ in range(120):  # wait for electrs to catch up
        if esplora_height() >= target:
            return
        time.sleep(0.5)
    raise RuntimeError("electrs didn't catch up with the new blocks")


def wait_in_mempool(txid: str) -> None:
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{ESPLORA}/tx/{txid}", timeout=10):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"{txid} never reached electrs")


def ready_signet() -> None:
    if "miner" not in json.loads(cli("listwallets")):
        try:
            cli("loadwallet", "miner")
        except RuntimeError:
            cli("createwallet", "miner")
    if float(miner("getbalance")) < 1:
        mine(110)  # coinbase needs 100 confirmations


# ---------- the laptop's console ----------


ANSI = re.compile(r"\x1b\[(\d*)(?:;\d+)*([A-Za-z])|\x1b\][^\x07]*\x07|\x1b[=>()][0-9A-B]?")


def plain(raw: str) -> str:
    """Console output as text. ConPTY draws spaces and line breaks with escape codes."""

    def replace(match):
        count, code = match.group(1), match.group(2)
        if code in ("C", "X"):
            return " " * int(count or 1)
        if code in ("H", "E", "J"):
            return "\n"
        return ""

    return ANSI.sub(replace, raw).replace("\r", "")


class Console:
    """A real Windows console running the app, read and typed into like a person would."""

    def __init__(self, command: list[str], env: dict, log: Path):
        from winpty import PtyProcess

        self.process = PtyProcess.spawn(command, env=env, dimensions=(50, 110))
        self.raw, self.seen, self.log = "", 0, log
        self.lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            try:
                chunk = self.process.read(4096)
            except EOFError:
                return
            with self.lock:
                self.raw += chunk
            with self.log.open("a", encoding="utf-8") as out:
                out.write(chunk)

    def text(self) -> str:
        with self.lock:
            return plain(self.raw)

    def expect(self, wanted: str, timeout: float = 60) -> str:
        """Wait for text after what was already matched. Returns everything up to it."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self.text()
            at = text.find(wanted, self.seen)
            if at >= 0:
                before = text[self.seen : at]
                self.seen = at + len(wanted)
                return before
            if not self.process.isalive():
                break
            time.sleep(0.1)
        tail = self.text()[-2500:]
        raise RuntimeError(f"The app never showed {wanted!r}. Last screen:\n{tail}")

    def type(self, text: str) -> None:
        self.process.write(text + "\r")


# ---------- the run ----------


def install(kit: Path, profile: Path) -> Path:
    """Extract the kit and run its installer, as a person would, into a throwaway profile."""
    extracted = profile / "Downloads"
    with zipfile.ZipFile(kit) as archive:
        archive.extractall(extracted)
    env = laptop_env(profile, keep_path=True)
    installer = extracted / "Afribit Oversight" / "Install Afribit Oversight.cmd"
    done = subprocess.run(
        [os.environ["COMSPEC"], "/c", str(installer), "/noshortcut"],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    print(done.stdout.strip())
    if done.returncode:
        raise RuntimeError(f"The installer failed: {done.stderr.strip()}")
    return (
        profile / "AppData" / "Local" / "Programs" / "Afribit Oversight" / "python" / "python.exe"
    )


def laptop_env(profile: Path, keep_path: bool = False) -> dict:
    """A fresh Windows profile. The app runs without System32 on PATH, so its clipboard
    copy fails quietly and this PC's clipboard is left alone."""
    env = {key: value for key, value in os.environ.items() if key.upper() != "ONEDRIVE"}
    env.update(
        USERPROFILE=str(profile),
        LOCALAPPDATA=str(profile / "AppData" / "Local"),
        APPDATA=str(profile / "AppData" / "Roaming"),
    )
    if not keep_path:
        env["PATH"] = str(profile)
    (profile / "Desktop").mkdir(parents=True, exist_ok=True)
    (profile / "AppData" / "Local").mkdir(parents=True, exist_ok=True)
    return env


def run(args) -> None:
    import uvicorn
    from clan_wallet_helpers import secret_key, sign_normal_path
    from clans import oversight as ov
    from clans.chain_watcher import ChainWatcher
    from clans.clan_wallet import ClanPolicy
    from test_clan_wallet_api import make_app, phone_code, three_signer_clan

    work = Path(tempfile.mkdtemp(prefix="afribit-e2e-"))
    print(f"Working folder: {work}")
    profile = work / "laptop-profile"
    profile.mkdir()

    step("Private signet")
    ready_signet()
    print(f"Height {esplora_height()}, miner has {miner('getbalance')} sBTC")

    step("Clans server on " + SERVER)
    placeholder = str(secret_key(5).as_public())  # replaced by the laptop's key below
    app = make_app(
        work, [placeholder], clan_wallet_esplora_url=ESPLORA, clan_wallet_recovery_blocks=4_320
    )
    settings = app.state.security.settings
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8410, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.1)

    step("Oversight laptop: install and first start")
    if args.kit:
        python = install(Path(args.kit).resolve(), profile)
        command = [str(python), "-I", "-m", "clans.oversight", "--url", SERVER]
    else:
        command = [sys.executable, "-m", "clans.oversight", "--url", SERVER]
    env = laptop_env(profile)
    if not args.kit:
        env["PYTHONPATH"] = str(ROOT / "backend" / "src")
    home = profile / "AppData" / "Local" / "AfribitOversight"
    laptop = Console(command, env, work / "laptop-console.log")
    laptop.expect("Press Enter to create your key.")
    laptop.expect("(If you already have 12 backup words")
    laptop.type("")
    laptop.expect("Passphrase:")
    laptop.type(PASSPHRASE)
    laptop.expect("Type it again:")
    laptop.type(PASSPHRASE)
    laptop.expect("YOUR 12 BACKUP WORDS", timeout=120)
    screen = laptop.expect("Press Enter once they're written down.")
    words = {int(n): word for n, word in re.findall(r"(\d+)\. ([a-z]+)", screen)}
    assert sorted(words) == list(range(1, 13)), f"Couldn't read the words: {screen!r}"
    print("Read the 12 backup words off the screen.")
    laptop.type("")
    for _ in range(2):
        laptop.expect("Word number ")
        number = int(laptop.expect(":"))
        laptop.type(words[number])
    laptop.expect("That's right.")
    laptop.expect("Press Enter once you've sent it.")
    sent = (profile / "Desktop" / "Send to the Clans administrator.txt").read_text(encoding="utf-8")
    public = re.search(r"Oversight public key: (\S+)", sent).group(1)
    digest = re.search(r"Connection line: (\S+)", sent).group(1)
    print(f"Desktop file: key {public[:24]}..., connection line {digest[:12]}...")
    # What the administrator does with the file: add both lines to the server settings.
    settings.clan_wallet_oversight_keys = public
    settings.clan_wallet_oversight_token_hashes = digest
    laptop.type("")
    laptop.expect("Nothing is waiting for you.")
    laptop.expect("Type a number, or press Enter for 1:")

    step("Clan wallet: three signatories add keys and confirm the wallet code")
    cid, signers, _ = three_signer_clan(app)
    owner, second, third = signers
    phone_keys = {id(c): secret_key(seed) for c, seed in zip(signers, (2, 3, 4), strict=True)}
    route = f"/api/clans/{cid}/wallet"
    for client in signers:
        key = str(phone_keys[id(client)].as_public())
        assert client.post(route + "/keys", json={"key": key}).status_code == 200
    view = owner.get(route).json()
    code = phone_code(view)
    for client in signers:
        assert client.post(route + "/confirm", json={"wallet_code": code}).is_success
    view = owner.get(route).json()
    assert view["status"] == "active", view
    assert view["policy"]["oversight"] == [public], "The wallet didn't take the laptop's key"
    policy = ClanPolicy.create(
        network="signet",
        oversight=view["policy"]["oversight"],
        signers=view["policy"]["signers"],
        recovery_threshold=view["policy"]["recovery_threshold"],
        recovery_blocks=view["policy"]["recovery_blocks"],
    )
    assert policy.wallet_code() == code
    watcher = ChainWatcher(settings)

    def tick():
        watcher.tick()
        assert watcher.failures == {}, watcher.failures

    step("Afribit funds the clan wallet on chain")
    funding = owner.get(route + "/address?purpose=grant_funding").json()["address"]
    txid = miner("sendtoaddress", funding, "0.001")
    wait_in_mempool(txid)
    mine(3)
    tick()
    print(f"Funded {funding} with 100,000 sats in {txid}")

    step("The clan passes a grant, and two signatories sign the payout on their phones")
    response = owner.post(
        f"/api/clans/{cid}/grants",
        json={"purpose": "Stock for the shop", "amount_sats": GRANT_SATS},
        headers={"Idempotency-Key": os.urandom(16).hex()},
    )
    assert response.status_code == 200, response.text
    gid = response.json()["grant_id"]
    for voter in (second, third):
        vote = voter.post(f"/api/clans/{cid}/grants/{gid}/vote", json={"choice": "approve"})
        assert vote.status_code == 200, vote.text
    assert owner.post(f"/api/clans/{cid}/grants/{gid}/accept", json={}).status_code == 200
    beneficiary = miner("getnewaddress", "beneficiary", "bech32m")
    response = owner.post(
        f"/api/clans/{cid}/grants/{gid}/payout-address", json={"address": beneficiary}
    )
    assert response.status_code == 200, response.text
    tick()
    (payout,) = owner.get(route + "/payouts", params={"grant_id": gid}).json()
    for client in (second, third):
        signed = sign_normal_path(policy, phone_keys[id(client)], payout["psbt"])
        response = client.post(f"{route}/payouts/{payout['id']}/signature", json={"psbt": signed})
        assert response.status_code == 200, response.text
        payout = response.json()
    print(f"Payout {payout['txid']} has the clan's signatures; it waits for Afribit.")

    step("The oversight laptop goes through what's waiting")
    laptop.type("")  # Check again
    laptop.expect("Waiting for you:")
    laptop.expect("Type a number, or press Enter for 1:")
    laptop.type("")  # Go through it
    laptop.expect("Wallet code they read")
    laptop.type(code[:4] + " " + code[4:])  # read out by phone, with a pause
    laptop.expect("Registered.")
    start, end = ov.check_characters(beneficiary)
    laptop.expect("Type the 12 characters they read:")
    laptop.type(f"{start} {end}")
    laptop.expect("The address matches and is saved.")
    screen = laptop.expect("Passphrase (hidden):", timeout=120)
    assert f"{GRANT_SATS:,}" in screen, screen
    laptop.type(PASSPHRASE)
    laptop.expect("Approved and sent.", timeout=120)
    laptop.expect("Done: 1 of 1 payout(s) approved.")
    laptop.expect("Type a number, or press Enter for 1:")

    step("Clans broadcasts it, and the network confirms it")
    tick()
    wait_in_mempool(payout["txid"])
    mine(3)
    tick()
    got = float(miner("getreceivedbyaddress", beneficiary, "1"))
    # The beneficiary pays the network fee, as the laptop showed before approving.
    assert round(got * 100_000_000) == GRANT_SATS - payout["fee_sats"], got
    (done,) = owner.get(route + "/payouts", params={"grant_id": gid}).json() or [None]
    print(f"The beneficiary received {round(got * 1e8):,} sats in {payout['txid']}.")
    print(f"Payout status on Clans: {done and done.get('status')}")

    step("Clan address for Afribit funding, from the laptop's own records")
    laptop.type("2")
    screen = laptop.expect("Press Enter to go on.")
    assert funding in screen.replace("\n", ""), screen
    print("The laptop shows the same funding address the clan sees.")
    laptop.type("")
    laptop.expect("Type a number, or press Enter for 1:")
    laptop.type("6")
    for _ in range(50):
        if not laptop.process.isalive():
            break
        time.sleep(0.1)
    assert not laptop.process.isalive(), "The app didn't close"
    register = json.loads((home / ov.REGISTER_FILE).read_text(encoding="utf-8"))
    assert register["payouts"][-1]["txid"] == payout["txid"]

    server.should_exit = True
    watcher.security.engine.dispose()
    app.state.security.engine.dispose()
    step("PASSED: install, setup, wallet code, address check, approval, payment on chain")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--kit", help="the oversight kit zip to install and test")
    parser.add_argument("--keep", action="store_true", help="keep the working folder")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This drives a Windows console. Run it on Windows.")
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
