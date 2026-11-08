"""Recovery policy: every affected clan approves the same replacement key."""

import hashlib

from fastapi import HTTPException
from sqlalchemy import select
from webauthn import verify_authentication_response

from clans.live_models import Passkey
from clans.live_security import unb64
from clans.models import Membership, PolicyVersion, User, now_iso
from clans.money_service import intent_digest
from clans.recovery_models import AccessRecovery, AccessRecoveryApproval, Contact


def recovery_hold(db, user_id):
    return bool(
        db.scalar(
            select(AccessRecovery.id)
            .where(
                AccessRecovery.user_id == user_id,
                AccessRecovery.status == "waiting",
                AccessRecovery.expires_at > now_iso(),
            )
            .limit(1)
        )
    )


def snapshot(db, user_id):
    groups = []
    for member in db.scalars(
        select(Membership)
        .where(
            Membership.user_id == user_id,
            Membership.active.is_(True),
        )
        .order_by(Membership.clan_id)
    ).all():
        policy = db.scalar(
            select(PolicyVersion)
            .where(
                PolicyVersion.clan_id == member.clan_id,
            )
            .order_by(PolicyVersion.version.desc())
        )
        signers = sorted(
            db.scalars(
                select(Membership.user_id)
                .join(
                    User,
                    User.id == Membership.user_id,
                )
                .where(
                    Membership.clan_id == member.clan_id,
                    Membership.active.is_(True),
                    Membership.is_signer.is_(True),
                    Membership.user_id != user_id,
                    User.active.is_(True),
                )
            ).all()
        )
        if not policy or len(signers) < policy.signer_threshold:
            raise HTTPException(
                409,
                "A clan does not have enough other signatories. "
                "Use a recovery code or a spare passkey.",
            )
        groups.append(
            {
                "clan_id": member.clan_id,
                "membership_id": member.id,
                "role": member.role,
                "is_signer": member.is_signer,
                "policy_id": policy.id,
                "threshold": policy.signer_threshold,
                "signers": signers,
            }
        )
    if not groups:
        raise HTTPException(
            409,
            "Clan recovery needs an existing clan with enough signatories. "
            "Use a recovery code or a spare passkey.",
        )
    return groups


def active_key_ids(db, user_id):
    return sorted(
        db.scalars(
            select(Passkey.id).where(
                Passkey.user_id == user_id,
                Passkey.active.is_(True),
            )
        ).all()
    )


def bound_challenge(digest, nonce, clan_id):
    return hashlib.sha256(
        b"afribit-clans-access-v1:" + bytes.fromhex(digest) + nonce + clan_id.encode()
    ).digest()


def approval_members(db, row, group, settings, *, lock=False):
    valid = []
    for approval in db.scalars(
        select(AccessRecoveryApproval)
        .where(
            AccessRecoveryApproval.recovery_id == row.id,
            AccessRecoveryApproval.clan_id == group["clan_id"],
        )
        .order_by(AccessRecoveryApproval.user_id)
    ).all():
        if approval.user_id == row.user_id or approval.user_id not in group["signers"]:
            continue
        query = select(Passkey).where(Passkey.id == approval.passkey_id, Passkey.active.is_(True))
        key = db.scalar(query.with_for_update() if lock else query)
        user = db.get(User, approval.user_id)
        member = db.scalar(
            select(Membership).where(
                Membership.user_id == approval.user_id,
                Membership.clan_id == group["clan_id"],
                Membership.active.is_(True),
                Membership.is_signer.is_(True),
            )
        )
        if (
            not key
            or key.user_id != approval.user_id
            or not user
            or not user.active
            or not member
            or recovery_hold(db, approval.user_id)
        ):
            continue
        proof = approval.proof
        try:
            if proof["digest"] != row.digest or proof["public_key"] != key.public_key:
                continue
            result = verify_authentication_response(
                credential=proof["credential"],
                expected_challenge=bound_challenge(
                    row.digest, unb64(proof["nonce"]), group["clan_id"]
                ),
                expected_rp_id=settings.rp_id,
                expected_origin=settings.public_origin,
                credential_public_key=unb64(key.public_key),
                credential_current_sign_count=proof["counter_before"],
                require_user_verification=True,
            )
            if (
                result.credential_id == unb64(key.credential_id)
                and result.new_sign_count <= key.sign_count
            ):
                valid.append(approval.user_id)
        except Exception:  # Invalid saved evidence never grants account access.
            continue
    return sorted(set(valid))


def refresh(db, row, settings, *, lock=False):
    from datetime import UTC, datetime, timedelta

    if row.status not in {"pending", "waiting"}:
        return
    if row.expires_at <= now_iso():
        row.status = "expired"
        return
    if row.digest != intent_digest(row.canonical):
        raise HTTPException(409, "This recovery request changed. Start again.")
    contact = db.get(Contact, row.user_id)
    if (
        not contact
        or not contact.recovery_consent_at
        or contact.recovery_consent_at != row.canonical["recovery_consent_at"]
    ):
        row.status = "cancelled"
        return
    if (
        row.canonical["credential_id"] != row.credential_id
        or row.canonical["public_key"] != row.public_key
    ):
        raise HTTPException(409, "This recovery key changed. Start again.")
    try:
        groups = snapshot(db, row.user_id)
    except HTTPException:
        row.status = "cancelled"
        return
    if (
        groups != row.canonical["groups"]
        or active_key_ids(db, row.user_id) != row.canonical["old_keys"]
    ):
        row.status = "cancelled"
        return
    complete = all(
        len(approval_members(db, row, group, settings, lock=lock)) >= group["threshold"]
        for group in groups
    )
    if complete:
        if row.status != "waiting" or not row.ready_at:
            row.ready_at = (
                datetime.fromisoformat(now_iso()).astimezone(UTC) + timedelta(hours=48)
            ).isoformat()
        row.status = "waiting"
    else:
        row.status, row.ready_at = "pending", None


def code_for(row):
    value = row.digest[:12].upper()
    return "-".join(value[index : index + 4] for index in range(0, 12, 4))


def replace_access(db, security, user_id, verified):
    """Caller holds the account lock. Keep memberships; revoke old credentials."""
    from sqlalchemy import update

    from clans.live_models import Grant, LoginSession, PaymentIntent, RecoveryCode
    from clans.models import Clan
    from clans.money_models import DispatchAuthorization, Payout
    from clans.money_service import release_intent

    clan_ids = sorted(
        db.scalars(
            select(Membership.clan_id).where(
                Membership.user_id == user_id,
                Membership.active.is_(True),
            )
        ).all()
    )
    for clan_id in clan_ids:
        db.scalar(select(Clan).where(Clan.id == clan_id).with_for_update())
    # A recovered account must supply a new receiving invoice for any unsent payout.
    # Already-dispatched outcomes remain reserved and are reconciled normally.
    grants = db.scalars(select(Grant).where(Grant.beneficiary_id == user_id)).all()
    for grant in grants:
        for intent in db.scalars(
            select(PaymentIntent).where(
                PaymentIntent.grant_id == grant.id,
                PaymentIntent.active.is_(True),
            )
        ).all():
            payout = db.scalar(select(Payout).where(Payout.intent_id == intent.id))
            if payout and (
                payout.status in {"sending", "uncertain", "settled"}
                or db.scalar(
                    select(DispatchAuthorization.payout_id).where(
                        DispatchAuthorization.payout_id == payout.id
                    )
                )
            ):
                continue
            release_intent(db, intent, grant, "cancelled")
            if payout:
                payout.status = "failed"
                payout.last_error = "account_recovered_new_invoice_required"
    db.execute(update(LoginSession).where(LoginSession.user_id == user_id).values(revoked=True))
    db.execute(update(RecoveryCode).where(RecoveryCode.user_id == user_id).values(used=True))
    db.execute(update(Passkey).where(Passkey.user_id == user_id).values(active=False))
    security.add_key(db, user_id, verified)
