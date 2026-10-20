# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

import _opentlv as native

from opentlv.error import (
    InvalidSchemaError,
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
    SchemaError,
    UnsupportedError,
    ValueOverflowError,
    VisitorError,
    _from_native,
)

KNOWN = [
    (native.RESULT_BUFFER_TOO_SHORT, BufferTooShortError),
    (native.RESULT_INVALID_LENGTH, InvalidLengthError),
    (native.RESULT_NULL_ARG, NullArgError),
    (native.RESULT_OUT_OF_MEMORY, OutOfMemoryError),
    (native.RESULT_END, EndError),
    (native.RESULT_INVALID_TAG, InvalidTagError),
    (native.RESULT_VISITOR, VisitorError),
    (native.RESULT_LIMIT, LimitError),
    (native.RESULT_SCHEMA, SchemaError),
    (native.RESULT_INVALID_ARG, InvalidArgError),
    (native.RESULT_INVALID_TAG_SIZE, InvalidTagSizeError),
    (native.RESULT_SYNTAX, InvalidSyntaxError),
    (native.RESULT_OVERFLOW, ValueOverflowError),
    (native.RESULT_INVALID_VALUE, InvalidValueError),
    (native.RESULT_UNSUPPORTED, UnsupportedError),
    (native.RESULT_INVALID_SCHEMA, InvalidSchemaError),
    (native.RESULT_NATIVE_SIZE, NativeSizeError),
    (native.RESULT_NEED_MORE_DATA, NeedMoreDataError),
    (native.RESULT_INVALID_STATE, InvalidStateError),
    (native.RESULT_CALLBACK, CallbackError),
    (native.RESULT_TRUNCATED, TruncatedError),
]


def test_every_native_result_constant_has_a_typed_error():
    names = [name for name in dir(native) if name.startswith("RESULT_") and name != "RESULT_OK"]
    assert native.RESULT_OK == 0
    assert sorted(getattr(native, name) for name in names) == sorted(code for code, _ in KNOWN)


def test_every_known_code_maps_to_its_typed_error():
    for code, error_type in KNOWN:
        native_error = native.Error({"code": code})
        error = _from_native(native_error)
        assert isinstance(error, error_type)
        assert isinstance(error, OpenTLVError)
        assert error.code == code
        assert str(error) == native.result_string(code)


def test_result_text_has_only_the_c_name():
    assert not hasattr(native, "strerror")


def test_unknown_code_falls_back_to_the_base_error():
    native_error = native.Error({"code": 999})
    error = _from_native(native_error)
    assert type(error) is OpenTLVError
    assert error.code == 999


def test_missing_keys_default_to_none():
    native_error = native.Error({"code": 1})
    error = _from_native(native_error)
    assert error.offset is None
    assert error.expected is None
    assert error.actual is None
    assert error.operation is None
    assert error.tag is None
    assert error.length is None
    assert error.required is None
    assert error.available is None


def test_reader_diagnostic_fields_are_carried_through():
    native_error = native.Error({
        "code": 1,
        "offset": 4,
        "expected": "at least 2 bytes",
        "actual": "0 bytes",
        "operation": "value",
        "tag": b"\x9f\x02",
    })
    error = _from_native(native_error)
    assert error.offset == 4
    assert error.expected == "at least 2 bytes"
    assert error.actual == "0 bytes"
    assert error.operation == "value"
    assert error.tag == b"\x9f\x02"


def test_writer_diagnostic_fields_are_carried_through():
    native_error = native.Error({
        "code": 1,
        "operation": "value",
        "length": 10,
        "required": 12,
        "available": 8,
    })
    error = _from_native(native_error)
    assert error.length == 10
    assert error.required == 12
    assert error.available == 8
