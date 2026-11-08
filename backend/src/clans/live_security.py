"""Origin-bound sessions and WebAuthn ceremonies for the standalone application."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from contextlib import contextmanager

from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from clans.db import make_engine
from clans.live_config import LiveSettings
from clans.live_models import (
    AuthChallenge,
    LoginSession,
    Passkey,
    Profile,
    RateLimit,
    RecoveryCode,
    after,
)
from clans.models import User, new_id, now_iso


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Security:
    def __init__(self, settings: LiveSettings):
        self.settings = settings
        self.engine = make_engine(settings.database_url.get_secret_value())

    @contextmanager
    def db(self):
        with Session(self.engine, expire_on_commit=False) as db, db.begin():
            yield db

    def mac(self, value: str) -> str:
        return hmac.new(
            self.settings.session_secret.get_secret_value().encode(), value.encode(), "sha256"
        ).hexdigest()

    def origin(self, request: Request):
        if request.headers.get("origin") != self.settings.public_origin:
            raise HTTPException(403, "Open Clans on its own secure website and try again.")
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "JSON is required.")

    def limit(
        self, request: Request, scope: str, maximum: int = 30, seconds: int = 300, *, identity=None
    ):
        # The reverse proxy is the only trusted source of the client address.
        address = request.client.host if request.client else "unknown"
        key = self.mac(scope + ":" + ("identity:" + identity if identity else "ip:" + address))
        now = int(time.time())
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        from sqlalchemy import case

        statement = insert(RateLimit).values(key=key, count=1, resets_at=now + seconds)
        statement = statement.on_conflict_do_update(
            index_elements=[RateLimit.key],
            set_={
                "count": case((RateLimit.resets_at <= now, 1), else_=RateLimit.count + 1),
                "resets_at": case(
                    (RateLimit.resets_at <= now, now + seconds), else_=RateLimit.resets_at
                ),
            },
        ).returning(RateLimit.count)
        with self.db() as db:
            count = db.execute(statement).scalar_one()
        if count > maximum:
            raise HTTPException(429, "Too many attempts. Please wait a few minutes.")

    def current(self, request: Request, db: Session, *, optional=False) -> User | None:
        token = request.cookies.get(self.settings.cookie_name, "")
        session = (
            db.scalar(
                select(LoginSession).where(
                    LoginSession.token_hash == digest(token),
                    LoginSession.revoked.is_(False),
                    LoginSession.expires_at > now_iso(),
                )
            )
            if token
            else None
        )
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
        if session and unsafe:
            # Serialize authenticated mutations with recovery. Recheck the session after
            # acquiring the account lock so a waiting request cannot outlive revocation.
            user = db.scalar(select(User).where(User.id == session.user_id).with_for_update())
            db.refresh(session)
            if session.revoked or session.expires_at <= now_iso():
                user = None
        else:
            user = db.get(User, session.user_id) if session else None
        if not user or not user.active or user.is_test_user or not db.get(Profile, user.id):
            if optional:
                return None
            raise HTTPException(401, "Sign in to continue.")
        if unsafe:
            self.origin(request)
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), self.mac(token)):
                raise HTTPException(403, "Your session changed. Refresh Clans and try again.")
            if not request.url.path.startswith(("/api/account/", "/api/auth/", "/api/onboarding/")):
                from clans.recovery_models import Contact

                if not db.get(Contact, user.id):
                    raise HTTPException(403, "Add your phone number in Profile first.")
        return user

    def issue_session(self, db: Session, response: Response, user_id: str):
        token = secrets.token_urlsafe(48)
        db.add(
            LoginSession(
                token_hash=digest(token),
                user_id=user_id,
                expires_at=after(self.settings.session_days * 86400),
            )
        )
        response.set_cookie(
            self.settings.cookie_name,
            token,
            max_age=self.settings.session_days * 86400,
            httponly=True,
            secure=self.settings.secure_cookies,
            samesite="lax",
            path="/",
        )
        response.delete_cookie(
            self.settings.challenge_cookie, path="/", secure=self.settings.secure_cookies
        )

    def challenge(
        self,
        db,
        response,
        kind,
        *,
        user_id=None,
        payload=None,
        registration=False,
        challenge_bytes=None,
    ):
        binding = secrets.token_urlsafe(32)
        challenge = challenge_bytes or secrets.token_bytes(32)
        record = AuthChallenge(
            binding_hash=digest(binding),
            kind=kind,
            user_id=user_id,
            payload=payload or {},
            challenge=b64(challenge),
            expires_at=after(300),
        )
        db.add(record)
        db.flush()
        response.set_cookie(
            self.settings.challenge_cookie,
            binding,
            max_age=300,
            httponly=True,
            secure=self.settings.secure_cookies,
            samesite="strict",
            path="/",
        )
        if registration:
            options = generate_registration_options(
                rp_id=self.settings.rp_id,
                rp_name="AfriBit Clans",
                user_name=record.payload["handle"],
                user_display_name=record.payload["display_name"],
                user_id=unb64(record.payload["passkey_handle"]),
                challenge=challenge,
                authenticator_selection=AuthenticatorSelectionCriteria(
                    resident_key=ResidentKeyRequirement.REQUIRED,
                    user_verification=UserVerificationRequirement.REQUIRED,
                ),
            )
        else:
            options = generate_authentication_options(
                rp_id=self.settings.rp_id,
                challenge=challenge,
                user_verification=UserVerificationRequirement.REQUIRED,
            )
        return {"challenge_id": record.id, "options": json.loads(options_to_json(options))}

    def take_challenge(self, db, request, challenge_id, kind):
        record = db.scalar(
            select(AuthChallenge).where(AuthChallenge.id == challenge_id).with_for_update()
        )
        if (
            not record
            or record.kind != kind
            or record.consumed
            or record.expires_at <= now_iso()
            or not hmac.compare_digest(
                record.binding_hash, digest(request.cookies.get(self.settings.challenge_cookie, ""))
            )
        ):
            self.limit(request, "invalid-ceremony:" + kind, 120, 300)
            raise HTTPException(400, "This passkey request expired. Please start again.")
        # A missing challenge or wrong cookie never spends a member's quota.
        # Challenge quotas apply across addresses; options routes retain IP limits.
        self.limit(request, "ceremony:" + kind, 5, 300, identity=record.id)
        if record.user_id and kind not in {"access-register", "access-resume"}:
            self.limit(request, "account-ceremony:" + kind, 60, 300, identity=record.user_id)
        record.consumed = True
        return record

    def registration(self, credential: dict, record: AuthChallenge):
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=unb64(record.challenge),
                expected_rp_id=self.settings.rp_id,
                expected_origin=self.settings.public_origin,
                require_user_verification=True,
            )
            if len(verified.credential_id) > 512:
                raise ValueError("Credential is too long")
            return verified
        except Exception as exc:
            raise HTTPException(400, "Passkey verification failed. Please try again.") from exc

    def assertion(self, db, credential, record, expected_user=None):
        key = db.scalar(
            select(Passkey)
            .where(Passkey.credential_id == credential.get("id", ""), Passkey.active.is_(True))
            .with_for_update()
        )
        if not key or (expected_user and key.user_id != expected_user):
            raise HTTPException(400, "Use the passkey belonging to this account.")
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=unb64(record.challenge),
                expected_rp_id=self.settings.rp_id,
                expected_origin=self.settings.public_origin,
                credential_public_key=unb64(key.public_key),
                credential_current_sign_count=key.sign_count,
                require_user_verification=True,
            )
        except Exception as exc:
            raise HTTPException(400, "Passkey verification failed. Please try again.") from exc
        key.sign_count = verified.new_sign_count
        key.backed_up = verified.credential_backed_up
        key.last_used_at = now_iso()
        return key

    def recovery_codes(self, db, user_id):
        from clans.recovery_words import generate, hash_input

        self.cancel_access_requests(db, user_id)
        codes = [generate()]
        for code in codes:
            db.add(RecoveryCode(user_id=user_id, code_hash=self.mac(hash_input(code))))
        return codes

    def add_key(self, db, user_id, verified):
        # This lock is also taken by recovery/current(), serializing all insertions.
        db.scalar(select(User).where(User.id == user_id).with_for_update())
        from sqlalchemy import func

        count = db.scalar(
            select(func.count())
            .select_from(Passkey)
            .where(Passkey.user_id == user_id, Passkey.active.is_(True))
        )
        if count >= 10:
            raise HTTPException(409, "This account already has ten passkeys.")
        self.cancel_access_requests(db, user_id)
        db.add(
            Passkey(
                user_id=user_id,
                credential_id=b64(verified.credential_id),
                public_key=b64(verified.credential_public_key),
                sign_count=verified.sign_count,
                backed_up=verified.credential_backed_up,
            )
        )

    @staticmethod
    def cancel_access_requests(db, user_id):
        from sqlalchemy import update

        from clans.recovery_models import AccessRecovery

        db.execute(
            update(AccessRecovery)
            .where(
                AccessRecovery.user_id == user_id,
                AccessRecovery.status.in_(["pending", "waiting"]),
            )
            .values(status="cancelled")
        )

    def registration_payload(self, name):
        return {
            "display_name": name,
            "handle": "clan-" + secrets.token_hex(6),
            "passkey_handle": b64(secrets.token_bytes(32)),
            "user_id": new_id(),
        }
