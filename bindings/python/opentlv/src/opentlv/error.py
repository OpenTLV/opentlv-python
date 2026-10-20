# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Python exceptions mapped from OpenTLV result codes."""

from __future__ import annotations

from typing import Optional
from opentlv.location import Location
from opentlv.diagnostic import QueryErrorKind, CodecOperation, CodecCause, CodecViolation, CodecReason, SchemaDefinitionKind, Severity

import _opentlv as _native


class OpenTLVError(Exception):
    """Base class for every OpenTLV error.

    Mirrors a non-zero ``tlv_result_t`` from the OpenTLV C API. `code` is the
    raw result code; the rest carry the structured diagnostic detail the C
    API reports for a failed operation, when available, and are `None`
    otherwise. `location` always holds a `Location`; its kind is `unknown`
    when evidence is unavailable. `offset` projects its known start.
    `offset`, `expected`, `actual`, `operation` and `tag` apply to
    both reading and writing failures; `length`, `required` and `available`
    describe buffer bounds (`length` is writer-only). Reader `required` is the
    required extent of the failing region. Field offsets and enclosing_end
    preserve the Reader's absolute source coordinates.
    `raw_length` and `declared_length` preserve reader length diagnostics
    without narrowing the decoded value. For writer failures, `required` is
    the exact encoded size needed to grow the output buffer. `codec_detail`
    optionally carries conversion evidence; its delegated `schema` is an owned
    `SchemaDiagnostic`.
    """

    def __init__(self, code: int, offset: Optional[int] = None, expected: Optional[str] = None,
                 actual: Optional[str] = None, operation: Optional[str] = None,
                 tag: Optional[bytes] = None, length: Optional[int] = None,
                 required: Optional[int] = None, available: Optional[int] = None,
                 raw_length: Optional[bytes] = None, declared_length: Optional[int] = None,
                 tag_offset: Optional[int] = None, length_offset: Optional[int] = None,
                 value_offset: Optional[int] = None, enclosing_end: Optional[int] = None, kind: Optional[str] = None,
                 location: Location | None = None) -> None:
        super().__init__(_native.result_string(code))
        self.location = location if location is not None else Location()
        self.kind = kind
        self.code = code
        self.offset = offset
        self.expected = expected
        self.actual = actual
        self.operation = operation
        self.tag = tag
        self.length = length
        self.required = required
        self.available = available
        self.raw_length = raw_length
        self.declared_length = declared_length
        self.tag_offset = tag_offset
        self.length_offset = length_offset
        self.value_offset = value_offset
        self.enclosing_end = enclosing_end
        self.codec_detail = None


class BufferTooShortError(OpenTLVError):
    """A caller-supplied destination or workspace is too small."""


class TruncatedError(OpenTLVError):
    """Final input ends inside an element; supply complete input."""


class InvalidLengthError(OpenTLVError):
    """A length is malformed, out of range, or not representable natively."""


class NullArgError(OpenTLVError):
    """A required argument is missing."""


class OutOfMemoryError(OpenTLVError):
    """An allocation failed."""


class EndError(OpenTLVError):
    """Normal end of iteration, or an empty single-read region; not a failure."""


class InvalidTagError(OpenTLVError):
    """A tag is malformed or invalid for the format or standard."""


class VisitorError(OpenTLVError):
    """A visitor callback requested an error stop."""


class LimitError(OpenTLVError):
    """A configured depth, size, or element-count limit was exceeded."""


class SchemaError(OpenTLVError):
    """Input violates a schema rule."""


class InvalidArgError(OpenTLVError):
    """An argument has an invalid value that no more specific error describes."""


class InvalidTagSizeError(OpenTLVError):
    """Tag size violates the range supported by the operation."""


class InvalidSyntaxError(OpenTLVError):
    """Text does not match the requested grammar, such as Query syntax.

    Mirrors ``TLV_ERR_SYNTAX`` (``Syntax``/``ErrSyntax``/``SYNTAX`` in the other
    bindings); named to avoid shadowing Python's built-in ``SyntaxError``.
    """


class ValueOverflowError(OpenTLVError):
    """An unsigned value cannot fit the requested numeric width."""


class InvalidValueError(OpenTLVError):
    """Data or its application representation is invalid for the requested interpretation."""


class UnsupportedError(OpenTLVError):
    """A valid requested capability or representation is not implemented."""


class InvalidSchemaError(OpenTLVError):
    """A schema definition is invalid independently of the input."""


class NativeSizeError(OpenTLVError):
    """A logical size exceeds the native address space."""


class NeedMoreDataError(OpenTLVError):
    """Non-final input is exhausted or incomplete; supply more data or EOF."""


class InvalidStateError(OpenTLVError):
    """The operation is forbidden by the current lifecycle state."""


class CallbackError(OpenTLVError):
    """A provider violated its callback contract."""


# Keyed by tlv_result_t; values come from the native module, not hard-coded numbers.
_ERROR_TYPES = {
    _native.RESULT_BUFFER_TOO_SHORT: BufferTooShortError,
    _native.RESULT_INVALID_LENGTH: InvalidLengthError,
    _native.RESULT_NULL_ARG: NullArgError,
    _native.RESULT_OUT_OF_MEMORY: OutOfMemoryError,
    _native.RESULT_END: EndError,
    _native.RESULT_INVALID_TAG: InvalidTagError,
    _native.RESULT_VISITOR: VisitorError,
    _native.RESULT_LIMIT: LimitError,
    _native.RESULT_SCHEMA: SchemaError,
    _native.RESULT_INVALID_ARG: InvalidArgError,
    _native.RESULT_INVALID_TAG_SIZE: InvalidTagSizeError,
    _native.RESULT_SYNTAX: InvalidSyntaxError,
    _native.RESULT_OVERFLOW: ValueOverflowError,
    _native.RESULT_INVALID_VALUE: InvalidValueError,
    _native.RESULT_UNSUPPORTED: UnsupportedError,
    _native.RESULT_INVALID_SCHEMA: InvalidSchemaError,
    _native.RESULT_NATIVE_SIZE: NativeSizeError,
    _native.RESULT_NEED_MORE_DATA: NeedMoreDataError,
    _native.RESULT_INVALID_STATE: InvalidStateError,
    _native.RESULT_CALLBACK: CallbackError,
    _native.RESULT_TRUNCATED: TruncatedError,
}


def _from_native(error: "_native.Error") -> OpenTLVError:
    """Translates a native `_opentlv.Error` into a typed `OpenTLVError`.

    `error.args[0]` is a dict with a "code" key and whichever diagnostic keys
    the failing native call supports; a missing key means the same as an
    explicit `None`.
    """
    fields = error.args[0]
    code = fields["code"]
    error_type = _ERROR_TYPES.get(code, OpenTLVError)
    result = error_type(code, offset=fields.get("offset"), expected=fields.get("expected"),
                       actual=fields.get("actual"), operation=fields.get("operation"),
                       tag=fields.get("tag"), length=fields.get("length"),
                       required=fields.get("required"), available=fields.get("available"),
                       raw_length=fields.get("raw_length"), declared_length=fields.get("declared_length"),
                       tag_offset=fields.get("tag_offset"), length_offset=fields.get("length_offset"),
                       value_offset=fields.get("value_offset"), enclosing_end=fields.get("enclosing_end"),
                       kind=fields.get("kind"),
                       location=Location(**fields.get("location", {})))
    result.severity = Severity(fields.get("severity", 0))
    result.path = tuple(fields.get("path", ())) if fields.get("has_path", False) else None
    result.path_omitted = fields.get("path_omitted", 0)
    result.contexts = tuple(fields.get("contexts", ()))
    result.codec_detail = fields.get("codec_detail")
    if result.codec_detail and "schema" in result.codec_detail:
        from opentlv.schema import _diagnostic_from_native
        result.codec_detail["schema"] = _diagnostic_from_native(result.codec_detail["schema"])
    result.definition_kind = SchemaDefinitionKind(fields.get("definition_kind", 0))
    result.definition_index = fields.get("definition_index")
    # Query-only fields; common evidence and codec_detail stay on the error itself.
    result.query = {key: fields.get(key) for key in (
        "query_kind", "query_kind_name", "expression", "limit", "configured")} if "query_kind" in fields else None
    if result.query is not None:
        result.query["query_kind"] = QueryErrorKind(result.query["query_kind"])
        result.query["expression"] = Location(**result.query["expression"])
    if result.codec_detail:
        for key, category in (("operation", CodecOperation), ("cause", CodecCause), ("violation", CodecViolation),
                              ("reason", CodecReason)):
            result.codec_detail[key] = category(result.codec_detail[key])
    if "applied" in fields:
        result.applied = fields["applied"]
    if "rule" in fields:
        result.rule = fields["rule"]
        result.schema = fields["schema"]
    return result
