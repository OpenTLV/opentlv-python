# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Python bindings for OpenTLV.

This package wraps ``_opentlv``, the native extension that registers
the public OpenTLV C API as Python callables, into an idiomatic API that
follows the OpenTLV conceptual model: see [Language
bindings](https://github.com/marekcingel/OpenTLV/blob/main/docs/concepts/bindings.md).

Currently bound: `Reader`, `TreeReader`, `Query`/`QueryMatcher`, Visitors,
`Writer`, `TreeWriter`, `Document`/`Node`, `DocumentBuilder`, `Element`, `Tag`,
`Format`, `FixedFormat`, `ComposedFormat` with its field encodings,
`LengthSchema`/`StructureSchema` with its `CheckedStructureSchema` handle,
`ValueConstraint`, the `Generator` wire generator and the
`OpenTLVError` exception hierarchy. The `codec` submodule exposes the generic
C Value codecs (`NumberCodec`, `SchemaNumberCodec`, `ValueCodec`, `TextCodec`,
`DigitsCodec`), the
`StructureCodec` sequence binding and EMV amounts. Builtin protocol codecs
remain a capability gap.
"""

from _opentlv import version_string

from opentlv.definition import Definition, DefinitionRegistry
from opentlv import codec
from opentlv.codec import (DigitsCodec, NumberCodec, NumberEncoding, SchemaNumberCodec,
                           StructureCodec, TextAlphabet, TextCodec, ValueCodec)
from opentlv.document import Document, DocumentBuilder, Node, SourceLocation
from opentlv.element import Element
from opentlv.location import Location
from opentlv.error import (
    BufferTooShortError,
    EndError,
    InvalidArgError,
    InvalidSyntaxError,
    InvalidLengthError,
    InvalidTagError,
    InvalidTagSizeError,
    InvalidValueError,
    LimitError,
    NullArgError,
    NativeSizeError,
    NeedMoreDataError,
    InvalidStateError,
    CallbackError,
    TruncatedError,
    OpenTLVError,
    OutOfMemoryError,
    SchemaError,
    InvalidSchemaError,
    UnsupportedError,
    ValueOverflowError,
    VisitorError,
)
from opentlv.composed_format import ComposedFormat
from opentlv.field import (ConstructedBit, EscapedLength, FixedIdentifier, FixedLength,
                           IdentifierPolicy, LengthPolicy, PackedField, VariableIdentifier,
                           VariableLength)
from opentlv.fixed_format import FixedFormat
from opentlv.format import Format
from opentlv.format_operations import Encoding
from opentlv.generator import Generator, GeneratorCandidate
from opentlv.reader import Reader, read, read_element
from opentlv.cursor import Decoded, Layout, TreeItem, TreeEvent, TreeEventKind, TreeReader, Visit
from opentlv.query import Query, QueryMatcher
from opentlv.tree_writer import TreeWriter
from opentlv.schema import CheckedStructureSchema, SchemaBounds, SchemaDiagnostic, SchemaDiagnosticReport, Kind, LengthRule, LengthSchema, SchemaOrder, UnknownPolicy, StructureGroup, StructureRule, StructureSchema, ValueConstraint, ValueConstraintKind
from opentlv.tag import Tag
from opentlv.writer import Writer, element_encoded_size, encoded_size, write_element

__version__ = version_string()
from opentlv.program import (QueryProgram, QueryExecution, QueryMatch, QueryProvider,
                             QueryCodecProvider, QueryRule, QuerySchema, QueryTagAdapter,
                             QueryDefinitionResolver, query_emv_resolve)

__all__ = [
    "ReaderOperation", "WriterOperation", "QueryErrorKind", "QueryCause", "SchemaIssue",
    "SchemaDefinitionKind", "SchemaCause", "CodecOperation", "CodecCause", "CodecViolation",
    "CodecReason", "Severity",
    "QueryProgram", "QueryExecution", "QueryMatch", "QueryProvider", "QueryCodecProvider",
    "QueryRule", "QuerySchema",
    "QueryTagAdapter", "QueryDefinitionResolver", "query_emv_resolve",
    "__version__",
    "BufferTooShortError",
    "CheckedStructureSchema",
    "ComposedFormat",
    "ConstructedBit",
    "Document",
    "DocumentBuilder",
    "Element",
    "Node",
    "codec",
    "Definition",
    "DefinitionRegistry",
    "DigitsCodec",
    "NumberCodec",
    "NumberEncoding",
    "Encoding",
    "EndError",
    "EscapedLength",
    "FixedFormat",
    "FixedIdentifier",
    "FixedLength",
    "Format",
    "Generator",
    "GeneratorCandidate",
    "IdentifierPolicy",
    "InvalidArgError",
    "InvalidSyntaxError",
    "InvalidLengthError",
    "InvalidTagError",
    "InvalidTagSizeError",
    "InvalidValueError",
    "Kind",
    "LengthPolicy",
    "LengthRule",
    "LengthSchema",
    "LimitError",
    "Location",
    "NullArgError",
    "NativeSizeError",
    "NeedMoreDataError",
    "InvalidStateError",
    "CallbackError",
    "TruncatedError",
    "OpenTLVError",
    "OutOfMemoryError",
    "PackedField",
    "Reader",
    "read",
    "read_element",
    "Decoded",
    "Layout",
    "TreeItem",
    "TreeEvent",
    "TreeEventKind",
    "TreeReader",
    "TreeWriter",
    "Visit",
    "SourceLocation",
    "Query",
    "QueryMatcher",
    "SchemaError",
    "SchemaNumberCodec",
    "InvalidSchemaError",
    "StructureRule",
    "SchemaOrder",
    "SchemaBounds",
    "SchemaDiagnostic",
    "SchemaDiagnosticReport",
    "UnknownPolicy",
    "StructureGroup",
    "StructureSchema",
    "StructureCodec",
    "Tag",
    "TextAlphabet",
    "TextCodec",
    "UnsupportedError",
    "ValueCodec",
    "ValueConstraint",
    "ValueConstraintKind",
    "ValueOverflowError",
    "VariableIdentifier",
    "VariableLength",
    "VisitorError",
    "Writer",
    "encoded_size",
    "element_encoded_size",
    "write_element",
]

from opentlv.diagnostic import (
    ReaderOperation, WriterOperation, QueryErrorKind, QueryCause, SchemaIssue,
    SchemaDefinitionKind, SchemaCause, CodecOperation, CodecCause, CodecViolation, CodecReason,
    Severity,
)
