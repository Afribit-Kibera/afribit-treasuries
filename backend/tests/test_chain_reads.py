"""How often the chain watcher reads the block explorer, and moving between explorers."""

import time

import pytest
import test_clan_wallet_payments as payments
from clan_wallet_helpers import DESTINATION
from test_clan_wallet_api import make_app
from test_clan_wallet_payments import (
    FakeChain,
    accepted_grant,
    address,
    drafts,
    fund_clan,
    oversight_sign,
    sign,
)

from clans import chain_watcher
from clans.chain_watcher import ChainWatcher, EsploraChain, FailoverChain
from clans.explorers import explorer_urls
from clans.wallet_models import ChainStatus

# Shared fixtures: an active 3-signatory clan wallet and its test keys.
clan, keys = payments.clan, payments.keys


def counted(clan):
    chain, calls = clan["chain"], {"sync": 0, "fee": 0}
    sync, fee_rate = chain.sync, chain.fee_rate

    def counted_sync(wallet):
        calls["sync"] += 1
        sync(wallet)

    def counted_fee():
        calls["fee"] += 1
        return fee_rate()

    chain.sync, chain.fee_rate = counted_sync, counted_fee
    return calls


def receipts(clan):
    return clan["signers"][0].get(f"/api/clans/{clan['cid']}/wallet/receipts").json()


def test_a_quiet_wallet_is_read_on_new_blocks_changes_or_after_a_while(clan):
    watcher, chain, owner = clan["watcher"], clan["chain"], clan["signers"][0]
    calls = counted(clan)
    watcher.tick()
    watcher.tick()
    assert calls == {"sync": 1, "fee": 1}
    # A new address is handed out: read straight away.
    mine = address(owner, clan["cid"], "contribution")["address"]
    watcher.tick()
    assert calls["sync"] == 2
    # A payment with no new block waits for the next read.
    chain.pay(mine, 20_000)
    watcher.tick()
    assert calls["sync"] == 2 and receipts(clan) == []
    chain.tip += 1
    watcher.tick()
    assert calls["sync"] == 3 and len(receipts(clan)) == 1
    # Nothing new, but the idle wait has passed.
    (wallet_id,) = watcher.last_read
    tip, read_at, marks = watcher.last_read[wallet_id]
    idle = watcher.settings.clan_wallet_idle_read_seconds
    watcher.last_read[wallet_id] = (tip, read_at - idle, marks)
    watcher.tick()
    assert calls == {"sync": 4, "fee": 4}


def test_payouts_are_built_and_sent_without_waiting_for_a_block(clan):
    watcher, owner, second, third = clan["watcher"], *clan["signers"]
    fund_clan(clan, 100_000)
    gid = accepted_grant(clan)
    route = f"/api/clans/{clan['cid']}/grants/{gid}/payout-address"
    assert owner.post(route, json={"address": DESTINATION}).status_code == 200
    watcher.tick()
    (payout,) = drafts(owner, clan["cid"], grant_id=gid)
    view = sign(clan, second, payout).json()
    view = sign(clan, third, view).json()
    assert oversight_sign(clan, view).status_code == 200
    watcher.tick()
    assert clan["chain"].broadcasts == [payout["txid"]]
    assert watcher.failures == {}


def test_a_server_with_no_wallets_yet_still_records_a_fee_rate(tmp_path, keys):
    app = make_app(tmp_path, keys)
    watcher = ChainWatcher(app.state.security.settings, chain=FakeChain())
    try:
        watcher.tick()
        with watcher.security.db() as db:
            status = db.get(ChainStatus, "signet")
            assert (status.tip_height, status.fee_rate_sat_vb) == (100, 2)
    finally:
        watcher.security.engine.dispose()
        app.state.security.engine.dispose()


class Explorer:
    def __init__(self, tip):
        self.tip, self.up, self.calls = tip, True, 0

    def tip_height(self):
        self.calls += 1
        if not self.up:
            raise ConnectionError("down")
        return self.tip


def test_the_next_explorer_answers_when_one_fails_and_the_first_is_retried():
    own, public = Explorer(10), Explorer(11)
    chain = FailoverChain([own, public])
    own.up = False
    assert chain.tip_height() == 11
    own.up = True
    assert chain.tip_height() == 11 and own.calls == 1
    chain.moved_at -= FailoverChain.RETRY_FIRST_SECONDS + 1
    assert chain.tip_height() == 10
    own.up = public.up = False
    with pytest.raises(ConnectionError):
        chain.tip_height()


def test_an_explorer_that_hangs_is_passed_over(monkeypatch):
    monkeypatch.setattr(chain_watcher, "TIP_TIMEOUT_SECONDS", 0.1)
    hung = EsploraChain.__new__(EsploraChain)
    hung.read_tip = lambda: time.sleep(1) or 1
    assert FailoverChain([hung, Explorer(5)]).tip_height() == 5


def test_explorers_can_be_listed_or_left_to_the_public_ones():
    assert explorer_urls("signet") == [
        "https://mempool.space/signet/api",
        "https://blockstream.info/signet/api",
    ]
    assert explorer_urls(
        "bitcoin", " http://umbrel.local:3006/api/ , https://mempool.space/api"
    ) == [
        "http://umbrel.local:3006/api",
        "https://mempool.space/api",
    ]
    with pytest.raises(ValueError, match="Not a block explorer"):
        explorer_urls("bitcoin", "umbrel.local:3006")
