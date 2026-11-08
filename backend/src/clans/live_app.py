"""Standalone Clans: real accounts and consent-based governance, no demo router."""

import json
import secrets
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from clans import communities
from clans.identity_inputs import ContactInput
from clans.live_config import LiveSettings
from clans.live_models import (
    ClanConfig,
    Grant,
    Invitation,
    LoginSession,
    Operation,
    Passkey,
    Profile,
    RecoveryCode,
    Treasury,
    Vote,
    after,
)
from clans.live_security import Security, digest
from clans.models import AuditEvent, Clan, Membership, PolicyVersion, User, new_id, now_iso
from clans.money_models import Balance, Debt, LedgerEntry
from clans.recovery_models import Contact

TERMS = "2026-11-03"
CUSTODY = (
    "Afribit runs the Bitcoin wallet that holds your clan's money. "
    "Members vote on requests, then signatories approve each payment and its fee. "
    "Afribit still has control of the wallet. Payments may take longer if a route is unavailable."
)
# Where clan wallets are the only way money moves, as on the signet pilot.
WALLET_CUSTODY = (
    "Your clan's money is in its own Bitcoin wallet. Signatories hold its keys on their "
    "phones, and each payment needs a majority of them plus Afribit. Clans can't move it "
    "alone. This is a test network: the coins have no value."
)


def custody_notice(settings) -> str:
    if settings.clan_wallets_enabled and not (
        settings.receiving_enabled or settings.payouts_enabled
    ):
        return WALLET_CUSTODY
    return CUSTODY


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Signup(ContactInput):
    display_name: str = Field(min_length=2, max_length=100)
    username: str
    accepted_terms: StrictBool

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        from clans.usernames import normalize

        return normalize(value)


class Finish(Input):
    challenge_id: str = Field(max_length=36)
    credential: dict


class Recover(Input):
    handle: str = Field(max_length=80)
    code: str = Field(min_length=20, max_length=200)


class ClanInput(Input):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=500)
    target_signers: Literal[3, 5, 7]
    member_vote_quorum: int = Field(ge=1, le=100)
    be_signer: StrictBool
    accepted_custody: StrictBool
    # Joins the community that gave this code. Without one, the clan is in the default one.
    community_code: str | None = Field(default=None, max_length=20)


class InviteInput(Input):
    is_signer: StrictBool = False


class Token(Input):
    token: str = Field(min_length=32, max_length=100)


class AcceptInvite(Token):
    accepted_custody: StrictBool
    accepted_signer: StrictBool = False


class GrantInput(Input):
    purpose: str = Field(min_length=8, max_length=1000)
    amount_sats: int | None = Field(default=None, strict=True, gt=0, le=100_000_000)
    quote: str | None = Field(default=None, min_length=100, max_length=2000)

    @model_validator(mode="after")
    def one_amount(self):
        if (self.amount_sats is None) == (self.quote is None):
            raise ValueError("Use one grant quote or one amount in sats")
        return self


class GrantQuoteInput(Input):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: str = Field(min_length=1, max_length=15)


class VoteInput(Input):
    choice: Literal["approve", "reject", "abstain"]


class ReauthInput(Input):
    action: Literal["add_passkey", "recovery_codes", "username"]
    username: str | None = None


def audit(db, clan_id, user_id, event, **payload):
    db.add(AuditEvent(clan_id=clan_id, actor_id=user_id, event_type=event, payload=payload))


def membership(db, clan_id, user_id, *, organizer=False):
    member = db.scalar(
        select(Membership).where(
            Membership.clan_id == clan_id,
            Membership.user_id == user_id,
            Membership.active.is_(True),
        )
    )
    if not member or (organizer and member.role != "organizer"):
        raise HTTPException(403, "You do not have access to this clan action.")
    return member


def require_no_clan(db, user_id):
    if db.scalar(
        select(Membership.id).where(Membership.user_id == user_id, Membership.active.is_(True))
    ):
        raise HTTPException(
            409, "Your account already belongs to a clan. You can belong to one clan at a time."
        )
    if db.scalar(
        select(Debt.grant_id)
        .join(Grant, Grant.id == Debt.grant_id)
        .where(Grant.beneficiary_id == user_id, Debt.outstanding_msat > 0)
    ):
        raise HTTPException(409, "Repay your existing grant before joining another clan.")


def debt_view(grant, debt, kes_rate):
    """What a grant's member owes, in the debt's own currency.

    KES debts: `principal_minor` and `outstanding_minor` are KES cents, and
    `outstanding_sats_estimate` is about what that is in sats now (None without a fresh
    rate). Sats debts: both are sats, and the estimate is the exact sats still owed.
    """
    from clans.kes_debts import is_kes, sats_estimate

    owed = grant.outstanding_minor if debt else 0
    if not is_kes(grant):
        estimate = (debt.outstanding_msat + 999) // 1000 if debt else 0
    elif not owed:
        estimate = 0
    else:
        rate = kes_rate()
        estimate = sats_estimate(owed, rate.per_btc) if rate else None
    return {
        "obligation_currency": grant.obligation_currency,
        "principal_minor": grant.principal_minor,
        "outstanding_minor": owed,
        "recovered_sats": grant.recovered_sats,
        "outstanding_sats_estimate": estimate,
    }


def lock_clan(db, clan_id):
    clan = db.scalar(select(Clan).where(Clan.id == clan_id).with_for_update())
    if not clan:
        raise HTTPException(404, "Clan not found.")
    return clan


def operation(db, request, user, scope, data, perform):
    key = request.headers.get("idempotency-key", "")
    if not 16 <= len(key) <= 100:
        raise HTTPException(400, "An idempotency key is required.")
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    hashed = digest(json.dumps(data, sort_keys=True, separators=(",", ":")))
    previous = db.scalar(
        select(Operation).where(
            Operation.user_id == user.id, Operation.scope == scope, Operation.key == key
        )
    )
    if previous:
        if previous.request_hash != hashed:
            raise HTTPException(409, "This request key was already used for a different action.")
        return previous.response
    result = perform()
    db.add(Operation(user_id=user.id, scope=scope, key=key, request_hash=hashed, response=result))
    return result


def clan_summary(db, clan, settings):
    config = db.get(ClanConfig, clan.id)
    policy = db.scalar(
        select(PolicyVersion)
        .where(PolicyVersion.clan_id == clan.id)
        .order_by(PolicyVersion.version.desc())
    )
    members = db.scalars(
        select(Membership).where(Membership.clan_id == clan.id, Membership.active.is_(True))
    ).all()
    treasury = db.get(Balance, clan.id)
    if not treasury:
        raise HTTPException(503, "The treasury accounting record needs reconciliation.")
    recovery, given, repaid = db.execute(
        select(
            func.coalesce(func.sum(Debt.outstanding_msat), 0),
            func.coalesce(func.sum(Debt.principal_msat), 0),
            func.coalesce(func.sum(Debt.recovered_msat), 0),
        )
        .join(Grant, Grant.id == Debt.grant_id)
        .where(Grant.clan_id == clan.id)
    ).one()
    return {
        "id": clan.id,
        "name": clan.name,
        "description": config.description,
        "target_signers": config.target_signers,
        "signer_threshold": policy.signer_threshold,
        "member_vote_quorum": policy.member_vote_quorum,
        "member_count": len(members),
        "signer_count": sum(m.is_signer for m in members),
        "governance_ready": sum(m.is_signer for m in members) == config.target_signers
        and len(members) > policy.member_vote_quorum,
        "balance_sats": treasury.balance_msat // 1000,
        "reserved_sats": treasury.reserved_msat // 1000,
        "available_sats": (treasury.balance_msat - treasury.reserved_msat) // 1000,
        "balance_msat": str(treasury.balance_msat),
        "reserved_msat": str(treasury.reserved_msat),
        "available_msat": str(treasury.balance_msat - treasury.reserved_msat),
        "in_recovery_msat": str(recovery),
        "grants_given_msat": str(given),
        "grants_repaid_msat": str(repaid),
        "created_at": clan.created_at,
        "community": communities.view(communities.for_clan(db, settings, clan.id)),
    }


def create_app(settings: LiveSettings | None = None):
    settings = settings or LiveSettings()
    if settings.environment == "production":
        if settings.static_directory is not None:
            raise ValueError("Production API must not serve frontend files")
        from sqlalchemy.engine import make_url

        if make_url(settings.database_url.get_secret_value()).username != "afribit_clans_web":
            raise ValueError("Production web requires the isolated afribit_clans_web runtime role")
        if settings.dispatch_secret.get_secret_value():
            raise ValueError("Worker dispatch secrets must not be present in the web environment")
    if (settings.receiving_enabled or settings.payouts_enabled) and (
        not settings.btcpay_store_id
        or not settings.btcpay_api_key.get_secret_value()
        or len(settings.expected_node_pubkey) != 66
    ):
        raise ValueError(
            "Money movement requires dedicated treasury credentials and node identity."
        )
    security = Security(settings)
    from clans.display_rates import DisplayRates

    security.display_rates = DisplayRates()
    app = FastAPI(
        title="AfriBit Clans",
        version="1.7.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )
    app.state.security = security
    from clans.request_limits import RequestBodyLimit

    app.add_middleware(RequestBodyLimit)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[settings.rp_id, "127.0.0.1", "localhost", "testserver"],
    )

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(self), payment=(), "
            "clipboard-read=(), clipboard-write=(self), "
            "publickey-credentials-create=(self), publickey-credentials-get=(self)"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
        )
        if request.url.path.startswith(("/api/", "/health")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(IntegrityError)
    async def conflict(_request, _exc):
        return JSONResponse(
            {
                "detail": "This action was already processed or conflicts with a recent change. "
                "Refresh and try again."
            },
            status_code=409,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/health/ready")
    def ready():
        with security.db() as db:
            db.execute(text("SELECT 1"))
            revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        return {
            "status": "ok",
            "release": "1.7.0",
            "schema": revision,
            "receiving": settings.receiving_enabled,
            "payouts": settings.payouts_enabled,
        }

    @app.get("/api/session")
    def session(request: Request):
        with security.db() as db:
            user = security.current(request, db, optional=True)
            result = {
                "user": None,
                "csrf": None,
                "custody_notice": custody_notice(settings),
                "terms_version": TERMS,
                "capabilities": {
                    "receiving": settings.receiving_enabled,
                    "payouts": settings.payouts_enabled,
                    "currency": "BTC",
                    "max_invoice_sats": settings.max_invoice_sats,
                    "max_payout_sats": settings.max_payout_sats,
                    "payout_budget_currency": settings.payout_budget_currency,
                    "payout_global_24h_kes": settings.payout_global_24h_kes,
                    "payout_clan_24h_kes": settings.payout_clan_24h_kes,
                    "max_payout_kes": settings.max_payout_kes,
                },
            }
            if user:
                profile = db.get(Profile, user.id)
                contact = db.get(Contact, user.id)
                result.update(
                    user={
                        "id": user.id,
                        "display_name": user.display_name,
                        "handle": profile.handle,
                        "onboarded": bool(profile.onboarded_at),
                        "phone_number": contact.phone_number if contact else None,
                        "lightning_address": contact.lightning_address if contact else None,
                        "clan_recovery_enabled": bool(contact and contact.recovery_consent_at),
                        "contact_complete": bool(contact),
                    },
                    csrf=security.mac(request.cookies[settings.cookie_name]),
                )
                result["clans"] = [
                    clan_summary(db, db.get(Clan, m.clan_id), settings)
                    for m in db.scalars(
                        select(Membership).where(
                            Membership.user_id == user.id, Membership.active.is_(True)
                        )
                    ).all()
                ]
            return result

    @app.post("/api/auth/register/options")
    def register_options(data: Signup, request: Request, response: Response):
        security.origin(request)
        security.limit(request, "register", 12)
        if not data.accepted_terms:
            raise HTTPException(400, "Accept the account terms to continue.")
        with security.db() as db:
            if db.scalar(select(Profile).where(Profile.handle == data.username)):
                raise HTTPException(409, "That username is taken. Choose another one.")
            return security.challenge(
                db,
                response,
                "register",
                payload={
                    **security.registration_payload(data.display_name),
                    "handle": data.username,
                    "phone_number": data.phone_number,
                    "lightning_address": data.lightning_address,
                    "accepted_recovery": data.accepted_recovery,
                },
                registration=True,
            )

    @app.post("/api/auth/register/verify")
    def register_verify(data: Finish, request: Request, response: Response):
        security.origin(request)
        with security.db() as db:
            record = security.take_challenge(db, request, data.challenge_id, "register")
            verified = security.registration(data.credential, record)
            payload = record.payload
            user = User(
                id=payload["user_id"], display_name=payload["display_name"], is_test_user=False
            )
            db.add(user)
            db.flush()
            db.add(
                Profile(
                    user_id=user.id,
                    handle=payload["handle"],
                    passkey_handle=payload["passkey_handle"],
                    terms_version=TERMS,
                )
            )
            security.add_key(db, user.id, verified)
            db.add(
                Contact(
                    user_id=user.id,
                    phone_number=payload["phone_number"],
                    lightning_address=payload["lightning_address"],
                    recovery_consent_at=now_iso() if payload["accepted_recovery"] else None,
                )
            )
            codes = security.recovery_codes(db, user.id)
            security.issue_session(db, response, user.id)
            return {"handle": payload["handle"], "recovery_codes": codes}

    @app.post("/api/auth/login/options")
    def login_options(request: Request, response: Response):
        security.origin(request)
        security.limit(request, "login")
        with security.db() as db:
            return security.challenge(db, response, "login")

    @app.post("/api/auth/login/verify")
    def login_verify(data: Finish, request: Request, response: Response):
        security.origin(request)
        with security.db() as db:
            record = security.take_challenge(db, request, data.challenge_id, "login")
            owner_id = db.scalar(
                select(Passkey.user_id).where(
                    Passkey.credential_id == data.credential.get("id", ""),
                    Passkey.active.is_(True),
                )
            )
            user = db.scalar(select(User).where(User.id == owner_id).with_for_update())
            if not user:
                raise HTTPException(400, "Use an active passkey belonging to this account.")
            if not user.active or user.is_test_user:
                raise HTTPException(403, "This account is unavailable.")
            key = security.assertion(db, data.credential, record, expected_user=user.id)
            security.issue_session(db, response, key.user_id)
            return {"ok": True}

    @app.post("/api/auth/recover/options")
    def recover_options(data: Recover, request: Request, response: Response):
        from clans.recovery_words import hash_input

        security.origin(request)
        security.limit(request, "recovery", 8, 900)
        with security.db() as db:
            profile = db.scalar(
                select(Profile).where(Profile.handle == data.handle.strip().lower())
            )
            try:
                recovery_hash = security.mac(hash_input(data.code))
            except ValueError as exc:
                raise HTTPException(400, "Check your username and recovery words.") from exc
            code = db.scalar(
                select(RecoveryCode).where(
                    RecoveryCode.code_hash == recovery_hash,
                    RecoveryCode.used.is_(False),
                )
            )
            if not profile or not code or code.user_id != profile.user_id:
                raise HTTPException(400, "The account handle or recovery code is incorrect.")
            user = db.get(User, profile.user_id)
            if not user.active:
                raise HTTPException(400, "This account cannot be recovered.")
            return security.challenge(
                db,
                response,
                "recover",
                user_id=user.id,
                registration=True,
                payload={
                    "handle": profile.handle,
                    "display_name": user.display_name,
                    "passkey_handle": profile.passkey_handle,
                    "code_id": code.id,
                },
            )

    @app.post("/api/auth/recover/verify")
    def recover_verify(data: Finish, request: Request, response: Response):
        security.origin(request)
        with security.db() as db:
            record = security.take_challenge(db, request, data.challenge_id, "recover")
            db.scalar(select(User).where(User.id == record.user_id).with_for_update())
            code = db.scalar(
                select(RecoveryCode)
                .where(RecoveryCode.id == record.payload["code_id"])
                .with_for_update()
            )
            if code.used:
                raise HTTPException(400, "This recovery code has already been used.")
            verified = security.registration(data.credential, record)
            from clans.access_service import replace_access

            replace_access(db, security, record.user_id, verified)
            codes = security.recovery_codes(db, record.user_id)
            security.issue_session(db, response, record.user_id)
            return {"handle": record.payload["handle"], "recovery_codes": codes}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        with security.db() as db:
            security.current(request, db)
            db.execute(
                update(LoginSession)
                .where(LoginSession.token_hash == digest(request.cookies[settings.cookie_name]))
                .values(revoked=True)
            )
        response.delete_cookie(settings.cookie_name, path="/", secure=settings.secure_cookies)
        return {"ok": True}

    @app.post("/api/account/reauth/options")
    def reauth_options(data: ReauthInput, request: Request, response: Response):
        security.limit(request, "account-security", 15)
        with security.db() as db:
            user = security.current(request, db)
            payload = {"action": data.action}
            if data.action == "username":
                from clans.usernames import normalize

                try:
                    username = normalize(data.username or "")
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from exc
                if db.scalar(
                    select(Profile).where(Profile.handle == username, Profile.user_id != user.id)
                ):
                    raise HTTPException(409, "That username is taken. Choose another one.")
                payload["username"] = username
            return security.challenge(db, response, "reauth", user_id=user.id, payload=payload)

    @app.post("/api/account/reauth/verify")
    def reauth_verify(data: Finish, request: Request, response: Response):
        with security.db() as db:
            user = security.current(request, db)
            record = security.take_challenge(db, request, data.challenge_id, "reauth")
            if record.user_id != user.id:
                raise HTTPException(403, "This security request belongs to another account.")
            db.scalar(select(User).where(User.id == user.id).with_for_update())
            security.assertion(db, data.credential, record, expected_user=user.id)
            profile = db.get(Profile, user.id)
            if record.payload["action"] == "username":
                profile.handle = record.payload["username"]
                security.cancel_access_requests(db, user.id)
                return {"handle": profile.handle}
            if record.payload["action"] == "recovery_codes":
                db.execute(
                    update(RecoveryCode).where(RecoveryCode.user_id == user.id).values(used=True)
                )
                return {
                    "handle": profile.handle,
                    "recovery_codes": security.recovery_codes(db, user.id),
                }
            count = db.scalar(
                select(func.count())
                .select_from(Passkey)
                .where(Passkey.user_id == user.id, Passkey.active.is_(True))
            )
            if count >= 10:
                raise HTTPException(409, "This account already has ten passkeys.")
            return security.challenge(
                db,
                response,
                "add-passkey",
                user_id=user.id,
                registration=True,
                payload={
                    "handle": profile.handle,
                    "display_name": user.display_name,
                    "passkey_handle": profile.passkey_handle,
                },
            )

    @app.post("/api/account/passkeys/verify")
    def add_passkey(data: Finish, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            record = security.take_challenge(db, request, data.challenge_id, "add-passkey")
            if record.user_id != user.id:
                raise HTTPException(403, "This passkey request belongs to another account.")
            security.add_key(db, user.id, security.registration(data.credential, record))
            return {"ok": True}

    @app.post("/api/onboarding/complete")
    def onboard(request: Request):
        with security.db() as db:
            user = security.current(request, db)
            db.get(Profile, user.id).onboarded_at = now_iso()
            return {"ok": True}

    @app.post("/api/clans")
    def create_clan(data: ClanInput, request: Request):
        security.limit(request, "clan-create", 10, 3600)
        with security.db() as db:
            user = security.current(request, db)

            def perform():
                require_no_clan(db, user.id)
                if not data.accepted_custody:
                    raise HTTPException(400, "Acknowledge the treasury custody terms.")
                count = db.scalar(
                    select(func.count()).select_from(Clan).where(Clan.created_by == user.id)
                )
                if count >= 10:
                    raise HTTPException(409, "You can organize up to ten clans.")
                community = None
                if data.community_code and data.community_code.strip():
                    community = communities.by_code(db, data.community_code)
                    if community is None:
                        raise HTTPException(
                            400, "That community code isn't valid. Check it with the community."
                        )
                clan = Clan(
                    id=new_id(),
                    name=data.name,
                    created_by=user.id,
                    status="setup",
                    community_id=community.id if community else None,
                )
                db.add(clan)
                db.flush()
                db.add_all(
                    [
                        ClanConfig(
                            clan_id=clan.id,
                            description=data.description,
                            target_signers=data.target_signers,
                            custody_terms_version=TERMS,
                            custody_accepted_by=user.id,
                        ),
                        Treasury(clan_id=clan.id),
                        Balance(clan_id=clan.id),
                        Membership(
                            clan_id=clan.id,
                            user_id=user.id,
                            role="organizer",
                            is_signer=data.be_signer,
                        ),
                        PolicyVersion(
                            clan_id=clan.id,
                            currency="BTC",
                            member_vote_quorum=data.member_vote_quorum,
                            signer_threshold=data.target_signers // 2 + 1,
                            beneficiary_can_approve=False,
                        ),
                    ]
                )
                audit(
                    db,
                    clan.id,
                    user.id,
                    "clan_created",
                    target_signers=data.target_signers,
                    accepted_custody=TERMS,
                    accepted_signer=data.be_signer,
                    community=community.id if community else None,
                )
                return {"clan_id": clan.id}

            return operation(db, request, user, "create-clan", data.model_dump(), perform)

    @app.get("/api/clans/{clan_id}")
    def detail(clan_id: str, request: Request, include_activity: bool = True):
        with security.db() as db:
            user = security.current(request, db)
            member = membership(db, clan_id, user.id)
            clan = db.get(Clan, clan_id)
            result = clan_summary(db, clan, settings)
            result["my_role"] = member.role
            result["my_signer"] = member.is_signer
            result["members"] = [
                {
                    "id": m.user_id,
                    "name": db.get(User, m.user_id).display_name,
                    "handle": db.get(Profile, m.user_id).handle,
                    "role": m.role,
                    "is_signer": m.is_signer,
                }
                for m in db.scalars(
                    select(Membership).where(
                        Membership.clan_id == clan_id, Membership.active.is_(True)
                    )
                ).all()
            ]
            result["grants"] = []
            found_rate = []

            def kes_rate():
                # Fetched only when a KES debt is shown; cached by DisplayRates for a minute.
                from clans.treasury_provider import ProviderError

                if not found_rate:
                    try:
                        found_rate.append(security.display_rates.get("KES"))
                    except ProviderError:
                        found_rate.append(None)
                return found_rate[0]

            recent_grants = (
                select(Grant.id)
                .where(Grant.clan_id == clan_id)
                .order_by(Grant.created_at.desc())
                .limit(100)
                .correlate(None)
            )
            for grant in db.scalars(
                select(Grant)
                .outerjoin(Debt, Debt.grant_id == Grant.id)
                .where(Grant.clan_id == clan_id)
                .where(
                    or_(
                        Grant.id.in_(recent_grants),
                        Grant.status == "voting",
                        and_(member.is_signer, Grant.status == "awaiting_signatures"),
                        and_(
                            Grant.beneficiary_id == user.id,
                            or_(
                                Debt.outstanding_msat > 0,
                                Grant.status.not_in(["recovered", "rejected", "cancelled"]),
                            ),
                        ),
                    )
                )
                .order_by(Grant.created_at.desc())
            ):
                votes = db.scalars(select(Vote).where(Vote.grant_id == grant.id)).all()
                from clans.live_models import PaymentIntent
                from clans.money_api import intent_view

                debt = db.get(Debt, grant.id)
                intent = db.scalar(
                    select(PaymentIntent)
                    .where(PaymentIntent.grant_id == grant.id)
                    .order_by(PaymentIntent.created_at.desc())
                )
                result["grants"].append(
                    {
                        "id": grant.id,
                        "beneficiary_id": grant.beneficiary_id,
                        "beneficiary_name": db.get(User, grant.beneficiary_id).display_name,
                        "purpose": grant.purpose,
                        "amount_sats": grant.amount_sats,
                        "status": grant.status,
                        "created_at": grant.created_at,
                        "accepted_at": grant.accepted_at,
                        "outstanding_msat": str(debt.outstanding_msat) if debt else "0",
                        "recovered_msat": str(debt.recovered_msat) if debt else "0",
                        **debt_view(grant, debt, kes_rate),
                        "payment": intent_view(db, intent, grant, settings, user.id)
                        if intent
                        else None,
                        "required_votes": grant.policy_snapshot["quorum"],
                        "votes": [{"user_id": v.user_id, "choice": v.choice} for v in votes],
                        "can_vote": user.id in grant.eligible_voters
                        and not any(v.user_id == user.id for v in votes)
                        and grant.status == "voting",
                    }
                )
            result["activity"] = (
                [
                    {
                        "id": event.id,
                        "event": event.event_type,
                        "actor": db.get(User, event.actor_id).display_name,
                        "at": event.occurred_at,
                        "data": event.payload,
                    }
                    for event in db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.clan_id == clan_id)
                        .order_by(AuditEvent.occurred_at.desc())
                        .limit(100)
                    )
                ]
                if include_activity
                else []
            )
            result["invitations"] = (
                [
                    {
                        "id": i.id,
                        "is_signer": i.is_signer,
                        "expires_at": i.expires_at,
                        "accepted": bool(i.accepted_by),
                        "revoked": i.revoked,
                    }
                    for i in db.scalars(
                        select(Invitation)
                        .where(Invitation.clan_id == clan_id)
                        .order_by(Invitation.created_at.desc())
                        .limit(100)
                    )
                ]
                if member.role == "organizer"
                else []
            )
            result["journal"] = (
                [
                    {
                        "id": j.id,
                        "event": j.event,
                        "amount_sats": j.amount_msat // 1000,
                        "amount_msat": str(j.amount_msat),
                        "at": j.created_at,
                    }
                    for j in db.scalars(
                        select(LedgerEntry)
                        .where(LedgerEntry.clan_id == clan_id)
                        .order_by(LedgerEntry.created_at.desc())
                        .limit(100)
                    )
                ]
                if include_activity
                else []
            )
            from clans.live_models import IncomingPayment
            from clans.money_api import incoming_view, worker_state

            result["deposits"] = [
                {**incoming_view(row), "requested_by_me": row.user_id == user.id}
                for row in db.scalars(
                    select(IncomingPayment)
                    .where(IncomingPayment.clan_id == clan_id)
                    .order_by(IncomingPayment.created_at.desc())
                    .limit(20)
                )
            ]
            result["treasury_ready"] = worker_state(db)
            from clans.access_api import clan_requests

            result["access_recoveries"] = clan_requests(db, clan_id, user.id, settings)
            return result

    @app.post("/api/clans/{clan_id}/invitations")
    def invite(clan_id: str, data: InviteInput, request: Request):
        security.limit(request, "invites", 60, 3600)
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id, organizer=True)
            # Bearer material is returned once, never written to audit or idempotency records.
            token = secrets.token_urlsafe(32)
            invitation = Invitation(
                id=new_id(),
                clan_id=clan_id,
                token_hash=digest(token),
                invited_by=user.id,
                is_signer=data.is_signer,
                expires_at=after(7 * 86400),
            )
            db.add(invitation)
            audit(
                db,
                clan_id,
                user.id,
                "invitation_created",
                invitation_id=invitation.id,
                is_signer=data.is_signer,
            )
            return {"id": invitation.id, "token": token, "expires_at": invitation.expires_at}

    @app.post("/api/invitations/preview")
    def preview(data: Token, request: Request):
        security.origin(request)
        security.limit(request, "invite-lookup", 60)
        with security.db() as db:
            invitation = db.scalar(
                select(Invitation).where(Invitation.token_hash == digest(data.token))
            )
            if (
                not invitation
                or invitation.revoked
                or invitation.accepted_by
                or invitation.expires_at <= now_iso()
            ):
                raise HTTPException(404, "This invitation is expired, revoked or already accepted.")
            clan = db.get(Clan, invitation.clan_id)
            return {
                "name": clan.name,
                "is_signer": invitation.is_signer,
                "invited_by": db.get(User, invitation.invited_by).display_name,
                "custody_notice": custody_notice(settings),
            }

    @app.post("/api/invitations/accept")
    def accept_invite(data: AcceptInvite, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            initial = db.scalar(
                select(Invitation).where(Invitation.token_hash == digest(data.token))
            )
            if not initial:
                raise HTTPException(404, "Invitation not found.")
            lock_clan(db, initial.clan_id)
            invitation = db.scalar(
                select(Invitation)
                .where(Invitation.id == initial.id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if invitation.accepted_by == user.id:
                return {"clan_id": invitation.clan_id}
            require_no_clan(db, user.id)
            if invitation.revoked or invitation.accepted_by or invitation.expires_at <= now_iso():
                raise HTTPException(409, "This invitation is no longer available.")
            if not data.accepted_custody or (invitation.is_signer and not data.accepted_signer):
                raise HTTPException(400, "Accept the membership terms and offered signatory role.")
            existing = db.scalar(
                select(Membership).where(
                    Membership.clan_id == invitation.clan_id, Membership.user_id == user.id
                )
            )
            if existing:
                raise HTTPException(409, "You are already a member of this clan.")
            config = db.get(ClanConfig, invitation.clan_id)
            count = db.scalar(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.clan_id == invitation.clan_id,
                    Membership.is_signer.is_(True),
                    Membership.active.is_(True),
                )
            )
            if invitation.is_signer and count >= config.target_signers:
                raise HTTPException(
                    409, "All signatory places are filled. Ask for a member invitation."
                )
            db.add(
                Membership(
                    clan_id=invitation.clan_id,
                    user_id=user.id,
                    role="member",
                    is_signer=invitation.is_signer,
                )
            )
            invitation.accepted_by = user.id
            invitation.accepted_at = now_iso()
            audit(
                db,
                invitation.clan_id,
                user.id,
                "member_joined",
                accepted_custody=TERMS,
                accepted_signer=invitation.is_signer,
            )
            return {"clan_id": invitation.clan_id}

    @app.post("/api/clans/{clan_id}/invitations/{invitation_id}/revoke")
    def revoke(clan_id: str, invitation_id: str, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id, organizer=True)
            invitation = db.get(Invitation, invitation_id)
            if not invitation or invitation.clan_id != clan_id:
                raise HTTPException(404, "Invitation not found.")
            if invitation.accepted_by:
                raise HTTPException(409, "This invitation was already accepted.")
            invitation.revoked = True
            audit(db, clan_id, user.id, "invitation_revoked", invitation_id=invitation.id)
            return {"ok": True}

    @app.get("/api/rates/{currency}")
    def display_rate(currency: str, request: Request):
        from clans.treasury_provider import ProviderError

        with security.db() as db:
            user = security.current(request, db)
        # Members sharing Wi-Fi or a mobile carrier must not consume one quota.
        security.limit(request, "display-rate:" + user.id, 240, 3600)
        try:
            return security.display_rates.get(currency).public()
        except ProviderError as exc:
            raise HTTPException(503, "A current rate is unavailable for this currency.") from exc

    @app.post("/api/clans/{clan_id}/deposit-quote")
    @app.post("/api/clans/{clan_id}/grant-quote")
    def grant_quote(clan_id: str, data: GrantQuoteInput, request: Request):
        from clans.display_rates import make_grant_quote

        security.limit(request, "grant-quote", 120, 3600)
        with security.db() as db:
            user = security.current(request, db)
            membership(db, clan_id, user.id)
            return make_grant_quote(security, user.id, clan_id, data.currency, data.amount)

    @app.post("/api/clans/{clan_id}/grants")
    def grant_request(clan_id: str, data: GrantInput, request: Request):
        security.limit(request, "grant-create", 30, 3600)
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)

            def perform():
                from clans.display_rates import read_grant_quote

                quoted = (
                    read_grant_quote(security, data.quote, user.id, clan_id) if data.quote else None
                )
                amount_sats = quoted["amount_sats"] if quoted else data.amount_sats
                if db.scalar(
                    select(Grant.id).where(
                        Grant.beneficiary_id == user.id,
                        Grant.status.not_in(["recovered", "rejected", "cancelled"]),
                    )
                ):
                    raise HTTPException(
                        409, "Finish your current grant and repay it before asking for another."
                    )
                policy = db.scalar(
                    select(PolicyVersion)
                    .where(PolicyVersion.clan_id == clan_id)
                    .order_by(PolicyVersion.version.desc())
                )
                members = db.scalars(
                    select(Membership).where(
                        Membership.clan_id == clan_id, Membership.active.is_(True)
                    )
                ).all()
                voters = [m.user_id for m in members if m.user_id != user.id]
                signers = [m.user_id for m in members if m.is_signer and m.user_id != user.id]
                config = db.get(ClanConfig, clan_id)
                if (
                    sum(m.is_signer for m in members) != config.target_signers
                    or len(voters) < policy.member_vote_quorum
                    or len(signers) < policy.signer_threshold
                ):
                    raise HTTPException(
                        409,
                        "Finish inviting the signatories and enough voting members before "
                        "requesting a grant. A beneficiary cannot approve their own request.",
                    )
                # Asked for in KES: the member owes the KES they asked for (in cents). The
                # sats paid out stay fixed at the quote. The debt starts once it's paid.
                in_kes = bool(quoted) and quoted["currency"] == "KES"
                grant = Grant(
                    id=new_id(),
                    clan_id=clan_id,
                    beneficiary_id=user.id,
                    purpose=data.purpose,
                    amount_sats=amount_sats,
                    obligation_currency="KES" if in_kes else "BTC",
                    principal_minor=quoted["amount_minor"] if in_kes else amount_sats,
                    outstanding_minor=0,
                    policy_snapshot={
                        "version": policy.version,
                        "quorum": policy.member_vote_quorum,
                        "threshold": policy.signer_threshold,
                        "currency": "KES" if in_kes else "BTC",
                        **({"request_value": quoted} if quoted else {}),
                    },
                    eligible_voters=voters,
                    eligible_signers=signers,
                )
                db.add(grant)
                audit(
                    db,
                    clan_id,
                    user.id,
                    "grant_requested",
                    grant_id=grant.id,
                    amount_sats=amount_sats,
                    **({"request_value": quoted} if quoted else {}),
                )
                return {"grant_id": grant.id}

            return operation(db, request, user, "grant:" + clan_id, data.model_dump(), perform)

    @app.post("/api/clans/{clan_id}/grants/{grant_id}/vote")
    def vote(clan_id: str, grant_id: str, data: VoteInput, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)
            grant = db.get(Grant, grant_id)
            if not grant or grant.clan_id != clan_id:
                raise HTTPException(404, "Grant not found.")
            previous = db.scalar(
                select(Vote).where(Vote.grant_id == grant_id, Vote.user_id == user.id)
            )
            if previous and previous.choice == data.choice:
                return {"status": grant.status}
            if (
                previous
                or grant.status != "voting"
                or user.id not in grant.eligible_voters
                or user.id == grant.beneficiary_id
            ):
                raise HTTPException(
                    409, "You cannot vote on this request, or your vote is already recorded."
                )
            db.add(Vote(grant_id=grant.id, user_id=user.id, choice=data.choice))
            db.flush()
            votes = db.scalars(select(Vote).where(Vote.grant_id == grant.id)).all()
            approvals = sum(v.choice == "approve" for v in votes)
            if (
                approvals >= grant.policy_snapshot["quorum"]
                and approvals > len(grant.eligible_voters) // 2
            ):
                grant.status = "awaiting_acceptance"
            elif len(votes) == len(grant.eligible_voters):
                grant.status = "rejected"
            audit(
                db,
                clan_id,
                user.id,
                "grant_vote_cast",
                grant_id=grant.id,
                choice=data.choice,
                status=grant.status,
            )
            return {"status": grant.status}

    @app.post("/api/clans/{clan_id}/grants/{grant_id}/accept")
    def accept_grant(clan_id: str, grant_id: str, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)
            grant = db.get(Grant, grant_id)
            if not grant or grant.clan_id != clan_id:
                raise HTTPException(404, "Grant not found.")
            if grant.beneficiary_id != user.id:
                raise HTTPException(403, "Only the beneficiary can accept this grant.")
            if grant.accepted_at:
                return {"status": grant.status}
            if grant.status != "awaiting_acceptance":
                raise HTTPException(409, "The member vote must pass before acceptance.")
            grant.accepted_at = now_iso()
            grant.status = "awaiting_funding"
            audit(
                db,
                clan_id,
                user.id,
                "grant_accepted",
                grant_id=grant.id,
                principal_sats=grant.amount_sats,
                **(
                    {"principal_kes_minor": grant.principal_minor}
                    if grant.obligation_currency == "KES"
                    else {}
                ),
            )
            return {"status": grant.status}

    @app.post("/api/clans/{clan_id}/grants/{grant_id}/cancel")
    def cancel_grant(clan_id: str, grant_id: str, request: Request):
        with security.db() as db:
            user = security.current(request, db)
            lock_clan(db, clan_id)
            membership(db, clan_id, user.id)
            grant = db.get(Grant, grant_id)
            if not grant or grant.clan_id != clan_id:
                raise HTTPException(404, "Grant not found.")
            if grant.beneficiary_id != user.id:
                raise HTTPException(403, "Only the beneficiary can withdraw this request.")
            if grant.status == "cancelled":
                return {"status": grant.status}
            if grant.status not in {
                "voting",
                "awaiting_acceptance",
                "awaiting_funding",
                "awaiting_signatures",
            }:
                raise HTTPException(409, "This request cannot be withdrawn.")
            from clans.money_service import ensure_invoice_change_allowed

            ensure_invoice_change_allowed(db, grant)
            grant.status = "cancelled"
            audit(db, clan_id, user.id, "grant_cancelled", grant_id=grant.id)
            return {"status": grant.status}

    @app.get("/api/account/security")
    def account_security(request: Request):
        with security.db() as db:
            user = security.current(request, db)
            return {
                "passkeys": [
                    {
                        "id": p.id,
                        "label": p.label,
                        "backed_up": p.backed_up,
                        "created_at": p.created_at,
                    }
                    for p in db.scalars(
                        select(Passkey).where(Passkey.user_id == user.id, Passkey.active.is_(True))
                    )
                ],
                "recovery_codes_remaining": db.scalar(
                    select(func.count())
                    .select_from(RecoveryCode)
                    .where(RecoveryCode.user_id == user.id, RecoveryCode.used.is_(False))
                ),
            }

    from clans.money_api import install as install_treasury

    install_treasury(app, security, settings)
    from clans.access_api import install as install_access

    install_access(app, security, settings)

    from clans.activity_api import install as install_activity

    install_activity(app, security)
    from clans.wallet_api import install as install_wallets

    install_wallets(app, security, settings)
    from clans.wallet_money_api import install as install_wallet_money

    install_wallet_money(app, security, settings)

    if settings.static_directory:
        root = settings.static_directory.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith(("api/", "health/", "__demo", ".")):
                raise HTTPException(404, "Not found.")
            candidate = (root / path).resolve()
            if not candidate.is_relative_to(root):
                raise HTTPException(404, "Not found.")
            if candidate.is_file():
                return FileResponse(
                    candidate,
                    headers={
                        "Cache-Control": "no-cache"
                        if path in {"sw.js", "manifest.webmanifest"}
                        else "public, max-age=3600"
                    },
                )
            directory_index = (candidate / "index.html").resolve()
            if (
                candidate.is_dir()
                and directory_index.is_relative_to(root)
                and directory_index.is_file()
            ):
                return FileResponse(directory_index, headers={"Cache-Control": "no-cache"})
            if Path(path).suffix:
                raise HTTPException(404, "Not found.")
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app
