"""Custom validators for pod-related schema fields."""

import re
from typing import Annotated

from pydantic import AfterValidator


def is_positive_power_of_two(value: int) -> int:
    """Validate that an integer is a positive power of two."""
    if value <= 0 or (value & (value - 1)) != 0:
        raise ValueError(f"{value} is not a positive power of 2")
    return value


PositivePowerOfTwo = Annotated[int, AfterValidator(is_positive_power_of_two)]


_MONTH_NAMES = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}
_DOW_NAMES = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"}

_CRON_FIELDS: list[tuple[str, int, int, set[str]]] = [
    ("minute", 0, 59, set()),
    ("hour", 0, 23, set()),
    ("day of month", 1, 31, set()),
    ("month", 1, 12, _MONTH_NAMES),
    ("day of week", 0, 6, _DOW_NAMES),
]


def _validate_cron_field(value: str, name: str, lo: int, hi: int, names: set[str]) -> None:
    """Validate comma, range, wildcard, and step syntax for one cron field."""
    for item in value.split(","):
        parts = item.split("/")
        if len(parts) > 2:
            raise ValueError(f"invalid step expression '{item}' in {name} field")
        base = parts[0]
        step = parts[1] if len(parts) == 2 else None
        if base == "*":
            pass
        elif "-" in base:
            bounds = base.split("-")
            if len(bounds) != 2:
                raise ValueError(f"invalid range '{base}' in {name} field")
            for b in bounds:
                _validate_atom(b, name, lo, hi, names)
        else:
            _validate_atom(base, name, lo, hi, names)
        if step is not None:
            if not step.isdigit() or int(step) == 0:
                raise ValueError(f"step value must be a positive integer, got '{step}' in {name} field")


def _validate_atom(atom: str, name: str, lo: int, hi: int, names: set[str]) -> None:
    """Validate a single numeric or named cron atom."""
    if atom.upper() in names:
        return
    if not re.fullmatch(r"\d+", atom):
        raise ValueError(f"'{atom}' is not a valid value in {name} field")
    n = int(atom)
    if n < lo or n > hi:
        raise ValueError(f"{name} field value {n} is outside the allowed range {lo}-{hi}")


def is_cron_string(value: str) -> str:
    """Validate a standard five-field cron expression."""
    if value == "":
        return value
    fields = value.split()
    if len(fields) != 5:
        raise ValueError(
            f"cron expression must have exactly 5 fields (minute hour day_of_month month day_of_week), got {len(fields)}"
        )
    for value, (name, lo, hi, names) in zip(fields, _CRON_FIELDS):
        _validate_cron_field(value, name, lo, hi, names)
    return value


CronString = Annotated[str, AfterValidator(is_cron_string)]
