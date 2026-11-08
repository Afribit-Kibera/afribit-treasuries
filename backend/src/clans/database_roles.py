"""Reviewed PostgreSQL runtime grants; invoke only from operator provisioning.

The pre-existing database owner is the migration role. Neither runtime is a
member of it. This reduces web compromise impact; it does not establish an
independent signer-enrollment trust root or protect against a database admin.
"""

import re


def identifier(value):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError("Invalid PostgreSQL identifier")
    return '"' + value + '"'


WALLET_MONEY_TABLES = (
    "clan_wallet_addresses",
    "clan_wallet_receipts",
    "clan_wallet_payout_requests",
    "clan_wallet_payouts",
    "clan_wallet_signatures",
    "clan_wallet_alarms",
    "clan_wallet_chain_status",
)


def runtime_grants(web_role, worker_role):
    web, worker = identifier(web_role), identifier(worker_role)
    if web_role == worker_role:
        raise ValueError("Web and worker roles must differ")
    web_tables = [
        "users",
        "clans",
        "memberships",
        "clan_policy_versions",
        "account_profiles",
        "passkeys",
        "login_sessions",
        "auth_challenges",
        "recovery_codes",
        "request_limits",
        "clan_configurations",
        "clan_invitations",
        "clan_treasuries",
        "grant_proposals",
        "grant_votes",
        "payment_intents",
        "signer_approvals",
        "idempotent_operations",
        "account_contacts",
        "account_access_recoveries",
        "account_recovery_approvals",
        "account_recovery_clans",
        # Clan wallets hold public keys only; the web registers and confirms them.
        "clan_wallets",
        "clan_wallet_keys",
        "clan_wallet_confirmations",
    ]
    # Resolve names from metadata, never guess historical table spellings.
    from clans.live_models import ClanConfig, Invitation

    web_tables[web_tables.index("clan_configurations")] = ClanConfig.__tablename__
    web_tables[web_tables.index("clan_invitations")] = Invitation.__tablename__
    worker_select = [
        "users",
        "clans",
        "memberships",
        "clan_policy_versions",
        "grant_proposals",
        "grant_votes",
        "payment_intents",
        "signer_approvals",
        "passkeys",
        "incoming_payments",
        "treasury_balances",
        "treasury_entries",
        "treasury_receipts",
        "grant_debts",
        "treasury_payouts",
        "treasury_worker_status",
        "treasury_deposit_polls",
        "audit_events",
        "treasury_dispatch_authorizations",
        "treasury_receive_authorizations",
        "treasury_receive_invoices",
        "treasury_payout_polls",
        "clan_wallets",
        "clan_wallet_keys",
        *WALLET_MONEY_TABLES,
    ]
    worker_update = [
        "grant_proposals",
        "payment_intents",
        "incoming_payments",
        "treasury_balances",
        "treasury_payouts",
        "treasury_worker_status",
        "treasury_deposit_polls",
        "grant_debts",
        "treasury_payout_polls",
        "clan_wallet_receipts",
        "clan_wallet_payouts",
        "clan_wallet_chain_status",
    ]
    worker_insert = [
        "treasury_entries",
        "treasury_receipts",
        "grant_debts",
        "treasury_worker_status",
        "treasury_deposit_polls",
        "audit_events",
        "treasury_dispatch_authorizations",
        "treasury_receive_authorizations",
        "treasury_receive_invoices",
        "treasury_payout_polls",
        "clan_wallet_receipts",
        "clan_wallet_payouts",
        "clan_wallet_alarms",
        "clan_wallet_chain_status",
    ]

    def tables(names):
        return ",".join(identifier(n) for n in names)

    statements = [
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC;",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {web},{worker};",
        f"REVOKE ALL ON SCHEMA public FROM {web},{worker};",
        f"GRANT USAGE ON SCHEMA public TO {web},{worker};",
        f"GRANT SELECT,INSERT,UPDATE ON {tables(web_tables)} TO {web};",
        f"GRANT SELECT ON treasury_balances,treasury_entries,treasury_receipts,grant_debts,"
        f"treasury_payouts,treasury_worker_status,alembic_version TO {web};",
        f"GRANT INSERT ON treasury_balances,treasury_payouts TO {web};",
        f"GRANT SELECT ON incoming_payments,audit_events TO {web};",
        f"GRANT INSERT ON audit_events TO {web};",
        f"GRANT INSERT (id,clan_id,user_id,grant_id,method,amount_sats,status,"
        f"credited_sats,created_at) ON incoming_payments TO {web};",
        f"GRANT UPDATE (reserved_msat) ON treasury_balances TO {web};",
        f"GRANT UPDATE (status,last_error) ON treasury_payouts TO {web};",
        f"GRANT SELECT (payout_id) ON treasury_dispatch_authorizations TO {web};",
        f"GRANT SELECT ON {tables(worker_select)} TO {worker};",
        f"GRANT UPDATE ON {tables(worker_update)} TO {worker};",
        f"GRANT INSERT ON {tables(worker_insert)} TO {worker};",
        # Row locks require UPDATE permission, not permission to replace identity keys.
        f"GRANT UPDATE (status) ON clans TO {worker};",
        f"GRANT UPDATE (last_used_at) ON passkeys TO {worker};",
        f"GRANT SELECT (id,user_id,status,expires_at) ON account_access_recoveries TO {worker};",
        # Clan wallet money: the web hands out addresses, records payout addresses and
        # stores signed copies. Only the worker credits, builds, checks and broadcasts.
        f"GRANT SELECT ON {tables(WALLET_MONEY_TABLES)} TO {web};",
        # Communities and their oversight keys are read-only to the web app. Only the
        # operator changes them (clans.communities, as the database owner).
        f"GRANT SELECT ON clan_communities TO {web};",
        f"GRANT INSERT ON clan_wallet_addresses,clan_wallet_payout_requests,"
        f"clan_wallet_signatures TO {web};",
        f"GRANT UPDATE (address,status,last_error,updated_at) ON clan_wallet_payout_requests "
        f"TO {web};",
        f"GRANT UPDATE (psbt,invalid_at,created_at) ON clan_wallet_signatures TO {web};",
        # A changed wallet code clears every confirmation, so all signatories check again.
        f"GRANT DELETE ON clan_wallet_confirmations TO {web};",
        # wallet_id: a waiting grant on a retired wallet moves to the clan's newest wallet.
        f"GRANT UPDATE (status,last_error,updated_at,wallet_id) ON clan_wallet_payout_requests "
        f"TO {worker};",
        f"GRANT UPDATE (invalid_at) ON clan_wallet_signatures TO {worker};",
        # The worker's count of coins still in each wallet, shown while an old one empties.
        f"GRANT UPDATE (balance_sats, spendable_coins) ON clan_wallets TO {worker};",
    ]
    # REVOKE at table level does not remove an earlier column-level grant.
    from clans.db import Base
    from clans.live_app import create_app  # noqa: F401 -- register all production models

    column_revokes = [
        f"REVOKE SELECT ({tables(list(table.columns.keys()))}),"
        f"INSERT ({tables(list(table.columns.keys()))}),"
        f"UPDATE ({tables(list(table.columns.keys()))}),"
        f"REFERENCES ({tables(list(table.columns.keys()))}) "
        f"ON {identifier(table.name)} FROM {web},{worker};"
        for table in Base.metadata.sorted_tables
    ]
    statements[1:1] = column_revokes
    # Runtime web inserts cannot manufacture credited funds or prior dispatch state.
    # SECURITY DEFINER is deliberately avoided: triggers execute with caller rights.
    statements.append(f"""
CREATE OR REPLACE FUNCTION clans_web_financial_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  IF current_user = '{web_role}' THEN
    IF TG_TABLE_NAME = 'treasury_balances' THEN
      IF NEW.balance_msat <> 0 OR NEW.reserved_msat <> 0 THEN
        RAISE EXCEPTION 'Web balance initialization must be zero';
      END IF;
    ELSIF TG_TABLE_NAME = 'incoming_payments' THEN
      IF NEW.status IS DISTINCT FROM 'creating' OR NEW.method IS DISTINCT FROM 'lightning'
         OR NEW.credited_sats IS DISTINCT FROM 0 OR NEW.provider_invoice_id IS NOT NULL
         OR NEW.bolt11 IS NOT NULL OR NEW.checkout_url IS NOT NULL
         OR NEW.expires_at IS NOT NULL THEN
        RAISE EXCEPTION 'Web may only request a new deposit';
      END IF;
    ELSIF TG_TABLE_NAME = 'treasury_payouts' THEN
      IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.attempts <> 0 OR NEW.dispatched_at IS NOT NULL
           OR NEW.fee_paid_msat IS NOT NULL THEN
          RAISE EXCEPTION 'Web may only queue a new payout';
        END IF;
      ELSIF EXISTS (SELECT 1 FROM public.treasury_dispatch_authorizations
                    WHERE payout_id = OLD.id) THEN
        RAISE EXCEPTION 'Dispatched payout is worker controlled';
      END IF;
    ELSIF EXISTS (SELECT 1 FROM public.treasury_dispatch_authorizations a
                  JOIN public.treasury_payouts p ON p.id = a.payout_id
                  WHERE p.intent_id = OLD.id) THEN
      RAISE EXCEPTION 'Dispatched intent is worker controlled';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION clans_web_financial_guard() FROM PUBLIC;
DROP TRIGGER IF EXISTS clans_web_receive_guard ON incoming_payments;
CREATE TRIGGER clans_web_receive_guard BEFORE INSERT ON incoming_payments
FOR EACH ROW EXECUTE FUNCTION clans_web_financial_guard();
DROP TRIGGER IF EXISTS clans_web_balance_guard ON treasury_balances;
CREATE TRIGGER clans_web_balance_guard BEFORE INSERT ON treasury_balances
FOR EACH ROW EXECUTE FUNCTION clans_web_financial_guard();
DROP TRIGGER IF EXISTS clans_web_payout_guard ON treasury_payouts;
CREATE TRIGGER clans_web_payout_guard BEFORE INSERT OR UPDATE ON treasury_payouts
FOR EACH ROW EXECUTE FUNCTION clans_web_financial_guard();
DROP TRIGGER IF EXISTS clans_web_intent_guard ON payment_intents;
CREATE TRIGGER clans_web_intent_guard BEFORE UPDATE ON payment_intents
FOR EACH ROW EXECUTE FUNCTION clans_web_financial_guard();
""")
    return "\n".join(statements)
