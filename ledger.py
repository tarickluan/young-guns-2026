"""Aplica créditos em contas a partir de eventos enviados por um provedor externo.

O provedor garante que cada evento tem um `event_id` estável, mas **não** garante
entrega única: o mesmo evento pode chegar mais de uma vez, inclusive em paralelo.

A idempotência é garantida pelo banco: `event_id` é PRIMARY KEY em `applied_events`.
Uma segunda gravação do mesmo evento viola a constraint e é tratada como duplicata,
sem creditar de novo. Isso vale para threads e para processos, porque a garantia
mora no banco compartilhado, não em estado em memória.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS applied_events (
    event_id     TEXT    PRIMARY KEY,
    account_id   TEXT    NOT NULL,
    amount_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id    TEXT    PRIMARY KEY,
    balance_cents INTEGER NOT NULL DEFAULT 0
);
"""

DATABASE_TIMEOUT_SECONDS = 5


class InvalidCreditError(Exception):
    """Raised when the incoming credit event is not valid."""


@dataclass
class CreditResult:
    applied: bool
    balance_cents: int


class CreditLedger:
    def __init__(self, database_path: str):
        self._database_path = database_path
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        # isolation_level=None: modo autocommit. Assim controlamos a transação
        # explicitamente com BEGIN IMMEDIATE, sem o sqlite3 abrir transações por conta própria.
        return sqlite3.connect(
            self._database_path,
            timeout=DATABASE_TIMEOUT_SECONDS,
            isolation_level=None,
        )

    @contextmanager
    def _transaction(self):
        # BEGIN IMMEDIATE adquire o lock de escrita já no início da transação.
        # Com o timeout, reduz janelas de "database is locked" entre escritores.
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def apply_credit(
        self,
        event_id: str,
        account_id: str,
        amount_cents: int,
    ) -> CreditResult:
        with self._transaction() as conn:
            try:
                conn.execute(
                    "INSERT INTO applied_events (event_id, account_id, amount_cents)"
                    " VALUES (?, ?, ?)",
                    (event_id, account_id, amount_cents),
                )
            except sqlite3.IntegrityError:
                # event_id já existe: evento duplicado. Não credita de novo.
                # A constraint do banco é quem decide, então isso é seguro sob
                # concorrência de threads e de processos.
                current = self._balance_in(conn, account_id)
                return CreditResult(applied=False, balance_cents=current)

            conn.execute(
                "INSERT OR IGNORE INTO accounts (account_id, balance_cents)"
                " VALUES (?, 0)",
                (account_id,),
            )
            conn.execute(
                "UPDATE accounts SET balance_cents = balance_cents + ?"
                " WHERE account_id = ?",
                (amount_cents, account_id),
            )
            new_balance = self._balance_in(conn, account_id)

        return CreditResult(applied=True, balance_cents=new_balance)

    def balance(self, account_id: str) -> int:
        conn = self._connect()
        try:
            return self._balance_in(conn, account_id)
        finally:
            conn.close()

    @staticmethod
    def _balance_in(conn: sqlite3.Connection, account_id: str) -> int:
        row = conn.execute(
            "SELECT balance_cents FROM accounts WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return row[0] if row else 0
