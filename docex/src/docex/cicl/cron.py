"""5-field cron translation. Mod 055.

``infra.yml`` carries a standard 5-field cron expression
(``minute hour day-of-month month day-of-week``, UTC). Two targets need
different forms — see ``doctrine/infrastructure/specifics/scheduler.md``
§ Cron format:

- **AWS EventBridge Scheduler** uses a 6-field
  ``cron(minute hour day-of-month month day-of-week year)`` form and
  forbids ``*`` in *both* day fields (exactly one must be ``?``). It also
  numbers day-of-week ``1-7`` (Sunday = 1) rather than the standard
  ``0-6`` (Sunday = 0, with 7 also Sunday).
- **Ofelia** (the fixed primitive) uses a 6-field cron whose leading
  field is *seconds*; the compiler prepends ``0`` (run at second 0).
  Ofelia's day-of-week numbering matches standard cron, so no remap.

Translation failures are surfaced at compile time (via
:func:`validate_five_field`) rather than producing a mistranslated
expression that fails at ``tofu apply`` / job-run time.
"""

from __future__ import annotations

from docex.errors import ValidationIssue


# Named day-of-week tokens are passed through unchanged on both targets:
# EventBridge and ofelia both accept the three-letter names, and the
# numbering hazard only applies to numeric tokens.
_DOW_NAMES = frozenset({"sun", "mon", "tue", "wed", "thu", "fri", "sat"})
# Named month tokens, likewise passed through unchanged.
_MONTH_NAMES = frozenset({
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
})


class CronError(ValueError):
    """Raised when a cron expression cannot be parsed or translated."""


# Inclusive numeric ranges for each of the five standard fields.
_FIELD_RANGES: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day-of-month", 1, 31),
    ("month", 1, 12),
    ("day-of-week", 0, 7),  # standard: 0-6 with 7 also Sunday
)


def _split(expr: str) -> list[str]:
    """Split a cron expression on runs of whitespace, raising on the
    wrong number of fields."""
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(
            f"cron expression must have exactly 5 fields "
            f"(minute hour day-of-month month day-of-week); "
            f"got {len(fields)} in {expr!r}"
        )
    return fields


def _validate_token(token: str, field_name: str, lo: int, hi: int) -> None:
    """Validate one comma-separated cron token against ``[lo, hi]``.

    Accepts the common forms: ``*``, a bare number, a range ``a-b``, a
    step ``*/n`` or ``a-b/n`` or ``a/n``. Named day/month tokens (and
    ranges/lists of them) are accepted for the month and day-of-week
    fields and are not range-checked here.
    """
    base, _, step = token.partition("/")
    if "/" in token and (not step or not step.isdigit() or int(step) == 0):
        raise CronError(
            f"{field_name} field: malformed step in token {token!r}"
        )

    if base == "*":
        return

    names = _names_for_field(field_name)
    for piece in base.split("-"):
        piece_l = piece.lower()
        if names is not None and piece_l in names:
            continue
        if not piece.lstrip("-").isdigit() or not piece.isdigit():
            raise CronError(
                f"{field_name} field: unrecognized token {token!r}"
            )
        val = int(piece)
        if val < lo or val > hi:
            raise CronError(
                f"{field_name} field: value {val} out of range "
                f"[{lo}, {hi}] in token {token!r}"
            )


def _names_for_field(field_name: str) -> frozenset[str] | None:
    if field_name == "day-of-week":
        return _DOW_NAMES
    if field_name == "month":
        return _MONTH_NAMES
    return None


def validate_five_field(expr: str) -> None:
    """Raise :class:`CronError` if ``expr`` is not a well-formed 5-field
    cron expression. Returns ``None`` on success.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise CronError("cron expression must be a non-empty string")
    fields = _split(expr.strip())
    for (field_name, lo, hi), field in zip(_FIELD_RANGES, fields):
        if not field:
            raise CronError(f"{field_name} field is empty in {expr!r}")
        for token in field.split(","):
            if not token:
                raise CronError(
                    f"{field_name} field has an empty list element in {expr!r}"
                )
            _validate_token(token, field_name, lo, hi)


def _remap_dow_token(token: str) -> str:
    """Remap a numeric day-of-week token from standard (0-6, 7=Sun) to
    AWS (1-7, 1=Sun). Named tokens and ``*``/``?`` pass through. Operates
    recursively on ranges, lists, and steps so ``1-5`` and ``0,6`` map
    correctly.
    """
    if "," in token:
        return ",".join(_remap_dow_token(t) for t in token.split(","))
    base, sep, step = token.partition("/")
    base = _remap_dow_base(base)
    return f"{base}{sep}{step}" if sep else base


def _remap_dow_base(base: str) -> str:
    if base in ("*", "?"):
        return base
    if "-" in base:
        return "-".join(_remap_dow_base(b) for b in base.split("-"))
    if base.lower() in _DOW_NAMES:
        return base
    if base.isdigit():
        # Standard 0-6 (0/7 = Sun) -> AWS 1-7 (1 = Sun): n -> (n % 7) + 1.
        return str((int(base) % 7) + 1)
    # Unreachable after validation; defensive passthrough.
    return base


def to_aws_cron(expr: str) -> str:
    """Translate a 5-field cron expression into the inner body of AWS
    EventBridge Scheduler's 6-field ``cron(...)`` form (without the
    ``cron(...)`` wrapper — :func:`to_aws_cron_expression` wraps it).

    - Appends the year field ``*``.
    - Substitutes ``?`` so exactly one day field is wildcarded: if
      day-of-week is ``*`` it becomes ``?``; else if day-of-month is
      ``*`` it becomes ``?`` (AWS forbids ``*`` in both).
    - Remaps numeric day-of-week ``0-6`` (0/7 = Sun) to ``1-7``
      (1 = Sun). Named days pass through unchanged.

    Raises :class:`CronError` on a malformed expression.
    """
    validate_five_field(expr)
    minute, hour, dom, month, dow = _split(expr.strip())

    dow = _remap_dow_token(dow)

    # AWS forbids '*' in both day fields; exactly one must be '?'.
    if dow == "*":
        dow = "?"
    elif dom == "*":
        dom = "?"

    return f"{minute} {hour} {dom} {month} {dow} *"


def to_aws_cron_expression(expr: str) -> str:
    """Return the full AWS ``cron(...)`` form for ``schedule_expression``."""
    return f"cron({to_aws_cron(expr)})"


def to_ofelia_cron(expr: str) -> str:
    """Translate a 5-field cron expression into ofelia's 6-field form by
    prepending ``0`` (run at second 0). Ofelia's day-of-week numbering
    matches standard cron, so no remap is applied.

    Raises :class:`CronError` on a malformed expression.
    """
    validate_five_field(expr)
    return "0 " + expr.strip()


def cron_validation_issue(
    expr: str, *, where: str
) -> ValidationIssue | None:
    """Validate ``expr`` and return a :class:`ValidationIssue` describing
    any problem, or ``None`` if it is well-formed. Used by the document
    validator so a malformed schedule is surfaced at compile time.
    """
    try:
        validate_five_field(expr)
    except CronError as exc:
        return ValidationIssue(
            rule="rule_scheduler_malformed_cron",
            message=f"invalid cron expression: {exc}",
            where=where,
        )
    return None
