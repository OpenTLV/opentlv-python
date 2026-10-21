# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Wire formats shared by `Reader` and `Writer`."""

from __future__ import annotations

import enum
import _opentlv


class Format(enum.IntEnum):
    """The wire format a `Reader` or `Writer` uses.

    Values match the format IDs `_opentlv` expects; do not renumber
    them.
    """

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


def _resolve_format(format):
    """Use BER by default, or require an explicit format when unavailable."""
    if format is not None:
        return format
    if _opentlv.HAS_BER:
        return Format.BER
    raise ValueError("format is required when BER is disabled")


def _format_specification(format):
    """Copy owning native descriptor configuration, including FixedFormat."""
    from opentlv.fixed_format import FixedFormat
    format = _resolve_format(format)
    return ((format.tag_size, format.length_size, format.big_endian)
            if isinstance(format, FixedFormat) else int(format))
