from __future__ import annotations

from knowledge_gateway.index import GatewayIndex


def test_build_match_query_joins_tokens_with_or() -> None:
    assert GatewayIndex.build_match_query("Никита день рождения birthday") == (
        '"Никита" OR "день" OR "рождения" OR "birthday"'
    )


def test_build_match_query_quotes_fts_operators_as_literals() -> None:
    assert GatewayIndex.build_match_query("hello OR AND") == (
        '"hello" OR "OR" OR "AND"'
    )
    assert GatewayIndex.build_match_query('say "hi"') == '"say" OR """hi"""'


def test_build_match_query_ignores_blank_input() -> None:
    assert GatewayIndex.build_match_query("   ") == ""
