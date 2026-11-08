import hashlib
from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from clans import __version__
from clans.config import Settings
from clans.db import Base, make_engine
from clans.models import AuditEvent, Clan, Membership, PolicyVersion, User
from clans.payments import BtcpayProbe, ProviderUnavailable
from clans.schemas import (
    ClanView,
    CreateClan,
    ErrorResponse,
    HealthView,
    MemberView,
    PolicyView,
    ProviderHealth,
    UserView,
)
from clans.simulation import (
    Command,
    SimulationCommandRecord,
    SimulationError,
    SimulationRun,
    SimulationView,
    StartSimulation,
    digest,
    initial_state,
    transition,
)

bearer = HTTPBearer(auto_error=False, description="Internal demo user token; not production login")


def failure(status: int, code: str, message: str) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return HTTPException(
        status_code=status, detail={"code": code, "message": message}, headers=headers
    )


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    config = settings or Settings()
    config.prepare_local_directory()
    owned_engine = engine is None
    db_engine = engine or make_engine(config.database_url.get_secret_value())
    factory = sessionmaker(db_engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Auto-create only the disposable SQLite schema. PostgreSQL needs explicit initialization.
        if db_engine.dialect.name == "sqlite":
            Base.metadata.create_all(db_engine)
        yield
        if owned_engine:
            db_engine.dispose()

    app = FastAPI(
        title="Afribit Clans API",
        version=__version__,
        description=(
            "Backend pilot: clan membership and initial governance policy. "
            "Demo authentication is opt-in. Payment execution is not implemented."
        ),
        lifespan=lifespan,
        responses={s: {"model": ErrorResponse} for s in [401, 403, 404, 409, 422, 503]},
    )
    app.state.engine = db_engine
    app.state.settings = config

    @app.exception_handler(HTTPException)
    async def handle_http(_request: Request, exc: HTTPException):
        detail = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {"code": "request_failed", "message": str(exc.detail)}
        )
        return JSONResponse({"error": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_request: Request, _exc: RequestValidationError):
        return JSONResponse(
            {"error": {"code": "validation_error", "message": "Request fields are invalid"}},
            status_code=422,
        )

    def database() -> Iterator[Session]:
        with factory() as session:
            yield session

    def current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
        session: Session = Depends(database),
    ) -> User:
        if not config.demo_auth_enabled:
            raise failure(503, "demo_auth_disabled", "Demo authentication is disabled")
        if credentials is None:
            raise failure(401, "unauthorized", "A valid demo bearer token is required")
        digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        user = session.scalar(
            select(User).where(
                User.demo_token_hash == digest, User.active.is_(True), User.is_test_user.is_(True)
            )
        )
        if user is None:
            raise failure(401, "unauthorized", "A valid demo bearer token is required")
        return user

    def membership(session: Session, clan_id: str, user_id: str) -> Membership:
        row = session.scalar(
            select(Membership).where(
                Membership.clan_id == clan_id,
                Membership.user_id == user_id,
                Membership.active.is_(True),
            )
        )
        if row is None:
            # Do not disclose whether another clan exists to an outsider.
            raise failure(404, "clan_not_found", "Clan was not found")
        return row

    def clan_view(session: Session, clan: Clan) -> ClanView:
        policy = session.scalar(
            select(PolicyVersion)
            .where(PolicyVersion.clan_id == clan.id)
            .order_by(PolicyVersion.version.desc())
            .limit(1)
        )
        count, signers = session.execute(
            select(
                func.count(Membership.id),
                func.count(Membership.id).filter(Membership.is_signer.is_(True)),
            )
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.clan_id == clan.id, Membership.active.is_(True), User.active.is_(True)
            )
        ).one()
        return ClanView(
            id=clan.id,
            name=clan.name,
            status=clan.status,
            created_at=clan.created_at,
            policy=PolicyView.model_validate(policy),
            member_count=count,
            signer_count=signers,
            governance_ready=count >= policy.member_vote_quorum
            and signers >= policy.signer_threshold,
        )

    @app.get("/health", response_model=HealthView, tags=["System"])
    def health() -> HealthView:
        return HealthView(version=__version__, demo_auth_enabled=config.demo_auth_enabled)

    @app.get("/api/v1/me", response_model=UserView, tags=["Identity"])
    def me(user: User = Depends(current_user)) -> UserView:
        return UserView.model_validate(user)

    @app.get("/api/v1/clans", response_model=list[ClanView], tags=["Clans"])
    def list_clans(
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        user: User = Depends(current_user),
        session: Session = Depends(database),
    ) -> list[ClanView]:
        rows = session.scalars(
            select(Clan)
            .join(Membership)
            .where(Membership.user_id == user.id, Membership.active.is_(True))
            .order_by(Clan.created_at, Clan.id)
            .offset(offset)
            .limit(limit)
        )
        return [clan_view(session, clan) for clan in rows]

    @app.post("/api/v1/clans", response_model=ClanView, status_code=201, tags=["Clans"])
    def create_clan(
        body: CreateClan,
        user: User = Depends(current_user),
        session: Session = Depends(database),
    ) -> ClanView:
        session.scalar(select(User).where(User.id == user.id).with_for_update())
        if session.scalar(
            select(Membership.id).where(Membership.user_id == user.id, Membership.active.is_(True))
        ):
            raise failure(409, "already_in_clan", "An account can belong to one clan at a time.")
        clan = Clan(name=body.name, created_by=user.id)
        session.add(clan)
        session.flush()
        session.add_all(
            [
                Membership(clan_id=clan.id, user_id=user.id, role="organizer", is_signer=False),
                PolicyVersion(clan_id=clan.id, **body.policy.model_dump()),
                AuditEvent(
                    clan_id=clan.id,
                    actor_id=user.id,
                    event_type="clan.created",
                    payload={
                        "name": clan.name,
                        "policy_version": 1,
                    },
                ),
            ]
        )
        session.commit()
        return clan_view(session, clan)

    @app.get("/api/v1/clans/{clan_id}", response_model=ClanView, tags=["Clans"])
    def get_clan(
        clan_id: str,
        user: User = Depends(current_user),
        session: Session = Depends(database),
    ) -> ClanView:
        membership(session, clan_id, user.id)
        return clan_view(session, session.get(Clan, clan_id))

    @app.get("/api/v1/clans/{clan_id}/members", response_model=list[MemberView], tags=["Clans"])
    def members(
        clan_id: str,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        user: User = Depends(current_user),
        session: Session = Depends(database),
    ) -> list[MemberView]:
        membership(session, clan_id, user.id)
        rows = session.execute(
            select(Membership, User)
            .join(User)
            .where(
                Membership.clan_id == clan_id, Membership.active.is_(True), User.active.is_(True)
            )
            .order_by(User.display_name, User.id)
            .offset(offset)
            .limit(limit)
        )
        return [
            MemberView(user=UserView.model_validate(u), role=m.role, is_signer=m.is_signer)
            for m, u in rows
        ]

    @app.get("/api/v1/system/btcpay/health", response_model=ProviderHealth, tags=["System"])
    def provider_health(_user: User = Depends(current_user)) -> ProviderHealth:
        try:
            return BtcpayProbe(config.btcpay_url, config.provider_timeout_seconds).health()
        except ProviderUnavailable as exc:
            raise failure(
                503, "provider_unavailable", "BTCPay health could not be verified"
            ) from exc

    def simulation_access(session: Session, clan_id: str, user: User) -> None:
        if not config.simulation_enabled:
            raise failure(503, "simulation_disabled", "Simulation commands are disabled")
        membership(session, clan_id, user.id)

    def active_roster(session: Session, clan_id: str) -> list[dict]:
        rows = session.execute(
            select(Membership, User)
            .join(User)
            .where(
                Membership.clan_id == clan_id,
                Membership.active.is_(True),
                User.active.is_(True),
            )
        )
        return [{"user_id": u.id, "is_signer": m.is_signer} for m, u in rows]

    def simulation_view(run: SimulationRun) -> dict:
        return SimulationView(
            id=run.id, clan_id=run.clan_id, revision=run.revision, state=run.state
        ).model_dump()

    @app.post(
        "/api/v1/clans/{clan_id}/simulations",
        response_model=SimulationView,
        status_code=201,
        tags=["Simulation"],
    )
    def start_simulation(
        clan_id: str,
        body: StartSimulation,
        idempotency_key: str = Header(min_length=1, max_length=100, alias="Idempotency-Key"),
        user: User = Depends(current_user),
        session: Session = Depends(database),
    ):
        simulation_access(session, clan_id, user)
        # Creation is serialized by a no-op clan-row update. Command records make retry durable.
        try:
            session.execute(update(Clan).where(Clan.id == clan_id).values(status=Clan.status))
            request_hash = digest({"create_simulation": body.model_dump(), "clan_id": clan_id})
            previous = session.scalar(
                select(SimulationCommandRecord)
                .join(SimulationRun)
                .where(
                    SimulationRun.clan_id == clan_id,
                    SimulationCommandRecord.actor_id == user.id,
                    SimulationCommandRecord.idempotency_key == "start:" + idempotency_key,
                )
            )
            if previous:
                if previous.request_sha256 != request_hash:
                    raise failure(409, "idempotency_conflict", "Key was used with different input")
                return previous.response
            policy = session.scalar(
                select(PolicyVersion)
                .where(PolicyVersion.clan_id == clan_id)
                .order_by(PolicyVersion.version.desc())
                .limit(1)
            )
            run = SimulationRun(
                clan_id=clan_id,
                created_by=user.id,
                state=initial_state(
                    body.name,
                    PolicyView.model_validate(policy).model_dump(),
                    active_roster(session, clan_id),
                ),
            )
            session.add(run)
            session.flush()
            response = simulation_view(run)
            session.add(
                SimulationCommandRecord(
                    run_id=run.id,
                    actor_id=user.id,
                    idempotency_key="start:" + idempotency_key,
                    request_sha256=request_hash,
                    response=response,
                )
            )
            session.commit()
            return response
        except (IntegrityError, OperationalError) as exc:
            session.rollback()
            raise failure(409, "concurrent_update", "Retry with the same idempotency key") from exc

    @app.get(
        "/api/v1/clans/{clan_id}/simulations/{run_id}",
        response_model=SimulationView,
        tags=["Simulation"],
    )
    def get_simulation(
        clan_id: str,
        run_id: str,
        user: User = Depends(current_user),
        session: Session = Depends(database),
    ):
        simulation_access(session, clan_id, user)
        run = session.scalar(
            select(SimulationRun).where(
                SimulationRun.id == run_id, SimulationRun.clan_id == clan_id
            )
        )
        if run is None:
            raise failure(404, "simulation_not_found", "Simulation not found")
        return simulation_view(run)

    @app.post(
        "/api/v1/clans/{clan_id}/simulations/{run_id}/commands",
        response_model=SimulationView,
        tags=["Simulation"],
    )
    def simulation_command(
        clan_id: str,
        run_id: str,
        body: Command,
        idempotency_key: str = Header(min_length=1, max_length=100, alias="Idempotency-Key"),
        user: User = Depends(current_user),
        session: Session = Depends(database),
    ):
        simulation_access(session, clan_id, user)
        try:
            run = session.scalar(
                select(SimulationRun).where(
                    SimulationRun.id == run_id, SimulationRun.clan_id == clan_id
                )
            )
            if run is None:
                raise failure(404, "simulation_not_found", "Simulation not found")
            request_hash = digest(body.model_dump())
            record_key = "command:" + idempotency_key
            previous = session.scalar(
                select(SimulationCommandRecord).where(
                    SimulationCommandRecord.run_id == run_id,
                    SimulationCommandRecord.actor_id == user.id,
                    SimulationCommandRecord.idempotency_key == record_key,
                )
            )
            if previous:
                if previous.request_sha256 != request_hash:
                    raise failure(409, "idempotency_conflict", "Key was used with different input")
                return previous.response
            roster = active_roster(session, clan_id)
            synthetic = set(
                session.scalars(
                    select(User.id).where(User.active.is_(True), User.is_test_user.is_(True))
                )
            )
            # Pure transition produces no external side effects. CAS prevents lost writes.
            state = transition(
                run.state,
                body,
                user.id,
                {m["user_id"] for m in roster},
                {m["user_id"] for m in roster if m["is_signer"]},
                synthetic,
            )
            revision = run.revision
            changed = session.execute(
                update(SimulationRun)
                .where(SimulationRun.id == run_id, SimulationRun.revision == revision)
                .values(state=state, revision=revision + 1),
                execution_options={"synchronize_session": False},
            )
            if changed.rowcount != 1:
                raise failure(409, "concurrent_update", "Retry with the same idempotency key")
            response = SimulationView(
                id=run.id, clan_id=clan_id, revision=revision + 1, state=state
            ).model_dump()
            session.add(
                SimulationCommandRecord(
                    run_id=run_id,
                    actor_id=user.id,
                    idempotency_key=record_key,
                    request_sha256=request_hash,
                    response=response,
                )
            )
            session.commit()
            return response
        except SimulationError as exc:
            session.rollback()
            raise failure(exc.status, exc.code, exc.message) from exc
        except (IntegrityError, OperationalError) as exc:
            session.rollback()
            raise failure(409, "concurrent_update", "Retry with the same idempotency key") from exc

    return app
