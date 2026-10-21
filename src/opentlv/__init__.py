# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Python bindings for OpenTLV.

This package wraps ``_opentlv``, the native extension that registers
the public OpenTLV C API as Python callables, into an idiomatic API that
follows the OpenTLV conceptual model: see [Language
bindings](https://github.com/marekcingel/OpenTLV/blob/main/docs/concepts/bindings.md).

Currently bound: `Reader`, `TreeReader`, `Query`/`QueryMatcher`, Visitors,
`Writer`, `TreeWriter`, `Document`/`Node`, `DocumentBuilder`, `Element`, `Tag`,
`Format`, `FixedFormat`, `LengthSchema`/`StructureSchema` and the
`OpenTLVError` exception hierarchy. The `codec` submodule exposes configured numeric codecs and EMV amounts.
Other public C codecs remain a capability gap.
"""

from _opentlv import version_string

from opentlv.definition import Definition, DefinitionRegistry
from opentlv import codec
from opentlv.codec import NumberCodec, NumberEncoding
from opentlv.document import Document, DocumentBuilder, Node
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
from opentlv.fixed_format import FixedFormat
from opentlv.format import Format
from opentlv.reader import Reader, read
from opentlv.cursor import Decoded, Layout, TreeItem, TreeEvent, TreeEventKind, TreeReader, Visit
from opentlv.query import Query, QueryMatcher
from opentlv.tree_writer import TreeWriter
from opentlv.schema import SchemaBounds, SchemaDiagnostic, SchemaDiagnosticReport, Kind, LengthRule, LengthSchema, SchemaOrder, UnknownPolicy, StructureGroup, StructureRule, StructureSchema
from opentlv.tag import Tag
from opentlv.writer import Writer, element_encoded_size, encoded_size

__version__ = version_string()
from opentlv.program import (QueryProgram, QueryExecution, QueryMatch, QueryProvider, QueryRule,
                             QuerySchema, QueryTagAdapter, QueryDefinitionResolver, query_emv_resolve)

__all__ = [
    "ReaderOperation", "WriterOperation", "QueryErrorKind", "QueryCause", "SchemaIssue",
    "SchemaDefinitionKind", "SchemaCause", "CodecOperation", "CodecCause", "CodecViolation",
    "CodecReason", "Severity",
    "QueryProgram", "QueryExecution", "QueryMatch", "QueryProvider", "QueryRule", "QuerySchema",
    "QueryTagAdapter", "QueryDefinitionResolver", "query_emv_resolve",
    "__version__",
    "BufferTooShortError",
    "Document",
    "DocumentBuilder",
    "Element",
    "Node",
    "codec",
    "Definition",
    "DefinitionRegistry",
    "NumberCodec",
    "NumberEncoding",
    "EndError",
    "FixedFormat",
    "Format",
    "InvalidArgError",
    "InvalidSyntaxError",
    "InvalidLengthError",
    "InvalidTagError",
    "InvalidTagSizeError",
    "InvalidValueError",
    "Kind",
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
    "Reader",
    "read",
    "Decoded",
    "Layout",
    "TreeItem",
    "TreeEvent",
    "TreeEventKind",
    "TreeReader",
    "TreeWriter",
    "Visit",
    "Query",
    "QueryMatcher",
    "SchemaError",
    "InvalidSchemaError",
    "StructureRule",
    "SchemaOrder",
    "SchemaBounds",
    "SchemaDiagnostic",
    "SchemaDiagnosticReport",
    "UnknownPolicy",
    "StructureGroup",
    "StructureSchema",
    "Tag",
    "UnsupportedError",
    "ValueOverflowError",
    "VisitorError",
    "Writer",
    "encoded_size",
    "element_encoded_size",
]

from opentlv.diagnostic import (
    ReaderOperation, WriterOperation, QueryErrorKind, QueryCause, SchemaIssue,
    SchemaDefinitionKind, SchemaCause, CodecOperation, CodecCause, CodecViolation, CodecReason,
    Severity,
)
