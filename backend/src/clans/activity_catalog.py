"""What each activity event means, in words a member understands.

Every event the app records has a title, a category and a one-line explanation. The member
activity list shows the title; the detail page shows the explanation and a few safe facts.
Reports group events by category. Only the fields listed here ever leave the server: never
addresses, phone codes, request ids or anything else in the stored payload.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

CATEGORIES = ("clan", "members", "grants", "money", "wallet", "security", "account")


def sats(value) -> str:
    return f"{int(value):,} sats"


def msat(value) -> str:
    return sats(int(value) // 1000)


def kes(minor) -> str:
    """KES cents, as members read money: KES 1,234.50."""
    whole, cents = divmod(int(minor), 100)
    return f"KES {whole:,}.{cents:02d}"


def kes_rate(value) -> str:
    return f"KES {Decimal(str(value)).quantize(Decimal(1)):,} per bitcoin"


@dataclass(frozen=True)
class Kind:
    title: str
    category: str
    explain: Callable[[dict, str], str]
    # (payload key, label, formatter): the only facts shown on the detail page.
    facts: tuple = ()


def _same(text: str) -> Callable[[dict, str], str]:
    return lambda payload, actor: text.format(actor=actor)


AMOUNT = ("amount_sats", "Amount", sats)
AMOUNT_MSAT = ("amount_msat", "Amount", msat)
FEE = ("fee_sats", "Network fee", sats)
KEY = ("fingerprint", "Key fingerprint", str)
GENERATION = ("generation", "Wallet version", str)


def _key_added(payload, actor):
    if payload.get("replaced"):
        return f"{actor} replaced their signing key with a new one made on their phone."
    return (
        f"{actor} made a signing key on their phone and added it to the clan wallet. "
        "The wallet starts once every signatory has added a key and compared the wallet code."
    )


def _settled(payload, actor):
    amount = msat(payload.get("amount_msat", 0))
    if payload.get("credited_kes_minor") is not None and payload.get("kes_per_btc"):
        text = (
            f"A repayment of {amount} reached the clan wallet. At "
            f"{kes_rate(payload['kes_per_btc'])}, the rate when it was sent, it counted as "
            f"{kes(payload['credited_kes_minor'])} towards the grant."
        )
        if payload.get("surplus_kes_minor"):
            text += f" The extra {kes(payload['surplus_kes_minor'])} is kept as clan money."
        if payload.get("owed_after_kes_minor") == 0:
            text += " The grant is now fully repaid."
        else:
            text += f" {kes(payload.get('owed_after_kes_minor', 0))} is still owed."
        return text
    if payload.get("purpose") == "repayment" or int(payload.get("recovery_msat", 0) or 0):
        return f"A repayment of {amount} reached the clan wallet and was counted."
    return f"{amount} reached the clan wallet and was added to the clan's money."


def _disbursed(payload, actor):
    received = payload.get("received_sats")
    text = f"The grant payment of {msat(payload.get('amount_msat', 0))} confirmed on the network."
    if received is not None:
        text += f" The member received {sats(received)} after the network fee."
    if payload.get("debt_kes_minor"):
        text += f" They now owe the clan {kes(payload['debt_kes_minor'])}."
    return text


def _alarm(payload, actor):
    return (
        "The clan wallet's watcher saw something unexpected and raised an alarm. "
        "The community's oversight has been told. Check the wallet alarms for what to do."
    )


KINDS: dict[str, Kind] = {
    "clan_created": Kind(
        "Created the clan", "clan", _same("{actor} created the clan and became its organizer.")
    ),
    "invitation_created": Kind(
        "Invited a member",
        "members",
        lambda p, a: (
            f"{a} created a private invitation"
            + (" for a signatory." if p.get("is_signer") else " for a member.")
        ),
    ),
    "invitation_revoked": Kind(
        "Cancelled an invitation", "members", _same("{actor} cancelled an unused invitation.")
    ),
    "member_joined": Kind(
        "Joined the clan",
        "members",
        lambda p, a: (
            f"{a} accepted the invitation and joined the clan"
            + (" as a signatory." if p.get("accepted_signer") else ".")
        ),
    ),
    "grant_requested": Kind(
        "Asked for a grant",
        "grants",
        _same("{actor} asked the clan for a grant. Members vote on it next."),
        (AMOUNT,),
    ),
    "grant_vote_cast": Kind(
        "Voted on a grant", "grants", _same("{actor} voted on a grant request.")
    ),
    "grant_accepted": Kind(
        "Accepted the grant terms",
        "grants",
        _same("{actor} accepted the grant and its repayment terms."),
        (("principal_sats", "Grant", sats), ("principal_kes_minor", "To repay", kes)),
    ),
    "grant_cancelled": Kind(
        "Withdrew a grant request", "grants", _same("{actor} withdrew their grant request.")
    ),
    "payout_address_given": Kind(
        "Gave a receiving address",
        "grants",
        _same("{actor} gave the Bitcoin address from their own wallet where the grant is paid."),
        (AMOUNT,),
    ),
    "payout_address_changed": Kind(
        "Changed the receiving address",
        "grants",
        _same(
            "{actor} changed the address the grant is paid to. Signatories check the new "
            "payment again before signing."
        ),
    ),
    "payout_built": Kind(
        "Payment prepared",
        "money",
        _same(
            "Clans prepared the grant payment. Signatories now check it on their phones and sign."
        ),
        (FEE,),
    ),
    "payout_signed": Kind(
        "Signed a payment",
        "money",
        _same("{actor} checked the payment on their phone and signed it with their key."),
        (KEY,),
    ),
    "payout_oversight_signed": Kind(
        "Oversight approved a payment",
        "money",
        _same(
            "The community's oversight checked the payment on its laptop and approved it. "
            "The payment can now be sent."
        ),
    ),
    "payout_broadcast": Kind(
        "Payment sent",
        "money",
        _same("The signed payment was sent to the Bitcoin network. It confirms in a block."),
    ),
    "payout_fee_raised": Kind(
        "Higher-fee version prepared",
        "money",
        _same(
            "The payment was waiting too long, so Clans prepared the same payment with a higher "
            "network fee. Signatories sign it again."
        ),
        (FEE,),
    ),
    "grant_disbursed": Kind(
        "Grant paid",
        "money",
        _disbursed,
        (("received_sats", "Received", sats), ("debt_kes_minor", "To repay", kes)),
    ),
    "treasury_settled": Kind(
        "Money received",
        "money",
        _settled,
        (
            AMOUNT_MSAT,
            ("credited_kes_minor", "Counted towards the grant", kes),
            ("kes_per_btc", "Rate used", kes_rate),
            ("surplus_kes_minor", "Extra kept by the clan", kes),
            ("owed_after_kes_minor", "Still owed", kes),
        ),
    ),
    "deposit_requested": Kind(
        "Asked for a payment address",
        "money",
        _same("{actor} asked for an address to pay money into the clan wallet."),
        (AMOUNT,),
    ),
    "payment_prepared": Kind(
        "Payment prepared", "money", _same("Clans prepared a Lightning payment."), (AMOUNT_MSAT,)
    ),
    "payment_approved": Kind(
        "Approved a payment", "money", _same("{actor} approved a Lightning payment.")
    ),
    "wallet_key_registered": Kind("Added a signing key", "wallet", _key_added, (KEY,)),
    "wallet_confirmed": Kind(
        "Compared the wallet code",
        "wallet",
        _same(
            "{actor} compared the wallet code on their phone with the other signatories and it "
            "matched. This proves everyone's phone sees the same wallet."
        ),
        (("wallet_code", "Wallet code", str),),
    ),
    "wallet_code_mismatch": Kind(
        "Wallet code did not match",
        "security",
        _same(
            "A phone worked out a different wallet code from the one the server shows. "
            "Nobody should use the wallet until the community's oversight has checked it."
        ),
    ),
    "wallet_next_started": Kind(
        "Started a new wallet version",
        "wallet",
        _same(
            "{actor} started a new version of the clan wallet, for example after a signatory "
            "changed. Signatories add keys and compare its code again."
        ),
        (GENERATION,),
    ),
    "wallet_next_cancelled": Kind(
        "Cancelled the new wallet version",
        "wallet",
        _same("{actor} cancelled the new wallet version before it started."),
        (GENERATION,),
    ),
    "wallet_retired": Kind(
        "Old wallet version retired",
        "wallet",
        _same("The new wallet version is active. Money in the old one is moved across."),
        (GENERATION,),
    ),
    "wallet_move_built": Kind(
        "Wallet move prepared",
        "wallet",
        _same("Clans prepared the payment that moves money from the old wallet to the new one."),
        (FEE,),
    ),
    "wallet_moved": Kind(
        "Money moved to the new wallet",
        "wallet",
        _same("The money in the old wallet version reached the new one."),
    ),
    "wallet_refresh_built": Kind(
        "Wallet refresh prepared",
        "wallet",
        _same(
            "Clans prepared a refresh: the clan's money is paid back to itself so the backup "
            "recovery waiting period starts again."
        ),
        (FEE,),
    ),
    "wallet_refreshed": Kind(
        "Wallet refreshed",
        "wallet",
        _same("The refresh confirmed. The backup recovery waiting period started again."),
    ),
    "account_recovery_requested": Kind(
        "Asked to recover an account",
        "account",
        _same("{actor} asked for help getting back into their account."),
    ),
    "account_recovery_approved": Kind(
        "Approved an account recovery",
        "account",
        _same("{actor} approved a member's request to get back into their account."),
    ),
    "account_recovery_blocked": Kind(
        "Blocked an account recovery",
        "account",
        _same("{actor} blocked a request to get back into an account."),
    ),
    "account_access_restored": Kind(
        "Account access restored",
        "account",
        _same("{actor} got back into their account after the clan's approval."),
    ),
}

ALARM = Kind("Wallet alarm", "security", _alarm)
OTHER = Kind("Clan activity", "clan", _same("Something changed in the clan."))


def kind(event: str) -> Kind:
    if event.startswith("wallet_alarm_"):
        return ALARM
    return KINDS.get(event, OTHER)


def summary(event: str, payload: dict, actor: str) -> dict:
    """The list view of one event: what to call it and how to group it."""
    found = kind(event)
    return {
        "title": found.title,
        "category": found.category,
        "summary": found.explain(payload, actor),
    }


def details(event: str, payload: dict) -> list[dict]:
    """Safe facts for the detail page, in a fixed order."""
    out = []
    for key, label, show in kind(event).facts:
        if payload.get(key) not in (None, ""):
            out.append({"label": label, "value": show(payload[key])})
    return out


def links(payload: dict) -> dict:
    """Records the detail page can open: the grant, the payment and its transaction."""
    return {
        key: payload[key]
        for key in ("grant_id", "payout_id", "txid")
        if isinstance(payload.get(key), str) and payload[key]
    }
