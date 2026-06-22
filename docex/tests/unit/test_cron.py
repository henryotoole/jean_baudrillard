"""Tests for the 5-field cron translation (mod 055).

Covers the AWS EventBridge form (6-field, ?-day rule, dow 0-6 -> 1-7
remap), the ofelia form (seconds prepend, no remap), and validation of
malformed expressions.
"""

from __future__ import annotations

import pytest

from docex.cicl.cron import (
    CronError,
    to_aws_cron,
    to_aws_cron_expression,
    to_ofelia_cron,
    validate_five_field,
)


# --- validate_five_field ---------------------------------------------------


def test_validate_accepts_common_forms():
    for expr in (
        "* * * * *",
        "0 3 * * *",
        "*/15 * * * *",
        "0 0 1,15 * *",
        "0 9-17 * * 1-5",
        "30 2 * * SUN",
        "0 0 1 JAN *",
    ):
        validate_five_field(expr)  # must not raise


@pytest.mark.parametrize("expr", [
    "",
    "   ",
    "* * * *",          # 4 fields
    "* * * * * *",      # 6 fields
    "60 * * * *",       # minute out of range
    "* 24 * * *",       # hour out of range
    "* * 32 * *",       # dom out of range
    "* * * 13 *",       # month out of range
    "* * * * 8",        # dow out of range (0-7 allowed; 8 not)
    "*/ * * * *",       # malformed step
    "*/0 * * * *",      # zero step
    "abc * * * *",      # garbage token
    "1,,2 * * * *",     # empty list element
])
def test_validate_rejects_malformed(expr):
    with pytest.raises(CronError):
        validate_five_field(expr)


# --- to_aws_cron -----------------------------------------------------------


def test_aws_all_wildcards_gets_question_dow_and_year():
    # dow '*' -> '?', dom stays '*', year '*' appended.
    assert to_aws_cron("* * * * *") == "* * * * ? *"


def test_aws_dom_set_dow_wildcard_keeps_dom_questions_dow():
    assert to_aws_cron("0 3 * * *") == "0 3 * * ? *"


def test_aws_dow_set_dom_wildcard_questions_dom():
    # dow is a numeric set, so dom (which is '*') becomes '?'.
    # dow 1 (Mon, standard) -> 2 (AWS).
    assert to_aws_cron("0 9 * * 1") == "0 9 ? * 2 *"


def test_aws_numeric_dow_remap_sunday():
    # Standard 0 = Sunday -> AWS 1 = Sunday.
    assert to_aws_cron("0 0 * * 0") == "0 0 ? * 1 *"
    # Standard 7 also = Sunday -> AWS 1.
    assert to_aws_cron("0 0 * * 7") == "0 0 ? * 1 *"


def test_aws_numeric_dow_remap_saturday():
    # Standard 6 = Saturday -> AWS 7.
    assert to_aws_cron("0 0 * * 6") == "0 0 ? * 7 *"


def test_aws_numeric_dow_range_remap():
    # Mon-Fri standard 1-5 -> AWS 2-6.
    assert to_aws_cron("0 9 * * 1-5") == "0 9 ? * 2-6 *"


def test_aws_numeric_dow_list_remap():
    # Sun,Sat standard 0,6 -> AWS 1,7.
    assert to_aws_cron("0 0 * * 0,6") == "0 0 ? * 1,7 *"


def test_aws_named_dow_passthrough():
    # Named days are not remapped.
    assert to_aws_cron("30 2 * * SUN") == "30 2 ? * SUN *"


def test_aws_expression_wrapper():
    assert to_aws_cron_expression("0 3 * * *") == "cron(0 3 * * ? *)"


def test_aws_rejects_malformed():
    with pytest.raises(CronError):
        to_aws_cron("not a cron")


# --- to_ofelia_cron --------------------------------------------------------


def test_ofelia_prepends_seconds():
    assert to_ofelia_cron("0 3 * * *") == "0 0 3 * * *"


def test_ofelia_no_dow_remap():
    # Standard numbering preserved (no remap on the fixed side).
    assert to_ofelia_cron("0 0 * * 0") == "0 0 0 * * 0"


def test_ofelia_rejects_malformed():
    with pytest.raises(CronError):
        to_ofelia_cron("* * *")
