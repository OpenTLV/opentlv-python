# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Value and structure codecs backed by canonical C descriptors."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from enum import IntEnum
from ipaddress import IPv4Address

import _opentlv as _native


from opentlv.error import _from_native
from opentlv.format import Format, _format_specification
from opentlv.schema import CheckedStructureSchema, StructureSchema


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


# Native codec kinds, matching native/src/codec.h.
_NUMBER, _TEXT, _DIGITS = 0, 8, 9


class _ValueCodec:
    """Shared operations over one native codec specification.

    Subclasses provide ``_spec`` and may adapt Python values to and from the
    C representation; C performs every conversion and validation.
    """
    __slots__ = ()

    def _call(self, operation, value, output=None):
        try:
            return _native.value_codec(operation, self._spec, value, output)
        except _native.Error as error:
            raise _from_native(error) from None

    def _from_native(self, value):
        return value

    def _to_native(self, value):
        return value

    def decode(self, data):
        """Decode complete Value bytes through C into an owned Python value."""
        return self._from_native(self._call(0, data))

    def encode(self, value) -> bytes:
        """Return the C encoding as owned bytes."""
        return self._call(1, self._to_native(value))

    def encoded_size(self, value) -> int:
        """Validate and measure through the C size-query operation."""
        return self._call(2, self._to_native(value))

    def encode_into(self, value, output) -> int:
        """Encode into caller storage; failures leave its bytes unchanged."""
        return self._call(3, self._to_native(value), output)


class NumberEncoding(IntEnum):
    """Explicit numeric Value representation, independent of protocol tags."""
    BIG_ENDIAN = 0
    LITTLE_ENDIAN = 1
    BCD = 2


@dataclass(frozen=True)
class NumberCodec(_ValueCodec):
    """Configured uint64 codec backed by C; configuration is validated on use.

    Width zero selects minimal encoding. BCD digits specify precision (1..18);
    binary encodings require digits=0. Schema owns contextual length constraints.
    """
    encoding: NumberEncoding = NumberEncoding.BIG_ENDIAN
    width: int = 0
    digits: int = 0

    @property
    def _spec(self):
        return (_NUMBER, int(self.encoding), self.width, self.digits)


class ValueCodec(_ValueCodec, enum.Enum):
    """Static C Value codecs, selected explicitly rather than by tag.

    Unsigned codecs convert ``int`` with an exact wire width; integers outside
    their C type raise ``OverflowError``. ``INT64_MINIMAL_BE`` uses the
    shortest big-endian two's-complement form. ``BYTES`` copies arbitrary
    bytes. ``IPV4`` converts an ``ipaddress.IPv4Address`` and ``IPV4_LIST`` a
    tuple of them, preserving order and duplicates; encoding accepts anything
    ``IPv4Address`` accepts.

    >>> ValueCodec.UINT16_BE.decode(b"\\x01\\x02")
    258
    >>> ValueCodec.IPV4.encode("192.0.2.1").hex()
    'c0000201'
    """
    UINT8 = 1
    UINT16_BE = 2
    UINT16_LE = 3
    UINT32_BE = 4
    UINT32_LE = 5
    INT64_MINIMAL_BE = 6
    BYTES = 7
    IPV4 = 10
    IPV4_LIST = 11

    @property
    def _spec(self):
        return (self.value, 0, 0, 0)

    def _from_native(self, value):
        if self is ValueCodec.IPV4:
            return IPv4Address(value)
        if self is ValueCodec.IPV4_LIST:
            return tuple(IPv4Address(address) for address in value)
        return value

    def _to_native(self, value):
        if self is ValueCodec.IPV4:
            return IPv4Address(value).packed
        if self is ValueCodec.IPV4_LIST:
            return b"".join(IPv4Address(address).packed for address in value)
        return value


def _text_bytes(value):
    if not isinstance(value, str):
        raise TypeError("str required")
    # C validates the repertoire, so non-ASCII input reaches it as UTF-8.
    return value.encode("utf-8")


class TextAlphabet(IntEnum):
    """Accepted logical text characters; protocol labels do not select them."""
    ASCII_PRINTABLE = 0
    """Printable ASCII including space (0x20..0x7E)."""
    ASCII_ALNUM = 1
    """ASCII letters and decimal digits only."""


@dataclass(frozen=True)
class TextCodec(_ValueCodec):
    """Configured ASCII text codec backed by C; configuration is validated on use.

    Width zero selects variable-width text. A nonzero width is fixed: with
    ``zero_padding`` decode strips trailing zero bytes and encode pads to the
    width, otherwise text must fill it. Embedded zeros are rejected.

    >>> TextCodec(width=4, zero_padding=True).encode("ab")
    b'ab\\x00\\x00'
    """
    alphabet: TextAlphabet = TextAlphabet.ASCII_PRINTABLE
    width: int = 0
    zero_padding: bool = False

    @property
    def _spec(self):
        return (_TEXT, int(self.alphabet), self.width, int(bool(self.zero_padding)))

    def _to_native(self, value):
        return _text_bytes(value)


@dataclass(frozen=True)
class DigitsCodec(_ValueCodec):
    """Packed decimal digit strings backed by C, retaining leading zeros.

    Digits are packed high nibble first with trailing F padding. Width zero
    selects minimal encoding; a nonzero width pads to that many bytes.

    >>> DigitsCodec().decode(b"\\x01\\x23\\x4f")
    '01234'
    >>> DigitsCodec(width=3).encode("0123").hex()
    '0123ff'
    """
    width: int = 0

    @property
    def _spec(self):
        return (_DIGITS, 0, self.width, 0)

    def _to_native(self, value):
        return _text_bytes(value)


class StructureCodec:
    """Maps one complete TLV sequence to one application object through C.

    ``tlv_structure_decode`` validates framing, nesting and the optional
    ``StructureSchema`` or ``CheckedStructureSchema`` before ``decode(data)``
    receives the sequence as owned bytes. ``tlv_structure_encode`` validates
    the bytes-like result of ``encode(value)`` against the same rules before
    it is returned; ``encode`` runs once per operation. Without ``decode`` or
    ``encode`` that direction raises ``UnsupportedError``. Callback exceptions
    propagate unchanged. Encoding requires a writable ``format``.
    """
    __slots__ = ("format", "schema", "max_depth", "max_elements", "_decode", "_encode")

    def __init__(self, format: Format | None = None, schema=None, *, decode=None, encode=None,
                 max_depth: int = 32, max_elements: int = 100_000) -> None:
        if schema is not None and not isinstance(schema, (StructureSchema,
                                                          CheckedStructureSchema)):
            raise TypeError("StructureSchema or CheckedStructureSchema required")
        if any(callback is not None and not callable(callback) for callback in (decode, encode)):
            raise TypeError("decode and encode must be callable or None")
        self.format = format
        self.schema = schema
        self.max_depth = max_depth
        self.max_elements = max_elements
        self._decode = decode
        self._encode = encode

    def _call(self, operation, value, output=None):
        schema = self.schema
        if isinstance(schema, CheckedStructureSchema):
            schema = schema._capsule
        elif schema is not None:
            schema = schema._to_native()
        try:
            return _native.structure_codec(operation, value, _format_specification(self.format),
                                           schema, self.max_depth, self.max_elements,
                                           self._decode, self._encode, output)
        except _native.Error as error:
            raise _from_native(error) from None

    def decode(self, data):
        """Validate a complete sequence, then return ``decode``'s object."""
        return self._call(0, data)

    def encode(self, value) -> bytes:
        """Return the validated sequence ``encode`` produces for ``value``."""
        return self._call(1, value)

    def encoded_size(self, value) -> int:
        """Return the size of the validated sequence for ``value``."""
        return self._call(2, value)

    def encode_into(self, value, output) -> int:
        """Encode into caller storage; failures leave its bytes unchanged."""
        return self._call(3, value, output)
