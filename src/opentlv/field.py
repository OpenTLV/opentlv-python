# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Field encodings that compose a Format, mirroring `tlv/field/*.h`.

Each class is an immutable configuration. Core validates masks, widths,
policies and their combination when a Format is composed from them, and
`PackedField` reads and writes its bits through Core directly; Python checks
only types and representable ranges.
"""

from __future__ import annotations

from dataclasses import dataclass

import _opentlv as _native

from opentlv.error import _from_native

_BYTE_ORDERS = {"big": True, "little": False}
_SIZE_MAX = 2 ** 64 - 1


def _unsigned(name: str, value: int, maximum: int = _SIZE_MAX) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int")
    if not 0 <= value <= maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return value


def _byte(name: str, value: int) -> int:
    return _unsigned(name, value, 0xFF)


def _big_endian(byte_order: str) -> bool:
    if byte_order not in _BYTE_ORDERS:
        raise ValueError("byte_order must be 'big' or 'little'")
    return _BYTE_ORDERS[byte_order]


@dataclass(frozen=True)
class FixedIdentifier:
    """An identifier of exactly `size` raw bytes (`tlv_fixed_identifier_t`)."""

    size: int

    def _native(self) -> tuple:
        return (0, _unsigned("size", self.size))


@dataclass(frozen=True)
class IdentifierPolicy:
    """Optional wire constraints of a variable identifier (`tlv_identifier_policy_t`).

    `forbidden_leading` lists rejected first bytes. `reject_zero_first_payload`
    rejects a zero first escaped payload; `require_minimal` rejects redundant
    leading zero digits and escaped numbers that could be inline.
    """

    forbidden_leading: bytes = b""
    reject_zero_first_payload: bool = False
    require_minimal: bool = False

    def _native(self) -> tuple:
        return (bytes(self.forbidden_leading), bool(self.reject_zero_first_payload),
                bool(self.require_minimal))


@dataclass(frozen=True)
class VariableIdentifier:
    """Inline identifier bits with an escape into continuation octets
    (`tlv_variable_identifier_t`).

    One octet suffices unless ``first & inline_mask == escape``; continuation
    octets follow while `continuation_bit` is set and carry `payload_mask`
    bits. The complete identifier, including its first octet, is at most
    `max_size` bytes.
    """

    inline_mask: int
    escape: int
    continuation_bit: int
    payload_mask: int
    max_size: int
    policy: IdentifierPolicy | None = None

    def _native(self) -> tuple:
        return (1, _byte("inline_mask", self.inline_mask), _byte("escape", self.escape),
                _byte("continuation_bit", self.continuation_bit),
                _byte("payload_mask", self.payload_mask), _unsigned("max_size", self.max_size),
                None if self.policy is None else self.policy._native())


@dataclass(frozen=True)
class FixedLength:
    """An unsigned count of `size` bytes, 1 to 8, in `byte_order` (`tlv_fixed_length_t`)."""

    size: int
    byte_order: str = "big"

    def _native(self) -> tuple:
        return (0, _unsigned("size", self.size), _big_endian(self.byte_order))


@dataclass(frozen=True)
class LengthPolicy:
    """Allowed definite count forms and limits of a variable length (`tlv_length_policy_t`).

    At least one form must be allowed. `max_long_octets` bounds the long-form
    width and `max_value` the count; `require_minimal` rejects padding and
    unnecessary long forms.
    """

    allow_short: bool = True
    allow_long: bool = True
    require_minimal: bool = False
    max_long_octets: int = 8
    max_value: int = _SIZE_MAX

    def _native(self) -> tuple:
        return (bool(self.allow_short), bool(self.allow_long), bool(self.require_minimal),
                _unsigned("max_long_octets", self.max_long_octets),
                _unsigned("max_value", self.max_value))


@dataclass(frozen=True)
class VariableLength:
    """A short count, or a prefix giving the number of following count octets
    (`tlv_variable_length_t`).

    With `long_form_bit` clear, `payload_mask` holds the count; otherwise it
    holds the number of following octets, read in `byte_order`.
    """

    long_form_bit: int
    payload_mask: int
    byte_order: str = "big"
    policy: LengthPolicy | None = None

    def _native(self) -> tuple:
        return (1, _byte("long_form_bit", self.long_form_bit),
                _byte("payload_mask", self.payload_mask), _big_endian(self.byte_order),
                None if self.policy is None else self.policy._native())


@dataclass(frozen=True)
class EscapedLength:
    """A one-byte inline count, or `escape` followed by an `extended_size`-byte
    count (`tlv_escaped_length_t`).

    Prefixes below `escape` are the count itself; prefixes above it are
    invalid. Extended counts are at least `min_extended`. Every count is at
    most `max_length`, by default the largest `extended_size`-byte count.
    """

    escape: int
    extended_size: int
    byte_order: str = "big"
    min_extended: int = 0
    max_length: int | None = None

    def _native(self) -> tuple:
        size = _unsigned("extended_size", self.extended_size)
        maximum = (self.max_length if self.max_length is not None
                   else (1 << 8 * min(size, 8)) - 1)
        return (2, _byte("escape", self.escape), size, _big_endian(self.byte_order),
                _unsigned("min_extended", self.min_extended), _unsigned("max_length", maximum))


@dataclass(frozen=True)
class PackedField:
    """An unsigned bit field of a packed header (`tlv_packed_field_t`).

    `bit_offset` counts from the least significant header bit; the header
    width and byte order are those of the enclosing packed Format, or the
    `header_size` and `byte_order` given to `read` and `write`.

    >>> flags = PackedField(5, 3)
    >>> flags.read(b"\\xa4", header_size=1)
    5
    >>> header = bytearray(b"\\xa4")
    >>> flags.write(header, 2, header_size=1)
    >>> header.hex()
    '44'
    """

    bit_offset: int
    bit_width: int

    def _native(self) -> tuple:
        return (_unsigned("bit_offset", self.bit_offset, 63),
                _unsigned("bit_width", self.bit_width, 64))

    def _storage(self, header_size: int, byte_order: str) -> tuple:
        return (_unsigned("header_size", header_size), *self._native(), _big_endian(byte_order))

    def read(self, data, *, header_size: int, byte_order: str = "big") -> int:
        """Extract the field from the `header_size`-byte integer at the start of `data`.

        Raises `TruncatedError` when `data` is shorter than the header and
        `InvalidArgError` for a field that does not fit it.
        """
        try:
            return _native.packed_field(self._storage(header_size, byte_order), data)
        except _native.Error as error:
            raise _from_native(error) from None

    def write(self, data, value: int, *, header_size: int, byte_order: str = "big") -> None:
        """Insert `value` into writable `data` in place, keeping every bit outside the field.

        Raises `ValueOverflowError` when `value` does not fit `bit_width`
        and `BufferTooShortError` when `data` is shorter than the header;
        `data` is unchanged on failure.
        """
        value = _unsigned("value", value)
        try:
            _native.packed_field(self._storage(header_size, byte_order), data, value)
        except _native.Error as error:
            raise _from_native(error) from None


@dataclass(frozen=True)
class ConstructedBit:
    """Constructed classification by a masked identifier byte (`tlv_constructed_bit_t`).

    An element is constructed when ``tag[byte_index] & mask == value``. `mask`
    must be nonzero and `value` must contain only masked bits.
    """

    byte_index: int
    mask: int
    value: int

    def _native(self) -> tuple:
        return (_unsigned("byte_index", self.byte_index), _byte("mask", self.mask),
                _byte("value", self.value))
