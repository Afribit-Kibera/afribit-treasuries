"""Grant generator checks plus opt-in PostgreSQL role enforcement.

Integration requires the existing disposable afribit_clans_tests database AND an
explicit CLANS_TEST_ROLE_ADMIN_URL for that same database. Never use a live DB.
"""

import os
import secrets

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from clans.database_roles import runtime_grants


@pytest.mark.parametrize("value", ["role;DROP TABLE users", "Role", "a'--", "", "a" * 64])
def test_role_identifiers_cannot_inject_sql(value):
    with pytest.raises(ValueError):
        runtime_grants(value, "valid_worker")


def test_roles_cannot_be_shared():
    with pytest.raises(ValueError):
        runtime_grants("shared", "shared")


def test_worker_cannot_read_recovery_material_or_replace_signer_keys():
    sql = runtime_grants("audit_web", "audit_worker")
    assert "GRANT SELECT (id,user_id,status,expires_at) ON account_access_recoveries" in sql
    assert 'GRANT UPDATE ON "passkeys"' not in sql
    assert "GRANT UPDATE (last_used_at) ON passkeys" in sql
    assert 'GRANT SELECT,INSERT,UPDATE ON "treasury_entries"' not in sql
    assert "GRANT SELECT (payout_id) ON treasury_dispatch_authorizations TO" in sql
    assert "Dispatched payout is worker controlled" in sql


def test_postgres_runtime_privileges(money):
    app, worker_instance, network = money
    admin_url = os.environ.get("CLANS_TEST_ROLE_ADMIN_URL")
    if not admin_url or app.state.security.engine.dialect.name != "postgresql":
        pytest.skip("Requires opt-in disposable PostgreSQL role-admin connection")
    actual, expected = make_url(admin_url), app.state.security.engine.url
    assert actual.database == expected.database == "afribit_clans_tests"
    assert (actual.host, actual.port) == (expected.host, expected.port)
    engine = create_engine(admin_url, hide_parameters=True)
    web, worker = "audit_web_" + secrets.token_hex(6), "audit_worker_" + secrets.token_hex(6)
    web_engine, worker_engine = None, None
    old_web_engine = app.state.security.engine
    old_worker_engine = worker_instance.security.engine
    try:
        with engine.begin() as connection:
            # Metadata fixtures do not create Alembic's own version table.
            connection.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32) PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                f"CREATE ROLE {web} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
            )
            connection.exec_driver_sql(
                f"CREATE ROLE {worker} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
            )
            connection.exec_driver_sql(runtime_grants(web, worker))
        for role, denied in [
            (web, "SELECT authentication_tag FROM treasury_dispatch_authorizations"),
            (web, "UPDATE treasury_balances SET balance_msat=100"),
            (web, "INSERT INTO treasury_dispatch_authorizations (payout_id) VALUES ('x')"),
            (web, "UPDATE incoming_payments SET clan_id='forged'"),
            (web, "UPDATE incoming_payments SET grant_id=NULL"),
            (web, "UPDATE incoming_payments SET provider_invoice_id='forged'"),
            (web, "INSERT INTO incoming_payments (provider_invoice_id) VALUES ('forged')"),
            (web, "SELECT * FROM treasury_receive_authorizations"),
            (web, "SELECT * FROM treasury_payout_polls"),
            (web, "INSERT INTO treasury_payout_polls (payout_id) VALUES ('x')"),
            (web, "UPDATE treasury_payout_polls SET next_attempt_at='1970'"),
            (web, "INSERT INTO treasury_receive_authorizations (incoming_id) VALUES ('x')"),
            (web, "UPDATE audit_events SET event_type='forged'"),
            (worker, "UPDATE treasury_receive_authorizations SET authentication_tag='forged'"),
            (worker, "DELETE FROM treasury_receive_invoices"),
            (worker, "SELECT * FROM login_sessions"),
            (worker, "SELECT * FROM recovery_codes"),
            (worker, "SELECT public_key FROM account_access_recoveries"),
            (worker, "UPDATE passkeys SET public_key='forged'"),
            (web, "CREATE TABLE public.audit_forbidden (id int)"),
            # Clan wallets: only the chain watcher credits, builds and broadcasts.
            (web, "UPDATE clan_wallet_payouts SET status='broadcast'"),
            (web, "UPDATE clan_wallet_receipts SET status='confirmed'"),
            (web, "INSERT INTO clan_wallet_alarms (id) VALUES ('x')"),
            (web, "DELETE FROM clan_wallet_alarms"),
            (worker, "UPDATE clan_wallets SET descriptor_external='forged'"),
            (worker, "UPDATE clan_wallet_keys SET key_expression='forged'"),
            (worker, "DELETE FROM clan_wallet_confirmations"),
            (worker, "UPDATE clan_wallet_payout_requests SET address='forged'"),
        ]:
            with engine.connect() as connection, connection.begin():
                connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
                with pytest.raises(DBAPIError) as denied_error:
                    connection.exec_driver_sql(denied)
                assert denied_error.value.orig.sqlstate == "42501"
                connection.rollback()
        with engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL ROLE {worker}")
            connection.exec_driver_sql(
                "SELECT id,user_id,status,expires_at FROM account_access_recoveries LIMIT 1"
            )
        with engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL ROLE {web}")
            connection.execute(text("SELECT balance_msat FROM treasury_balances LIMIT 1"))
            connection.exec_driver_sql("DELETE FROM clan_wallet_confirmations WHERE false")
        with engine.begin() as connection:
            connection.exec_driver_sql(f"SET LOCAL ROLE {worker}")
            connection.exec_driver_sql("UPDATE clan_wallets SET balance_sats=0 WHERE false")
            connection.exec_driver_sql(
                "UPDATE clan_wallet_payout_requests SET wallet_id=wallet_id WHERE false"
            )

        def role_engine(role):
            runtime = create_engine(admin_url, hide_parameters=True)

            @event.listens_for(runtime, "connect")
            def set_role(connection, _):
                with connection.cursor() as cursor:
                    cursor.execute(f"SET ROLE {role}")
                connection.commit()

            return runtime

        # Exercise the real account, deposit, vote, signature and settlement path
        # using the exact restricted roles, not an unrestricted DB-owner fixture.
        web_engine, worker_engine = role_engine(web), role_engine(worker)
        app.state.security.engine = web_engine
        worker_instance.security.engine = worker_engine
        from test_money import approve, prepared

        data = prepared(money)
        # Even an existing, correctly requested invoice cannot be relabelled.
        with engine.connect() as connection, connection.begin():
            connection.exec_driver_sql(f"SET LOCAL ROLE {web}")
            with pytest.raises(DBAPIError):
                connection.exec_driver_sql("UPDATE incoming_payments SET amount_sats=1")
            connection.rollback()
        approve(data[2], data[3], data[8])
        approve(data[4], data[5], data[8])
        worker_instance.tick()
        assert network.pay_calls == 1
        assert data[0].get(f"/api/clans/{data[6]}").json()["reserved_msat"] == "0"
    finally:
        app.state.security.engine = old_web_engine
        worker_instance.security.engine = old_worker_engine
        for runtime in [web_engine, worker_engine]:
            if runtime is not None:
                runtime.dispose()
        with engine.begin() as connection:
            for role in [web, worker]:
                connection.exec_driver_sql(f"DROP OWNED BY {role}")
                connection.exec_driver_sql(f"DROP ROLE IF EXISTS {role}")
        engine.dispose()


# Reuse the disposable-database safety guard from production tests.
from test_live_app import live as live  # noqa: E402
from test_money import money as money  # noqa: E402


def test_the_sqlite_grant_checker_catches_a_missing_grant():
    """Wallet tests rely on this to find grants that only PostgreSQL would enforce."""
    from role_grants import GrantChecker

    checker = GrantChecker()
    engine = create_engine("sqlite://")
    checker.watch(engine, "web")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE treasury_balances (balance_msat int, reserved_msat int)"
        )
        connection.exec_driver_sql("CREATE TABLE treasury_entries (id int)")
        connection.exec_driver_sql("SELECT balance_msat FROM treasury_balances")
        connection.exec_driver_sql("UPDATE treasury_balances SET reserved_msat=1")
        assert checker.violations == []
        connection.exec_driver_sql("UPDATE treasury_balances SET balance_msat=1")
        connection.exec_driver_sql("INSERT INTO treasury_entries (id) VALUES (1)")
    engine.dispose()
    assert sorted(checker.violations) == [
        "web has no INSERT on treasury_entries",
        "web has no UPDATE (balance_msat) on treasury_balances",
    ]
