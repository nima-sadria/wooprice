"""
Unit tests — A2.3-R2 AST formula engine.

Verifies determinism, sandboxing, and correct arithmetic.
No database required; all tests are pure computation.
"""
import os
os.environ.setdefault("A2_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from decimal import Decimal

import pytest

from app.a2.rules.formula import evaluate_formula, extract_variables


# ── Basic arithmetic ───────────────────────────────────────────────────────────

def test_multiply_constant():
    result = evaluate_formula("cost * 1.20", {"cost": Decimal("100000")})
    assert result == Decimal("100000") * Decimal("1.20")


def test_add_two_variables():
    result = evaluate_formula("cost + fee", {"cost": Decimal("100000"), "fee": Decimal("5000")})
    assert result == Decimal("105000")


def test_subtract():
    result = evaluate_formula("competitor_price - 10000", {"competitor_price": Decimal("200000")})
    assert result == Decimal("190000")


def test_divide():
    result = evaluate_formula("cost / 2", {"cost": Decimal("100000")})
    assert result == Decimal("50000")


def test_compound_expression():
    result = evaluate_formula(
        "(cost + fee) * fx_rate",
        {"cost": Decimal("100"), "fee": Decimal("10"), "fx_rate": Decimal("15000")},
    )
    assert result == Decimal("1650000")


def test_nested_multiplication():
    result = evaluate_formula(
        "cost * fx_rate * 1.15",
        {"cost": Decimal("100"), "fx_rate": Decimal("15000")},
    )
    assert result == Decimal("100") * Decimal("15000") * Decimal("1.15")


def test_integer_constant():
    result = evaluate_formula("cost * 2", {"cost": Decimal("50000")})
    assert result == Decimal("100000")


def test_unary_negation_with_subtraction():
    result = evaluate_formula(
        "competitor_price - cost",
        {"competitor_price": Decimal("200"), "cost": Decimal("150")},
    )
    assert result == Decimal("50")


def test_determinism_same_inputs_same_output():
    formula = "cost * 1.20 + fee"
    inputs = {"cost": Decimal("80000"), "fee": Decimal("3000")}
    r1 = evaluate_formula(formula, inputs)
    r2 = evaluate_formula(formula, inputs)
    assert r1 == r2


def test_fx_based_formula():
    result = evaluate_formula("cost * fx_rate", {"cost": Decimal("100"), "fx_rate": Decimal("15000")})
    assert result == Decimal("1500000")


def test_fee_based_formula():
    result = evaluate_formula(
        "(cost + fee) * 1.10",
        {"cost": Decimal("100000"), "fee": Decimal("5000")},
    )
    assert result == (Decimal("100000") + Decimal("5000")) * Decimal("1.10")


def test_competition_formula():
    result = evaluate_formula("competitor_price * 0.95", {"competitor_price": Decimal("200000")})
    assert result == Decimal("200000") * Decimal("0.95")


def test_multi_variable_formula():
    result = evaluate_formula(
        "cost * fx_rate + fee",
        {"cost": Decimal("10"), "fx_rate": Decimal("15000"), "fee": Decimal("500")},
    )
    assert result == Decimal("10") * Decimal("15000") + Decimal("500")


# ── Sandboxing — forbidden constructs ─────────────────────────────────────────

def test_reject_function_call():
    with pytest.raises(ValueError, match="forbidden"):
        evaluate_formula("eval('1+1')", {})


def test_reject_import():
    with pytest.raises((ValueError, SyntaxError)):
        evaluate_formula("__import__('os')", {})


def test_reject_attribute_access():
    with pytest.raises(ValueError, match="forbidden"):
        evaluate_formula("cost.__class__", {"cost": Decimal("1")})


def test_reject_comparison():
    with pytest.raises(ValueError, match="forbidden"):
        evaluate_formula("cost > 0", {"cost": Decimal("1")})


def test_reject_ternary():
    with pytest.raises(ValueError, match="forbidden"):
        evaluate_formula("cost if cost else 0", {"cost": Decimal("1")})


def test_reject_string_literal():
    with pytest.raises(ValueError):
        evaluate_formula("'hello'", {})


def test_reject_list_literal():
    with pytest.raises(ValueError, match="forbidden"):
        evaluate_formula("[1, 2]", {})


def test_reject_subscript():
    with pytest.raises(ValueError, match="forbidden"):
        evaluate_formula("cost[0]", {"cost": Decimal("1")})


def test_reject_lambda():
    with pytest.raises((ValueError, SyntaxError)):
        evaluate_formula("lambda x: x", {})


def test_does_not_use_eval_internally():
    """Verify the formula module's source does not call eval() or exec()."""
    import importlib
    spec = importlib.util.find_spec("app.a2.rules.formula")
    assert spec is not None and spec.origin is not None
    with open(spec.origin, encoding="utf-8") as f:
        src = f.read()
    # Only check non-comment, non-docstring lines
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        assert "eval(" not in line, f"formula.py must not call eval(): {line!r}"
        assert "exec(" not in line, f"formula.py must not call exec(): {line!r}"


# ── Error cases ────────────────────────────────────────────────────────────────

def test_unknown_variable_raises_key_error():
    with pytest.raises(KeyError, match="unknown_var"):
        evaluate_formula("unknown_var * 1.2", {})


def test_division_by_zero_raises():
    with pytest.raises(ZeroDivisionError):
        evaluate_formula("cost / 0", {"cost": Decimal("100")})


def test_syntax_error_raises_value_error():
    with pytest.raises(ValueError, match="syntax"):
        evaluate_formula("cost *", {"cost": Decimal("100")})


def test_empty_formula_raises():
    with pytest.raises(ValueError):
        evaluate_formula("", {})


def test_whitespace_only_formula_raises():
    with pytest.raises(ValueError):
        evaluate_formula("   ", {})


# ── extract_variables ──────────────────────────────────────────────────────────

def test_extract_single_variable():
    assert extract_variables("cost * 1.20") == ["cost"]


def test_extract_multiple_variables():
    assert extract_variables("(cost + fee) * fx_rate") == ["cost", "fee", "fx_rate"]


def test_extract_no_variables():
    assert extract_variables("100 * 1.20") == []


def test_extract_deduplicates():
    assert extract_variables("cost + cost") == ["cost"]


def test_extract_sorted():
    assert extract_variables("z_var + a_var") == ["a_var", "z_var"]
