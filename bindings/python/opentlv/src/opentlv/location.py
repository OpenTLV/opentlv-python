# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Shared failure coordinates supplied by the native engine."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    """Evidence domain and anchor; unknown positions have no numeric bounds.

    Domains are input, output, expression, definition, value or unknown.
    Kinds are point, span, scope_end, insertion or unknown. Spans are half-open;
    points and boundaries have equal begin and end, including zero or EOF.
    """
    domain: str = "unknown"
    kind: str = "unknown"
    begin: int | None = None
    end: int | None = None
