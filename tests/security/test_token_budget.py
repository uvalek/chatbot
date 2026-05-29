"""Pruebas del contador de tokens."""

from __future__ import annotations

from app.security import token_budget


def setup_function() -> None:  # pytest hook por test
    token_budget._per_chat.clear()
    token_budget._global.clear()


def test_record_y_consulta() -> None:
    token_budget.record("chat-A", 100)
    token_budget.record("chat-A", 50)
    assert token_budget.chat_usage("chat-A") == 150
    assert token_budget.global_usage() == 150


def test_record_otro_chat_no_contamina() -> None:
    token_budget.record("chat-A", 100)
    token_budget.record("chat-B", 200)
    assert token_budget.chat_usage("chat-A") == 100
    assert token_budget.chat_usage("chat-B") == 200
    assert token_budget.global_usage() == 300


def test_chat_over_budget() -> None:
    token_budget.record("chat-A", 999)
    assert token_budget.chat_over_budget("chat-A", 1000) is False
    token_budget.record("chat-A", 2)
    assert token_budget.chat_over_budget("chat-A", 1000) is True


def test_global_over_budget() -> None:
    token_budget.record("chat-A", 600)
    token_budget.record("chat-B", 600)
    assert token_budget.global_over_budget(1000) is True


def test_limit_0_desactiva() -> None:
    token_budget.record("chat-A", 999999)
    assert token_budget.chat_over_budget("chat-A", 0) is False
    assert token_budget.global_over_budget(0) is False


def test_estimate_tokens_aprox() -> None:
    assert token_budget.estimate_tokens("") == 0
    assert token_budget.estimate_tokens("abcd") >= 1
    assert token_budget.estimate_tokens("a" * 400) >= 100
