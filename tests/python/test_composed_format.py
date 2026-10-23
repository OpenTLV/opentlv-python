# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import gc

import pytest
import _opentlv
from opentlv import (ComposedFormat, ConstructedBit, Document, Element, Encoding, EndError,
                     EscapedLength, FixedFormat, FixedIdentifier, FixedLength, Format,
                     IdentifierPolicy, InvalidArgError, InvalidLengthError, InvalidTagError,
                     Kind, LengthPolicy, PackedField, QueryProgram, Reader, StructureRule,
                     StructureSchema, Tag, TreeReader, TreeWriter, TruncatedError,
                     VariableIdentifier, VariableLength, Writer, element_encoded_size,
                     encoded_size)

# Core's EMV and LLDP builtins expressed through the generic compositions.
EMV = dict(
    tag=VariableIdentifier(0x1F, 0x1F, 0x80, 0x7F, 2,
                           IdentifierPolicy(b"\x00", reject_zero_first_payload=True)),
    length=VariableLength(0x80, 0x7F, policy=LengthPolicy(max_long_octets=2, max_value=65535)),
    constructed=ConstructedBit(0, 0x20, 0x20))
LLDP = dict(header_size=2, tag=PackedField(9, 7), length=PackedField(0, 9))
FCI = bytes.fromhex("6F1A840E315041592E5359532E4444463031A5088801025F2D02656E")
# A proprietary format: one-byte tag, inline count below 0xFF or 0xFF and a
# two-byte big-endian count, and constructed tags with the top bit set.
PROPRIETARY = dict(tag=FixedIdentifier(1), length=EscapedLength(0xFF, 2),
                   constructed=ConstructedBit(0, 0x80, 0x80))


def items(data, format):
    return [(item.depth, item.element.tag.data, bytes(item.element.value), item.constructed)
            for item in TreeReader(data, format)]


@pytest.mark.skipif(not _opentlv.HAS_EMV, reason="EMV disabled")
def test_variable_composition_matches_emv_builtin():
    format = Format.variable(**EMV)
    assert items(FCI, format) == items(FCI, Format.EMV)
    assert format.encode(b"\x5f\x2d", b"en") == Format.EMV.encode(b"\x5f\x2d", b"en")
    assert format.measure(b"\x6f", bytes(200)) == Encoding(3, 200, 0, 203)
    with pytest.raises(InvalidTagError):
        format.decode(b"\x00\x00")


@pytest.mark.skipif(not _opentlv.HAS_LLDP, reason="LLDP disabled")
@pytest.mark.parametrize("length", [0, 255, 511])
def test_packed_composition_matches_lldp_builtin(length):
    format = Format.packed(**LLDP)
    wire = format.encode(b"\x7f", b"\xaa" * length)
    assert wire == Format.LLDP.encode(b"\x7f", b"\xaa" * length)
    decoded = format.decode(wire + b"trailing")
    assert decoded.element == Element(Tag(b"\x7f"), memoryview(b"\xaa" * length))
    assert len(decoded.encoded) == len(wire)


def test_packed_tag_size_and_validation():
    format = Format.packed(header_size=2, tag=PackedField(4, 12), length=PackedField(0, 4),
                           byte_order="little", tag_size=3)
    assert format.encode(b"\x00\x0a\xbc", b"xy") == b"\xc2\xab" + b"xy"
    assert format.decode(b"\xc2\xabxy").element.tag == Tag(b"\x00\x0a\xbc")
    with pytest.raises(InvalidArgError):
        Format.packed(header_size=1, tag=PackedField(0, 5), length=PackedField(4, 4))
    with pytest.raises(ValueError):
        Format.packed(header_size=4, tag=PackedField(0, 17), length=PackedField(17, 8))


def test_packed_field_reads_and_writes_bits_through_core():
    from opentlv import BufferTooShortError, ValueOverflowError
    tag, length = LLDP["tag"], LLDP["length"]
    assert tag.read(b"\x02\x07", header_size=2) == 1
    assert length.read(b"\x02\x07\xff", header_size=2) == 7
    assert length.read(b"\x07\x02", header_size=2, byte_order="little") == 7
    header = bytearray(b"\x02\x07")
    length.write(header, 0x1FF, header_size=2)
    assert header == b"\x03\xff" and tag.read(header, header_size=2) == 1
    tag.write(memoryview(header), 0x7F, header_size=2)
    assert header == b"\xff\xff"
    for value, data, error in ((0x200, header, ValueOverflowError),
                               (1, bytearray(b"\xff"), BufferTooShortError)):
        before = bytes(data)
        with pytest.raises(error):
            length.write(data, value, header_size=2)
        assert data == before
    with pytest.raises(TruncatedError):
        length.read(b"\x02", header_size=2)
    with pytest.raises(InvalidArgError):
        PackedField(5, 4).read(b"\x00", header_size=1)
    with pytest.raises(BufferError):
        length.write(b"\x00\x00", 1, header_size=2)
    with pytest.raises(ValueError):
        length.write(header, -1, header_size=2)
    with pytest.raises(ValueError):
        length.read(header, header_size=2, byte_order="middle")


def test_escaped_composition_inline_extended_and_tag_only():
    format = Format.escaped(FixedIdentifier(1), EscapedLength(0xFF, 2), tag_only=[b"\x00"])
    assert format.encode(b"\x07", b"abc") == b"\x07\x03abc"
    extended = format.encode(b"\x07", bytes(300))
    assert extended[:4] == b"\x07\xff\x01\x2c"
    assert format.encode(Tag(b"\x00"), b"") == b"\x00"
    assert [element.tag.data for element in Reader(b"\x00" + extended, format)] == [b"\x00", b"\x07"]
    with pytest.raises(InvalidLengthError):
        format.encode(b"\x00", b"x")


def test_fixed_fields_cover_ltv_scope_and_tagged_binary():
    ltv = Format.fields(FixedIdentifier(1), FixedLength(1), element_order="ltv",
                        length_scope="tag_and_value")
    assert ltv.encode(b"\x02", b"ab") == b"\x03\x02ab"
    assert ltv.decode(b"\x03\x02ab").element == Element(Tag(b"\x02"), memoryview(b"ab"))
    tagged = Format.fields(FixedIdentifier(1), FixedLength(2, "little"), tag_only=[b"\xff"])
    assert tagged.encode(b"\xff", b"") == b"\xff"
    assert tagged.encode(b"\x01", b"a") == b"\x01\x01\x00a"


def test_mixed_fields_use_generic_field_composition():
    format = Format.fields(VariableIdentifier(0x1F, 0x1F, 0x80, 0x7F, 3), FixedLength(2, "little"),
                           tag_only=[b"\x00"], constructed=ConstructedBit(0, 0x20, 0x20))
    wire = format.encode(b"\x00", b"") + format.encode(b"\x9f\x02", b"ab")
    assert wire == b"\x00" + b"\x9f\x02\x02\x00ab"
    assert [(element.tag.data, bytes(element.value)) for element in Reader(wire, format)] == [
        (b"\x00", b""), (b"\x9f\x02", b"ab")]
    nested = Format.fields(FixedIdentifier(1), VariableLength(0x80, 0x7F),
                           constructed=ConstructedBit(0, 0x80, 0x80))
    assert items(b"\x81\x03\x01\x01z", nested) == [
        (0, b"\x81", b"\x01\x01z", True), (1, b"\x01", b"z", False)]


@pytest.mark.skipif(not _opentlv.HAS_EMV, reason="EMV disabled")
def test_tagged_variable_fields_keep_constructed_classification():
    format = Format.variable(**EMV, tag_only=[b"\x01"])
    assert items(b"\x01" + FCI, format) == [(0, b"\x01", b"", False)] + items(FCI, Format.EMV)


@pytest.mark.parametrize("compose", [
    lambda: Format.fields(FixedIdentifier(0), FixedLength(1)),
    lambda: Format.fields(FixedIdentifier(1), FixedLength(9)),
    lambda: Format.fields(VariableIdentifier(0, 0, 0x80, 0x7F, 2), FixedLength(1)),
    lambda: Format.fields(FixedIdentifier(1), VariableLength(0x80, 0x80)),
    lambda: Format.escaped(FixedIdentifier(1), EscapedLength(0, 2)),
    lambda: Format.packed(header_size=1, tag=PackedField(0, 0), length=PackedField(1, 7)),
    lambda: Format.fields(FixedIdentifier(1), FixedLength(1), element_order="ltv",
                          tag_only=[b"\x00"]),
    lambda: Format.fields(FixedIdentifier(1), FixedLength(1), constructed=ConstructedBit(0, 0, 0)),
    lambda: Format.fields(FixedIdentifier(1), FixedLength(1), constructed=ConstructedBit(0, 1, 2)),
])
def test_core_rejects_invalid_configuration(compose):
    with pytest.raises(InvalidArgError):
        compose()


def test_python_rejects_wrong_types_and_ranges():
    with pytest.raises(TypeError):
        Format.fields(FixedLength(1), FixedLength(1))
    with pytest.raises(TypeError):
        Format.variable(FixedIdentifier(1), VariableLength(0x80, 0x7F))
    with pytest.raises(TypeError):
        Format.escaped(FixedIdentifier(1), FixedLength(1))
    with pytest.raises(ValueError):
        Format.fields(FixedIdentifier(1), FixedLength(1, "middle"))
    with pytest.raises(ValueError):
        Format.fields(FixedIdentifier(1), FixedLength(1), length_scope="tag")
    with pytest.raises(ValueError):
        Format.fields(VariableIdentifier(0x100, 0, 0x80, 0x7F, 2), FixedLength(1))
    with pytest.raises(TypeError):
        ComposedFormat()


def test_equal_configurations_share_one_native_format():
    first = Format.escaped(**PROPRIETARY)
    assert Format.escaped(**PROPRIETARY) is first
    assert Format.fields(**PROPRIETARY) is first
    assert Format.escaped(**PROPRIETARY, tag_only=[b"\x00"]) is not first
    assert repr(first).startswith("Format.escaped(tag=FixedIdentifier(size=1)")
    del first
    gc.collect()
    assert Format.escaped(**PROPRIETARY).can_read


def proprietary_wire(format):
    writer = TreeWriter(512, format)
    writer.begin(b"\x81")
    writer.write(Element(Tag(b"\x01"), b"A" * 300))
    writer.write(Element(Tag(b"\x02"), b"short"))
    writer.end()
    return writer.finish()


def test_proprietary_format_through_reader_document_query_and_schema():
    format = Format.escaped(**PROPRIETARY)
    wire = proprietary_wire(format)
    assert wire[:4] == b"\x81\xff\x01\x37"
    assert items(wire, format) == [(0, b"\x81", wire[4:], True), (1, b"\x01", b"A" * 300, False),
                                   (1, b"\x02", b"short", False)]
    with Document(wire, format) as document:
        assert bytes(document.find_path("81/02").value) == b"short"
        program = QueryProgram("//02", format=Format.escaped(**PROPRIETARY))
        assert [bytes(node.value) for node in document.select(program)] == [b"short"]
        assert document.encode() == wire
        assert document.encode(format) == wire
    assert QueryProgram("count(//01)", format=format).evaluate(wire) == 1
    schema = StructureSchema([StructureRule(b"\x81", min_occurs=1, children=StructureSchema([
        StructureRule(b"\x01", min_occurs=1), StructureRule(b"\x02", kind=Kind.PRIMITIVE)]))])
    schema.validate(wire, format)


def test_writer_and_sizes_accept_composed_formats():
    format = Format.fields(FixedIdentifier(2), EscapedLength(0x80, 1))
    writer = Writer(format)
    writer.write(Tag(b"\x01\x02"), bytes(200))
    assert writer.bytes()[:4] == b"\x01\x02\x80\xc8"
    assert encoded_size(b"\x01\x02", 200, format) == 204
    assert element_encoded_size(Element(Tag(b"\x01\x02"), b"ab"), format) == 5
    assert writer.format is format


def test_operations_on_builtin_and_fixed_formats():
    fixed = FixedFormat(1, 2, "little")
    assert fixed.can_read and fixed.can_write
    assert fixed.encode(b"\x01", b"ab") == b"\x01\x02\x00ab"
    assert fixed.measure(Tag(b"\x01"), b"ab") == Encoding(3, 2, 0, 5)
    decoded = fixed.decode(bytearray(b"\x01\x02\x00abZZ"))
    assert decoded.element == Element(Tag(b"\x01"), memoryview(b"ab"))
    assert decoded.layout.length == (1, 2)
    assert decoded.preserve() == b"\x01\x02\x00ab"
    if _opentlv.HAS_BER:
        assert Format.BER.can_read and Format.BER.can_write
        assert Format.BER.encode(b"\x84", b"x") == b"\x84\x01x"
        assert Format.BER.decode(b"\x84\x01x").element.tag == Tag(b"\x84")


def test_operation_failures_carry_format_detail():
    format = Format.escaped(**PROPRIETARY)
    with pytest.raises(EndError):
        format.decode(b"")
    with pytest.raises(TruncatedError) as truncated:
        format.decode(b"\x01\xff\x01")
    error = truncated.value
    assert (error.operation, error.region, error.tag_offset, error.length_offset) == (
        "decode", "length", 0, 1)
    assert error.raw_length == b"\xff\x01"
    assert error.location.domain == "input"
    with pytest.raises(InvalidLengthError) as overflow:
        format.encode(b"\x01", bytes(0x10000))
    assert overflow.value.operation == "measure"
    assert overflow.value.raw_length is None
