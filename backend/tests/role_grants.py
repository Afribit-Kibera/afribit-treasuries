"""Check every statement a test runs against the production PostgreSQL grants.

SQLite has no roles, so a missing grant would otherwise only show up on PostgreSQL, as a
web route or chain watcher cycle that fails every time. Attach a checker to each engine
with the role it runs as in production, then assert there were no violations.
"""

import re
from contextlib import contextmanager

from sqlalchemy import event

from clans.database_roles import runtime_grants

ROLES = {"web": "check_web", "worker": "check_worker"}
PRIVILEGE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b(?:\s*\(([^)]*)\))?")


def granted() -> dict:
    """(role, privilege, table) -> None for every column, or the set of granted columns."""
    allowed: dict = {}
    for statement in runtime_grants(ROLES["web"], ROLES["worker"]).split(";"):
        match = re.match(r"\s*GRANT (.+?) ON (.+?) TO (.+)$", statement, re.S)
        if not match or "SCHEMA" in match.group(2):
            continue
        privileges, tables, roles = match.groups()
        for name, role in ROLES.items():
            if f'"{role}"' not in roles:
                continue
            for table in tables.split(","):
                table = table.strip().strip('"')
                for privilege, columns in PRIVILEGE.findall(privileges):
                    key = (name, privilege, table)
                    if not columns:
                        allowed[key] = None
                    elif allowed.get(key, set()) is not None:
                        names = {column.strip().strip('"') for column in columns.split(",")}
                        allowed[key] = allowed.get(key, set()) | names
    return allowed


def touched(sql: str):
    """(privilege, table, columns) for each table a statement reads or writes."""
    sql = " ".join(sql.split())
    if match := re.match(r"UPDATE (\w+) SET (.+?)(?: WHERE |$)", sql):
        yield "UPDATE", match.group(1), set(re.findall(r"(\w+)=", match.group(2)))
    elif match := re.match(r"INSERT INTO (\w+) \(([^)]*)\)", sql):
        yield "INSERT", match.group(1), {column.strip() for column in match.group(2).split(",")}
    elif match := re.match(r"DELETE FROM (\w+)", sql):
        yield "DELETE", match.group(1), set()
    if sql.startswith(("SELECT", "UPDATE", "INSERT", "DELETE")):
        for table in set(re.findall(r"\b(?:FROM|JOIN) (\w+)", sql)):
            if not sql.startswith("DELETE FROM " + table):
                yield "SELECT", table, set()


class GrantChecker:
    def __init__(self):
        self.allowed = granted()
        self.violations: list[str] = []
        self.active = True

    def watch(self, engine, role: str):
        @event.listens_for(engine, "before_cursor_execute")
        def check(conn, cursor, statement, parameters, context, executemany):
            if not self.active:
                return
            for privilege, table, columns in touched(statement):
                key = (role, privilege, table)
                if key not in self.allowed:
                    self.violations.append(f"{role} has no {privilege} on {table}")
                elif self.allowed[key] is not None and not columns <= self.allowed[key]:
                    missing = ", ".join(sorted(columns - self.allowed[key]))
                    self.violations.append(f"{role} has no {privilege} ({missing}) on {table}")

    @contextmanager
    def paused(self):
        """For test setup that writes directly, as no production role would."""
        self.active = False
        try:
            yield
        finally:
            self.active = True

    def assert_clean(self):
        assert not self.violations, "\n".join(sorted(set(self.violations)))
