"""5-field cron *validation*, and nothing else. Mod 115.

``schedules:`` values on a ``clock`` core service are bare 5-field cron
expressions (``minute hour day-of-month month day-of-week``) in UTC. This
module checks that shape at compile time so a malformed expression is an
infra.yml error rather than a runtime surprise inside a clock entrypoint.

There is **no translation of any kind** here — no ``to_aws_cron``, no
``to_ofelia_cron``, no day-of-week remap. Per
``doctrine/infrastructure/specifics/clock.md`` § Cron format the compiler
passes the expression through to the schedule table unchanged; whatever
cron library the codebase uses parses it directly.

WHY a second cron validator while ``cicl/cron.py`` still exists: ``cron.py``
is on Mod 116's delete-outright list. Importing its validator would force
that mod to disentangle a live dependency mid-deletion, which is exactly the
coupling the 115/116 split exists to avoid. The duplication is **transient
and self-resolving** — it spans one mod boundary and ``cron.py``'s deletion
ends it. ``cron.py``'s translation half (``to_aws_cron``, ``to_ofelia_cron``,
the Sunday-is-1 remap) has no counterpart here and is never resurrected.
"""

from __future__ import annotations

from docex.errors import ValidationIssue


class CronExprError(ValueError):
    """Raised when a cron expression is not a well-formed 5-field form."""


# Inclusive numeric ranges for each of the five standard fields.
_FIELD_RANGES: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day-of-month", 1, 31),
    ("month", 1, 12),
    ("day-of-week", 0, 7),  # standard: 0-6 with 7 also Sunday
)

# Three-letter names accepted in the day-of-week and month fields. They are
# not range-checked; the cron library that ultimately parses the expression
# understands them.
_DOW_NAMES = frozenset({"sun", "mon", "tue", "wed", "thu", "fri", "sat"})
_MONTH_NAMES = frozenset({
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
})


def _names_for_field(field_name: str) -> frozenset[str] | None:
    if field_name == "day-of-week":
        return _DOW_NAMES
    if field_name == "month":
        return _MONTH_NAMES
    return None


def _split(expr: str) -> list[str]:
    """Split on runs of whitespace, raising on the wrong field count."""
    fields = expr.split()
    if len(fields) != 5:
        raise CronExprError(
            f"cron expression must have exactly 5 fields "
            f"(minute hour day-of-month month day-of-week); "
            f"got {len(fields)} in {expr!r}"
        )
    return fields


def _validate_token(token: str, field_name: str, lo: int, hi: int) -> None:
    """Validate one comma-separated cron token against ``[lo, hi]``.

    Accepts ``*``, a bare number, a range ``a-b``, and the step forms
    ``*/n`` / ``a-b/n`` / ``a/n``. Named day/month tokens (and ranges or
    lists of them) are accepted in their fields and not range-checked.
    """
    base, _, step = token.partition("/")
    if "/" in token and (not step or not step.isdigit() or int(step) == 0):
        raise CronExprError(
            f"{field_name} field: malformed step in token {token!r}"
        )

    if base == "*":
        return

    names = _names_for_field(field_name)
    for piece in base.split("-"):
        if names is not None and piece.lower() in names:
            continue
        if not piece.isdigit():
            raise CronExprError(
                f"{field_name} field: unrecognized token {token!r}"
            )
        val = int(piece)
        if val < lo or val > hi:
            raise CronExprError(
                f"{field_name} field: value {val} out of range "
                f"[{lo}, {hi}] in token {token!r}"
            )


def validate_five_field(expr: str) -> None:
    """Raise :class:`CronExprError` if ``expr`` is not a well-formed
    5-field cron expression. Returns ``None`` on success.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise CronExprError("cron expression must be a non-empty string")
    fields = _split(expr.strip())
    for (field_name, lo, hi), field in zip(_FIELD_RANGES, fields):
        if not field:
            raise CronExprError(f"{field_name} field is empty in {expr!r}")
        for token in field.split(","):
            if not token:
                raise CronExprError(
                    f"{field_name} field has an empty list element in {expr!r}"
                )
            _validate_token(token, field_name, lo, hi)


def cron_expr_issue(
    expr: str, *, where: str, rule: str
) -> ValidationIssue | None:
    """Validate ``expr``, returning a :class:`ValidationIssue` under
    ``rule`` describing any problem, or ``None`` when well-formed.

    ``rule`` is a parameter rather than a constant so the caller owns the
    rule id it reports under — the clock validator reports
    ``rule_clock_cron_invalid``.
    """
    try:
        validate_five_field(expr)
    except CronExprError as exc:
        return ValidationIssue(
            rule=rule,
            message=f"invalid cron expression: {exc}",
            where=where,
        )
    return None
