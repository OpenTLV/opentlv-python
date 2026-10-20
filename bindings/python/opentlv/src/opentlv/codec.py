# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Configured numeric and EMV amount Value codecs backed by canonical C."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import _opentlv as _native


from opentlv.error import _from_native


def decode_amount(data: bytes) -> int:
    """Decodes 6 bytes of BCD (EMV format n12) into an unscaled minor-unit amount.

    Wraps the public C `tlv_emv_codec_amount` codec.

    >>> decode_amount(bytes.fromhex("000000012345"))
    12345
    """
    if not _native.HAS_EMV:
        raise NotImplementedError("EMV is disabled in this build")
    try:
        return _native.emv_decode_amount(data)
    except _native.Error as native_error:
        raise _from_native(native_error) from None


def encode_amount(value: int) -> bytes:
    """Encodes an unscaled minor-unit amount as 6 bytes of BCD (EMV format n12).

    >>> encode_amount(12345).hex()
    '000000012345'
    """
    if not _native.HAS_EMV:
        raise NotImplementedError("EMV is disabled in this build")
    try:
        return _native.emv_encode_amount(value)
    except _native.Error as native_error:
        raise _from_native(native_error) from None




class NumberEncoding(IntEnum):
    """Explicit numeric Value representation, independent of protocol tags."""
    BIG_ENDIAN = 0
    LITTLE_ENDIAN = 1
    BCD = 2


@dataclass(frozen=True)
class NumberCodec:
    """Configured uint64 codec backed by C; configuration is validated on use.

    Width zero selects minimal encoding. BCD digits specify precision (1..18);
    binary encodings require digits=0. Schema owns contextual length constraints.
    """
    encoding: NumberEncoding = NumberEncoding.BIG_ENDIAN
    width: int = 0
    digits: int = 0

    def _call(self, operation, value, output=None):
        try:
            return _native.number_codec(operation, int(self.encoding), self.width,
                                        self.digits, value, output)
        except _native.Error as error:
            raise _from_native(error) from None

    def decode(self, data) -> int:
        """Decode Value bytes through C into an unsigned integer."""
        return self._call(0, data)

    def encode(self, value: int) -> bytes:
        """Return the C encoding as owned bytes."""
        return self._call(1, value)

    def encoded_size(self, value: int) -> int:
        """Validate and measure through the C size-query operation."""
        return self._call(2, value)

    def encode_into(self, value: int, output) -> int:
        """Encode into caller storage; failures leave its bytes unchanged."""
        return self._call(3, value, output)
