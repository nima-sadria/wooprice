"""
Sandboxed formula evaluator for A2.3 pricing rules.

Uses Python's ast module with a strict whitelist of allowed node types.
Arithmetic only. No arbitrary code execution.
"""
from __future__ import annotations

import ast
from decimal import Decimal

# Nodes permitted in a pricing formula. Anything not in this set is rejected.
_ALLOWED_NODES = frozenset({
    ast.Expression,
    ast.BinOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.UnaryOp, ast.USub, ast.UAdd,
    ast.Constant,
    ast.Name,
    ast.Load,   # context node on ast.Name — appears in every variable reference
})


class _WhitelistValidator(ast.NodeVisitor):
    """Raises ValueError on the first forbidden AST node type."""

    def generic_visit(self, node: ast.AST) -> None:
        if type(node) not in _ALLOWED_NODES:
            raise ValueError(
                f"Formula contains forbidden construct: {type(node).__name__}"
            )
        super().generic_visit(node)


def evaluate_formula(formula: str, variables: dict[str, Decimal]) -> Decimal:
    """
    Safely evaluate an arithmetic pricing formula.

    Args:
        formula:   Arithmetic expression using +, -, *, / and variable names.
                   Examples: "cost * 1.20", "(cost + fee) * fx_rate"
        variables: Mapping of variable name → Decimal value.

    Returns:
        Decimal result of the formula.

    Raises:
        ValueError:        Syntax error, forbidden AST node, or non-numeric constant.
        KeyError:          Formula references a variable not present in *variables*.
        ZeroDivisionError: Formula divides by zero.
    """
    if not formula or not formula.strip():
        raise ValueError("Formula must not be empty.")

    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Formula syntax error: {exc}") from exc

    _WhitelistValidator().visit(tree)
    return _eval_node(tree.body, variables)


def extract_variables(formula: str) -> list[str]:
    """Return the sorted list of variable names referenced by a formula."""
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Formula syntax error: {exc}") from exc
    _WhitelistValidator().visit(tree)

    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in names:
                names.append(node.id)
    return sorted(names)


# ── Internal AST evaluator ─────────────────────────────────────────────────────

def _eval_node(node: ast.expr, variables: dict[str, Decimal]) -> Decimal:
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise ValueError(
                f"Only numeric constants are allowed; got {node.value!r}."
            )
        return Decimal(str(node.value))

    if isinstance(node, ast.Name):
        name = node.id
        if name not in variables:
            raise KeyError(f"Unknown variable in formula: '{name}'.")
        value = variables[name]
        return Decimal(str(value))

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, variables)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}.")

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, variables)
        right = _eval_node(node.right, variables)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            if right == 0:
                raise ZeroDivisionError("Division by zero in formula.")
            return left / right
        raise ValueError(f"Unsupported binary operator: {type(op).__name__}.")

    raise ValueError(f"Unsupported AST node: {type(node).__name__}.")
