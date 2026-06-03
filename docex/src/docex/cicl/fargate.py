"""Fargate ``(cpu, memory)`` pair validation.

AWS Fargate only accepts a small set of ``(cpu, memory)`` combinations
per task definition. The Phase 1 emitter computed ``cpu*1024`` and
``memory_to_mib`` without consulting the allow-list, producing pairs
like ``(1024, 1907)`` that Fargate rejects.

This module maps the CICL ``cpu: <float vCPUs>`` and
``memory: "<N>GB"`` fields to a valid Fargate pair, rounding memory
**up** within the chosen CPU's allowed range. If the requested values
exceed Fargate's maximums, it raises ``ValidationError`` with a clear
message pointing at the service.

See the table in the AWS Fargate task-definition docs § Task size:
https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html
"""

from __future__ import annotations

import re

from docex.errors import ValidationError, ValidationIssue


# Allowed Fargate CPU values, in Fargate "units" (1024 = 1 vCPU).
_FARGATE_CPUS = (256, 512, 1024, 2048, 4096, 8192, 16384)


def _allowed_memory_mib(cpu: int) -> list[int]:
    """Return the sorted list of allowed memory values (MiB) for a given Fargate CPU."""
    if cpu == 256:
        return [512, 1024, 2048]
    if cpu == 512:
        return [1024, 2048, 3072, 4096]
    if cpu == 1024:
        return [m for m in range(2048, 8192 + 1, 1024)]
    if cpu == 2048:
        return [m for m in range(4096, 16384 + 1, 1024)]
    if cpu == 4096:
        return [m for m in range(8192, 30720 + 1, 1024)]
    if cpu == 8192:
        return [m for m in range(16384, 61440 + 1, 4096)]
    if cpu == 16384:
        return [m for m in range(32768, 122880 + 1, 8192)]
    raise ValueError(f"unknown Fargate CPU: {cpu}")


def _memory_to_mib(memory: str) -> int:
    """Convert a CICL memory string (e.g. ``"2GB"``, ``"512MB"``) to MiB.

    Uses decimal-units inputs (GB/MB) → binary-units outputs (MiB),
    matching docex's compose-side behavior. Fractional values are
    accepted; the result is rounded to the nearest int MiB.
    """
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(MB|GB)$", memory)
    if not m:
        raise ValueError(f"unparseable memory string: {memory!r}")
    n, unit = float(m.group(1)), m.group(2)
    bytes_ = n * (1_000_000 if unit == "MB" else 1_000_000_000)
    return int(round(bytes_ / (1024 * 1024)))


def _round_cpu_to_fargate(cpu_units: int) -> int:
    """Pick the smallest valid Fargate CPU that is >= the requested units.

    If the request exceeds the largest allowed value (16384 = 16 vCPU),
    return that ceiling — the caller catches it as a validation error
    when memory cannot fit.
    """
    for c in _FARGATE_CPUS:
        if c >= cpu_units:
            return c
    return _FARGATE_CPUS[-1]


def fargate_pair_from_units(
    cpu_units: int, memory_mib: int, *, service_name: str
) -> tuple[int, int]:
    """Translate already-computed ``(cpu_units, memory_mib)`` to a valid
    Fargate pair, rounding both up.

    Same shape as :func:`fargate_pair` but skips the string parsing —
    useful when the caller has already added per-task overhead (e.g. the
    sidecar's 0.1 vCPU / 128 MiB) and wants the rounding logic directly.
    Mod 018.
    """
    cpu_choice = _round_cpu_to_fargate(cpu_units)
    for cpu_attempt in [cpu_choice] + [
        c for c in _FARGATE_CPUS if c > cpu_choice
    ]:
        allowed = _allowed_memory_mib(cpu_attempt)
        for mib in allowed:
            if mib >= memory_mib:
                return (cpu_attempt, mib)
    max_cpu = _FARGATE_CPUS[-1]
    max_mib = _allowed_memory_mib(max_cpu)[-1]
    raise ValidationError([ValidationIssue(
        rule="rule_fargate_pair_invalid",
        message=(
            f"Fargate cannot satisfy cpu={cpu_units} units + memory={memory_mib} MiB: "
            f"exceeds Fargate maximum {max_cpu} units / {max_mib} MiB. "
            f"Reduce resources or split the service. Valid CPU buckets: "
            f"{list(_FARGATE_CPUS)}."
        ),
        where=f"core_services.{service_name}.resources",
    )])


def fargate_pair(cpu: float, memory: str, *, service_name: str) -> tuple[int, int]:
    """Translate a CICL ``(cpu, memory)`` to a valid Fargate pair.

    Algorithm:
      1. Round CPU **up** to the next valid Fargate value.
      2. Compute target memory in MiB.
      3. Round memory **up** to the next valid value for the chosen CPU.
      4. If the target memory exceeds the chosen CPU's allowed maximum,
         retry with the next larger CPU (one bump only — we don't want
         to silently quadruple a misconfigured service).

    Returns ``(fargate_cpu_units, fargate_memory_mib)``.

    Raises :class:`ValidationError` if no valid combination exists for
    the requested values.
    """
    requested_cpu_units = max(1, int(round(cpu * 1024)))
    cpu_choice = _round_cpu_to_fargate(requested_cpu_units)

    try:
        target_mib = _memory_to_mib(memory)
    except ValueError as e:
        raise ValidationError([ValidationIssue(
            rule="rule_fargate_memory_unparseable",
            message=str(e),
            where=f"core_services.{service_name}.resources.memory",
        )]) from e

    for cpu_attempt in [cpu_choice] + [
        c for c in _FARGATE_CPUS if c > cpu_choice
    ]:
        allowed = _allowed_memory_mib(cpu_attempt)
        # Round up to the smallest valid memory >= target.
        for mib in allowed:
            if mib >= target_mib:
                return (cpu_attempt, mib)
        # Target exceeds this CPU's max — try the next larger CPU.

    # Exhausted all Fargate CPU buckets.
    max_cpu = _FARGATE_CPUS[-1]
    max_mib = _allowed_memory_mib(max_cpu)[-1]
    raise ValidationError([ValidationIssue(
        rule="rule_fargate_pair_invalid",
        message=(
            f"Fargate cannot satisfy cpu={cpu} vCPU + memory={memory!r}: "
            f"requested {requested_cpu_units} CPU units / {target_mib} MiB "
            f"exceeds Fargate maximum {max_cpu} units / {max_mib} MiB. "
            f"Reduce resources or split the service. Valid CPU buckets: "
            f"{list(_FARGATE_CPUS)}."
        ),
        where=f"core_services.{service_name}.resources",
    )])
