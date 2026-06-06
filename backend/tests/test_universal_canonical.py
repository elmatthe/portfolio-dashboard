"""Item 4 Step 1 — canonical schema: action down-map + min-schema ruleset."""
from __future__ import annotations

from typing import get_args

import pytest

from backend.models import Action
from backend.import_engine.canonical import (
    ACTION_DOWNMAP,
    EMITTED_ACTIONS,
    GLOBAL_REQUIRED,
    MIN_SCHEMA,
    CanonicalAction,
    CanonicalField,
    rule_for,
    to_emitted_action,
)


def test_emitted_actions_match_models_action_literal():
    """EMITTED_ACTIONS must stay byte-identical to backend.models.Action.

    If a future edit changes the Action Literal, this fails loudly so the
    down-map can't silently emit an action the DB/ACB won't accept.
    """
    assert EMITTED_ACTIONS == set(get_args(Action))


def test_downmap_covers_every_canonical_action():
    """Every rich canonical action has a down-map entry (no KeyError at runtime)."""
    for action in CanonicalAction:
        assert action in ACTION_DOWNMAP, f"{action} missing from ACTION_DOWNMAP"


def test_downmap_only_yields_stored_actions():
    """The down-map can only ever produce one of the stored 11 actions."""
    for action in CanonicalAction:
        assert to_emitted_action(action) in EMITTED_ACTIONS


@pytest.mark.parametrize(
    "canonical,expected",
    [
        (CanonicalAction.BUY, "BUY"),
        (CanonicalAction.SELL, "SELL"),
        (CanonicalAction.DIVIDEND, "DIVIDEND"),
        (CanonicalAction.TRANSFER_IN, "DEPOSIT"),
        (CanonicalAction.TRANSFER_OUT, "WITHDRAWAL"),
        (CanonicalAction.REINVEST_DRIP, "BUY"),
        (CanonicalAction.JOURNAL, "TRANSFER"),
        (CanonicalAction.CORPORATE_ACTION, "OTHER"),
        (CanonicalAction.RETURN_OF_CAPITAL, "OTHER"),
        (CanonicalAction.TAX_WITHHOLDING, "OTHER"),
        (CanonicalAction.CASH_ADJUSTMENT, "OTHER"),
    ],
)
def test_downmap_specific_cases(canonical, expected):
    assert to_emitted_action(canonical) == expected


def test_min_schema_covers_every_action():
    for action in CanonicalAction:
        rule = rule_for(action)
        assert rule.action is action


def test_every_rule_requires_a_transaction_date():
    """The global minimum: a parseable date is required for every action."""
    assert CanonicalField.TRANSACTION_DATE in GLOBAL_REQUIRED
    for action, rule in MIN_SCHEMA.items():
        assert CanonicalField.TRANSACTION_DATE in rule.required, f"{action} lacks date"


def test_buy_sell_need_two_of_qty_price_amount():
    for action in (CanonicalAction.BUY, CanonicalAction.SELL):
        rule = rule_for(action)
        # exactly one n_of group requiring 2 of {quantity, price, net_amount}
        assert rule.n_of, f"{action} should declare an n_of group"
        n, fields = rule.n_of[0]
        assert n == 2
        assert set(fields) == {
            CanonicalField.QUANTITY,
            CanonicalField.PRICE,
            CanonicalField.NET_AMOUNT,
        }
        # and a security identifier (ticker OR security_name)
        assert (CanonicalField.TICKER, CanonicalField.SECURITY_NAME) in rule.any_of
