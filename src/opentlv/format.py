# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Wire formats shared by `Reader` and `Writer`."""

from __future__ import annotations

import enum
import _opentlv

from opentlv import composed_format
from opentlv.format_operations import FormatOperations


class Format(FormatOperations, enum.IntEnum):
    """The wire format a `Reader` or `Writer` uses.

    Values match the format IDs `_opentlv` expects; do not renumber
    them. Every Format, including `FixedFormat` and composed formats, also
    provides the canonical `decode()`, `measure()`, `encode()`, `can_read`
    and `can_write` operations.

    `fields()`, `variable()`, `escaped()` and `packed()` compose a custom
    `ComposedFormat` from the generic C field encodings and compositions.
    """

    fields = staticmethod(composed_format.fields)
    variable = staticmethod(composed_format.variable)
    escaped = staticmethod(composed_format.escaped)
    packed = staticmethod(composed_format.packed)

    if _opentlv.HAS_BER:
        BER = 1
        """BER-TLV."""

    if _opentlv.HAS_CER:
        CER = 2
        """Canonical Encoding Rules."""

    if _opentlv.HAS_DER:
        DER = 3
        """Distinguished Encoding Rules."""

    if _opentlv.HAS_EMV:
        EMV = 5
        """Definite EMV Contact Book 3 BER-TLV element framing."""
    if _opentlv.HAS_NFC:
        NFC_TYPE2 = 6
        """Contiguous NFC Type 2 TLV stream; the caller handles termination."""

    if _opentlv.HAS_LLDP:
        LLDP = 4
        """LLDP packed header framing, without LLDPDU semantic validation."""

    def _native_format(self):
        return int(self)


def _resolve_format(format):
    """Use BER by default, or require an explicit format when unavailable."""
    if format is not None:
        return format
    if _opentlv.HAS_BER:
        return Format.BER
    raise ValueError("format is required when BER is disabled")


def _format_specification(format):
    """Native descriptor specification: builtin ID, fixed widths or composed owner."""
    format = _resolve_format(format)
    return format._native_format() if isinstance(format, FormatOperations) else int(format)
