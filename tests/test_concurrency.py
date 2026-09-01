"""Testes de concorrência (requisitos 3, 4 e 6 do README).

Estes testes falham no código original (dedup em memória, sem constraint no banco)
e passam depois da correção (idempotência garantida pela PRIMARY KEY do event_id).
"""

import threading

from ledger import CreditLedger


def _run_concurrently(fn, n):
    """Dispara `n` threads que chamam `fn(i)` ao mesmo tempo.

    Uma Barrier segura todas as threads e libera juntas, maximizando a disputa
    e expondo qualquer race condition de check-then-act.

    Exceções levantadas dentro das threads (ex.: "database is locked") são
    coletadas em `errors`. Sem isso, uma thread que morre some de `results` e
    o teste poderia passar escondendo a falha. Os testes exigem `not errors`.
    """
    barrier = threading.Barrier(n)
    results = []
    errors = []
    lock = threading.Lock()

    def worker(i):
        barrier.wait()
        try:
            result = fn(i)
        except Exception as exc:
            with lock:
                errors.append(exc)
            return
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def test_same_event_in_many_threads_credits_once(ledger):
    """Requisito 3: mesmo event_id em N threads credita uma vez só."""
    n = 30
    results, errors = _run_concurrently(
        lambda i: ledger.apply_credit("evt-conc", "acc-1", 1000), n
    )

    assert not errors
    assert ledger.balance("acc-1") == 1000
    assert sum(1 for r in results if r.applied) == 1


def test_same_event_across_instances_credits_once(database_path):
    """Requisito 4: N instâncias no mesmo arquivo, mesmo event_id, credita uma vez só."""
    n = 30
    ledgers = [CreditLedger(database_path) for _ in range(n)]
    results, errors = _run_concurrently(
        lambda i: ledgers[i].apply_credit("evt-multi", "acc-1", 1000), n
    )

    assert not errors
    assert CreditLedger(database_path).balance("acc-1") == 1000
    assert sum(1 for r in results if r.applied) == 1


def test_distinct_events_in_parallel_all_apply(ledger):
    """Requisito 6: eventos diferentes em paralelo somam (a correção não pode travar demais)."""
    n = 30
    results, errors = _run_concurrently(
        lambda i: ledger.apply_credit(f"evt-{i}", "acc-1", 100), n
    )

    assert not errors
    assert ledger.balance("acc-1") == 100 * n
    assert all(r.applied for r in results)
