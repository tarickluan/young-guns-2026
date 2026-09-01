"""Testes de validação de input (requisito 5 do README).

Falham no código original (não havia validação) e passam depois da correção.
"""

import pytest

from ledger import InvalidCreditError


@pytest.mark.parametrize(
    "event_id, account_id, amount_cents",
    [
        ("", "acc-1", 100),      # event_id vazio
        ("evt-1", "", 100),      # account_id vazio
        ("evt-1", "acc-1", 0),   # amount zero
        ("evt-1", "acc-1", -50), # amount negativo
    ],
)
def test_invalid_event_raises(ledger, event_id, account_id, amount_cents):
    with pytest.raises(InvalidCreditError):
        ledger.apply_credit(event_id, account_id, amount_cents)


def test_invalid_event_does_not_change_balance(ledger):
    with pytest.raises(InvalidCreditError):
        ledger.apply_credit("evt-1", "acc-1", -50)

    assert ledger.balance("acc-1") == 0


def test_rejected_event_id_can_be_reused(ledger):
    with pytest.raises(InvalidCreditError):
        ledger.apply_credit("evt-1", "acc-1", -50)

    result = ledger.apply_credit("evt-1", "acc-1", 100)

    assert result.applied is True
    assert ledger.balance("acc-1") == 100
