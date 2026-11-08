"""Contact details, claimant-bound recovery, signatory approval and owner veto."""

import hmac
import secrets
from types import SimpleNamespace

from fastapi import HTTPException, Request, Response
from pydantic import Field, StrictBool
from sqlalchemy import func, select
from webauthn import verify_authentication_response

from clans.access_service import (
    active_key_ids,
    approval_members,
    bound_challenge,
    code_for,
    refresh,
    snapshot,
)
from clans.identity_inputs import ContactInput
from clans.live_app import Finish, Input, audit, lock_clan, membership
from clans.live_models import Passkey, Profile, after
from clans.live_security import b64, digest, unb64
from clans.models import User, new_id, now_iso
from clans.money_service import intent_digest
from clans.recovery_models import (
    AccessRecovery,
    AccessRecoveryApproval,
    AccessRecoveryClan,
    Contact,
)


class RecoveryStart(Input):
    handle: str = Field(min_length=6, max_length=80)


class RecoveryCheck(Input):
    request_id: str = Field(min_length=36, max_length=36)


class RecoveryConsent(Input):
    member_checked: StrictBool
    device_code: str = Field(min_length=12, max_length=20)


def group_for(row, clan_id):
    return next((g for g in row.canonical["groups"] if g["clan_id"] == clan_id), None)


def clan_requests(db, clan_id, user_id, settings):
    items = []
    for row in db.scalars(
        select(AccessRecovery)
        .join(AccessRecoveryClan, AccessRecoveryClan.recovery_id == AccessRecovery.id)
        .where(
            AccessRecoveryClan.clan_id == clan_id,
            AccessRecovery.status.in_(["pending", "waiting"]),
            AccessRecovery.expires_at > now_iso(),
        )
        .order_by(AccessRecovery.created_at.desc())
        .limit(200)
    ).all():
        group = group_for(row, clan_id)
        if not group:
            continue
        approved = approval_members(db, row, group, settings)
        items.append(
            {
                "id": row.id,
                "member_name": db.get(User, row.user_id).display_name,
                "member_id": row.user_id,
                "created_at": row.created_at,
                "status": row.status,
                "ready_at": row.ready_at,
                "approvals": len(approved),
                "required": group["threshold"],
                "approved_names": [db.get(User, uid).display_name for uid in approved],
                "can_approve": user_id in group["signers"] and user_id not in approved,
            }
        )
    return items


def install(app, security, settings):
    cookie = "__Host-clans_access" if settings.secure_cookies else "clans_access"

    def issue_claim(row, response):
        token = secrets.token_urlsafe(48)
        row.claim_token_hash = digest(token)
        response.set_cookie(
            cookie,
            token,
            max_age=7 * 86400,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="strict",
            path="/",
        )

    def claim(db, request, recovery_id, *, mutate=False):
        query = select(AccessRecovery).where(AccessRecovery.id == recovery_id)
        row = db.scalar(query.with_for_update().execution_options(populate_existing=True))
        token = request.cookies.get(cookie, "")
        if not row or not token or not hmac.compare_digest(row.claim_token_hash, digest(token)):
            raise HTTPException(403, "Open this request on the phone where you started it.")
        if mutate:
            security.origin(request)
            if not hmac.compare_digest(
                request.headers.get("x-recovery-csrf-token", ""), security.mac("access:" + token)
            ):
                raise HTTPException(403, "Refresh your recovery request and try again.")
        return row

    def pending_assertion(row, credential, record):
        if credential.get("id") != row.credential_id:
            raise HTTPException(400, "Use the new passkey you made for this request.")
        try:
            result = verify_authentication_response(
                credential=credential,
                expected_challenge=unb64(record.challenge),
                expected_rp_id=settings.rp_id,
                expected_origin=settings.public_origin,
                credential_public_key=unb64(row.public_key),
                credential_current_sign_count=row.sign_count,
                require_user_verification=True,
            )
        except Exception as exc:
            raise HTTPException(400, "The new passkey could not be checked. Try again.") from exc
        if result.credential_id != unb64(row.credential_id):
            raise HTTPException(400, "Use the new passkey for this request.")
        row.sign_count = result.new_sign_count
        row.backed_up = result.credential_backed_up
        return result

    @app.post("/api/account/contact/options")
    def contact_options(data: ContactInput, request: Request, response: Response):
        security.limit(request, "contact", 15)
        with security.db() as db:
            user = security.current(request, db)
            return security.challenge(
                db, response, "contact-update", user_id=user.id, payload=data.model_dump()
            )

    @app.post("/api/account/contact/verify")
    def contact_verify(data: Finish, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            record = security.take_challenge(db, request, data.challenge_id, "contact-update")
            if record.user_id != user.id:
                raise HTTPException(403, "These details belong to another account.")
            security.assertion(db, data.credential, record, expected_user=user.id)
            contact = db.get(Contact, user.id)
            if not contact:
                contact = Contact(user_id=user.id, phone_number=record.payload["phone_number"])
                db.add(contact)
            contact.phone_number = record.payload["phone_number"]
            contact.lightning_address = record.payload["lightning_address"]
            if record.payload["accepted_recovery"]:
                contact.recovery_consent_at = contact.recovery_consent_at or now_iso()
            else:
                contact.recovery_consent_at = None
                security.cancel_access_requests(db, user.id)
            contact.updated_at = now_iso()
            return {"ok": True}

    @app.post("/api/auth/clan-recovery/options")
    def recovery_options(data: RecoveryStart, request: Request, response: Response):
        security.origin(request)
        security.limit(request, "clan-recovery-start", 6, 3600)
        with security.db() as db:
            profile = db.scalar(select(Profile).where(Profile.handle == data.handle))
            if not profile:
                raise HTTPException(400, "Check your account ID or use a saved recovery code.")
            user = db.scalar(select(User).where(User.id == profile.user_id).with_for_update())
            if not user.active or user.is_test_user:
                raise HTTPException(400, "This account cannot be recovered here.")
            contact = db.get(Contact, user.id)
            if not contact or not contact.recovery_consent_at:
                raise HTTPException(
                    409,
                    "Clan recovery was not enabled for this account. "
                    "Use a saved code or a spare passkey.",
                )
            groups = snapshot(db, user.id)
            count = db.scalar(
                select(func.count())
                .select_from(AccessRecovery)
                .where(
                    AccessRecovery.user_id == user.id,
                    AccessRecovery.expires_at > now_iso(),
                    AccessRecovery.status.in_(["pending", "waiting"]),
                )
            )
            if count >= 3:
                raise HTTPException(
                    429, "This account has open requests. Ask your clan to review them."
                )
            request_id = new_id()
            result = security.challenge(
                db,
                response,
                "access-register",
                user_id=user.id,
                registration=True,
                payload={
                    "handle": profile.handle,
                    "display_name": user.display_name,
                    "passkey_handle": profile.passkey_handle,
                    "request_id": request_id,
                    "groups": groups,
                    "old_keys": active_key_ids(db, user.id),
                    "recovery_consent_at": contact.recovery_consent_at,
                },
            )
            return {**result, "request_id": request_id}

    @app.post("/api/auth/clan-recovery/verify")
    def recovery_verify(data: Finish, request: Request, response: Response):
        security.origin(request)
        with security.db() as db:
            record = security.take_challenge(db, request, data.challenge_id, "access-register")
            user = db.scalar(select(User).where(User.id == record.user_id).with_for_update())
            if not user or not user.active:
                raise HTTPException(400, "This account cannot be recovered here.")
            if (
                snapshot(db, user.id) != record.payload["groups"]
                or active_key_ids(db, user.id) != record.payload["old_keys"]
            ):
                raise HTTPException(409, "The account changed. Start again.")
            count = db.scalar(
                select(func.count())
                .select_from(AccessRecovery)
                .where(
                    AccessRecovery.user_id == user.id,
                    AccessRecovery.status.in_(["pending", "waiting"]),
                    AccessRecovery.expires_at > now_iso(),
                )
            )
            if count >= 3:
                raise HTTPException(429, "This account has open recovery requests.")
            verified = security.registration(data.credential, record)
            contact = db.get(Contact, user.id)
            if (
                not contact
                or not contact.recovery_consent_at
                or contact.recovery_consent_at != record.payload["recovery_consent_at"]
            ):
                raise HTTPException(409, "Clan recovery is no longer enabled for this account.")
            created, expires = now_iso(), after(7 * 86400)
            canonical = {
                "version": 1,
                "user_id": user.id,
                "credential_id": b64(verified.credential_id),
                "public_key": b64(verified.credential_public_key),
                "groups": record.payload["groups"],
                "old_keys": record.payload["old_keys"],
                "created_at": created,
                "expires_at": expires,
                "rp_id": settings.rp_id,
                "origin": settings.public_origin,
                "recovery_consent_at": contact.recovery_consent_at,
                "nonce": secrets.token_hex(32),
            }
            if db.scalar(
                select(Passkey.id).where(Passkey.credential_id == canonical["credential_id"])
            ):
                raise HTTPException(409, "Create a new passkey for this recovery request.")
            row = AccessRecovery(
                id=record.payload["request_id"],
                user_id=user.id,
                credential_id=canonical["credential_id"],
                public_key=canonical["public_key"],
                sign_count=verified.sign_count,
                backed_up=verified.credential_backed_up,
                canonical=canonical,
                digest=intent_digest(canonical),
                claim_token_hash=digest(secrets.token_urlsafe(48)),
                created_at=created,
                expires_at=expires,
            )
            db.add(row)
            issue_claim(row, response)
            for group in canonical["groups"]:
                db.add(AccessRecoveryClan(recovery_id=row.id, clan_id=group["clan_id"]))
                audit(
                    db, group["clan_id"], user.id, "account_recovery_requested", request_id=row.id
                )
            return {"request_id": row.id, "device_code": code_for(row)}

    @app.get("/api/auth/clan-recovery/{recovery_id}")
    def recovery_status(recovery_id: str, request: Request):
        with security.db() as db:
            row = claim(db, request, recovery_id)
            refresh(db, row, settings)
            return {
                "id": row.id,
                "status": row.status,
                "ready_at": row.ready_at,
                "expires_at": row.expires_at,
                "device_code": code_for(row),
                "csrf": security.mac("access:" + request.cookies[cookie]),
            }

    @app.post("/api/auth/clan-recovery/resume/options")
    def resume_options(data: RecoveryCheck, request: Request, response: Response):
        security.origin(request)
        security.limit(request, "access-resume", 12, 900)
        with security.db() as db:
            row = db.get(AccessRecovery, data.request_id)
            if not row or row.status not in {"pending", "waiting"} or row.expires_at <= now_iso():
                raise HTTPException(400, "This request is closed or expired. Start again.")
            result = security.challenge(
                db, response, "access-resume", user_id=row.user_id, payload={"request_id": row.id}
            )
            result["options"]["allowCredentials"] = [
                {"id": row.credential_id, "type": "public-key"}
            ]
            return result

    @app.post("/api/auth/clan-recovery/resume/verify")
    def resume_verify(data: Finish, request: Request, response: Response):
        security.origin(request)
        with security.db() as db:
            record = security.take_challenge(db, request, data.challenge_id, "access-resume")
            row = db.scalar(
                select(AccessRecovery)
                .where(AccessRecovery.id == record.payload["request_id"])
                .with_for_update()
            )
            if row.status not in {"pending", "waiting"} or row.expires_at <= now_iso():
                raise HTTPException(400, "This request is closed or expired.")
            pending_assertion(row, data.credential, record)
            issue_claim(row, response)
            return {"request_id": row.id}

    @app.post("/api/auth/clan-recovery/{recovery_id}/finish/options")
    def finish_options(recovery_id: str, request: Request, response: Response):
        with security.db() as db:
            row = claim(db, request, recovery_id, mutate=True)
            refresh(db, row, settings)
            if row.status != "waiting" or row.ready_at > now_iso():
                raise HTTPException(409, "Wait for all clan approvals and the full 48 hours.")
            result = security.challenge(
                db,
                response,
                "access-finish",
                user_id=row.user_id,
                payload={"request_id": row.id, "digest": row.digest},
            )
            result["options"]["allowCredentials"] = [
                {"id": row.credential_id, "type": "public-key"}
            ]
            return result

    @app.post("/api/auth/clan-recovery/{recovery_id}/finish/verify")
    def finish_verify(recovery_id: str, data: Finish, request: Request, response: Response):
        with security.db() as db:
            # Account -> recovery -> sorted clans -> keys matches authenticated mutation order.
            initial = db.get(AccessRecovery, recovery_id)
            if not initial:
                raise HTTPException(404, "Recovery request not found.")
            user = db.scalar(select(User).where(User.id == initial.user_id).with_for_update())
            row = claim(db, request, recovery_id, mutate=True)
            db.refresh(row)
            record = security.take_challenge(db, request, data.challenge_id, "access-finish")
            if (
                record.payload["request_id"] != row.id
                or record.payload["digest"] != row.digest
                or not user.active
            ):
                raise HTTPException(409, "This recovery request changed.")
            for group in row.canonical["groups"]:
                lock_clan(db, group["clan_id"])
            refresh(db, row, settings, lock=True)
            if row.status != "waiting" or row.ready_at > now_iso():
                raise HTTPException(409, "This request is blocked, changed or still waiting.")
            result = pending_assertion(row, data.credential, record)
            row.status, row.finished_at = "completed", now_iso()
            from clans.access_service import replace_access

            replace_access(
                db,
                security,
                row.user_id,
                SimpleNamespace(
                    credential_id=unb64(row.credential_id),
                    credential_public_key=unb64(row.public_key),
                    sign_count=result.new_sign_count,
                    credential_backed_up=row.backed_up,
                ),
            )
            codes = security.recovery_codes(db, row.user_id)
            security.issue_session(db, response, row.user_id)
            response.delete_cookie(cookie, path="/", secure=settings.secure_cookies)
            for group in row.canonical["groups"]:
                audit(
                    db, group["clan_id"], row.user_id, "account_access_restored", request_id=row.id
                )
            return {"handle": db.get(Profile, row.user_id).handle, "recovery_codes": codes}

    @app.get("/api/account/access-recoveries")
    def own_recoveries(request: Request):
        with security.db() as db:
            user = security.current(request, db)
            return [
                {
                    "id": row.id,
                    "status": row.status,
                    "created_at": row.created_at,
                    "ready_at": row.ready_at,
                    "expires_at": row.expires_at,
                }
                for row in db.scalars(
                    select(AccessRecovery)
                    .where(
                        AccessRecovery.user_id == user.id,
                        AccessRecovery.status.in_(["pending", "waiting"]),
                        AccessRecovery.expires_at > now_iso(),
                    )
                    .order_by(AccessRecovery.created_at.desc())
                ).all()
            ]

    @app.post("/api/account/access-recoveries/{recovery_id}/block/options")
    def block_options(recovery_id: str, request: Request, response: Response):
        with security.db() as db:
            user = security.current(request, db)
            row = db.get(AccessRecovery, recovery_id)
            if not row or row.user_id != user.id:
                raise HTTPException(404, "Recovery request not found.")
            return security.challenge(
                db, response, "access-block", user_id=user.id, payload={"request_id": row.id}
            )

    @app.post("/api/account/access-recoveries/{recovery_id}/block/verify")
    def block_verify(recovery_id: str, data: Finish, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            row = db.scalar(
                select(AccessRecovery).where(AccessRecovery.id == recovery_id).with_for_update()
            )
            if not row or row.user_id != user.id or row.status not in {"pending", "waiting"}:
                raise HTTPException(409, "This request is already closed.")
            record = security.take_challenge(db, request, data.challenge_id, "access-block")
            if record.user_id != user.id or record.payload["request_id"] != row.id:
                raise HTTPException(403, "This block belongs to a different request.")
            security.assertion(db, data.credential, record, expected_user=user.id)
            row.status = "blocked"
            for group in row.canonical["groups"]:
                audit(db, group["clan_id"], user.id, "account_recovery_blocked", request_id=row.id)
            return {"ok": True}

    @app.post("/api/clans/{clan_id}/access-recoveries/{recovery_id}/approval/options")
    def approve_options(
        clan_id: str, recovery_id: str, data: RecoveryConsent, request: Request, response: Response
    ):
        security.limit(request, "access-approval", 20, 900)
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            row = db.get(AccessRecovery, recovery_id)
            group = group_for(row, clan_id) if row else None
            if (
                not group
                or row.status not in {"pending", "waiting"}
                or row.expires_at <= now_iso()
                or user.id not in group["signers"]
                or user.id == row.user_id
            ):
                raise HTTPException(403, "You cannot approve this account recovery.")
            code = data.device_code.replace("-", "").replace(" ", "").upper()
            if not data.member_checked or not hmac.compare_digest(code, row.digest[:12].upper()):
                raise HTTPException(400, "Check the member and the code on their new phone.")
            nonce = secrets.token_bytes(32)
            return {
                **security.challenge(
                    db,
                    response,
                    "access-approval",
                    user_id=user.id,
                    payload={
                        "request_id": row.id,
                        "clan_id": clan_id,
                        "digest": row.digest,
                        "nonce": b64(nonce),
                    },
                    challenge_bytes=bound_challenge(row.digest, nonce, clan_id),
                ),
                "digest": row.digest,
            }

    @app.post("/api/clans/{clan_id}/access-recoveries/{recovery_id}/approval/verify")
    def approve_verify(clan_id: str, recovery_id: str, data: Finish, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            row = db.scalar(
                select(AccessRecovery).where(AccessRecovery.id == recovery_id).with_for_update()
            )
            group = group_for(row, clan_id) if row else None
            if not group or user.id not in group["signers"] or user.id == row.user_id:
                raise HTTPException(403, "You cannot approve this account recovery.")
            refresh(db, row, settings)
            if row.status not in {"pending", "waiting"}:
                raise HTTPException(409, "This request is closed or changed.")
            record = security.take_challenge(db, request, data.challenge_id, "access-approval")
            if (
                record.user_id != user.id
                or record.payload["request_id"] != row.id
                or record.payload["clan_id"] != clan_id
                or record.payload["digest"] != row.digest
            ):
                raise HTTPException(409, "This recovery request changed. Review it again.")
            key = db.scalar(
                select(Passkey)
                .where(
                    Passkey.credential_id == data.credential.get("id", ""),
                    Passkey.user_id == user.id,
                    Passkey.active.is_(True),
                )
                .with_for_update()
            )
            if not key:
                raise HTTPException(400, "Use your own passkey.")
            counter = key.sign_count
            key = security.assertion(db, data.credential, record, expected_user=user.id)
            previous = db.scalar(
                select(AccessRecoveryApproval).where(
                    AccessRecoveryApproval.recovery_id == row.id,
                    AccessRecoveryApproval.clan_id == clan_id,
                    AccessRecoveryApproval.user_id == user.id,
                )
            )
            proof = {
                "digest": row.digest,
                "nonce": record.payload["nonce"],
                "public_key": key.public_key,
                "counter_before": counter,
                "credential": data.credential,
            }
            if previous:
                previous.passkey_id, previous.proof = key.id, proof
            else:
                db.add(
                    AccessRecoveryApproval(
                        recovery_id=row.id,
                        clan_id=clan_id,
                        user_id=user.id,
                        passkey_id=key.id,
                        proof=proof,
                    )
                )
            db.flush()
            refresh(db, row, settings)
            audit(db, clan_id, user.id, "account_recovery_approved", request_id=row.id)
            return {"status": row.status, "ready_at": row.ready_at}
