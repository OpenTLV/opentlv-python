// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#include "codec.h"
#include "format.h"
#include "reader.h"
#include "schema.h"
#include <tlv/codec/ipv4.h>
#include <tlv/codec/structure.h>
#include <tlv/codec/values.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>

enum { CODEC_DECODE, CODEC_ENCODE, CODEC_MEASURE, CODEC_ENCODE_INTO };

/* C representation of one value; spans borrow the Python buffer or input. */
typedef union codec_object {
    uint8_t         u8;
    uint16_t        u16;
    uint32_t        u32;
    uint64_t        u64;
    int64_t         i64;
    tlv_value_t     span;
    tlv_ipv4_t      address;
    tlv_ipv4_list_t list;
} codec_object;

int opentlv_python_codec_init(opentlv_python_codec* self, PyObject* specification) {
    int        kind, parameter;
    Py_ssize_t width;
    PyObject*  digits_obj;
    memset(self, 0, sizeof *self);
    if (!PyTuple_Check(specification) ||
        !PyArg_ParseTuple(specification, "iinO", &kind, &parameter, &width, &digits_obj)) {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_TypeError, "codec specification required");
        return 0;
    }
    if (width < 0) {
        PyErr_SetString(PyExc_ValueError, "negative codec width");
        return 0;
    }
    unsigned long digits = PyLong_AsUnsignedLong(digits_obj);
    if (PyErr_Occurred()) return 0;
    if (digits > UINT_MAX) {
        PyErr_SetString(PyExc_OverflowError, "digits exceed unsigned int");
        return 0;
    }
    self->kind = kind;
    self->codec = &self->configured;
    /* Configured descriptors spell out what tlv_*_codec() would build. */
    switch (kind) {
        case OPENTLV_PYTHON_CODEC_NUMBER:
            self->config.number = (tlv_number_codec_config_t){(tlv_number_encoding_t)parameter,
                                                              (size_t)width, (unsigned int)digits};
            self->configured =
                (tlv_codec_t){&self->config.number, tlv_number_decode, tlv_number_encode};
            return 1;
        case OPENTLV_PYTHON_CODEC_TEXT:
            self->config.text = (tlv_text_codec_config_t){(tlv_text_alphabet_t)parameter,
                                                          (size_t)width, (int)digits};
            self->configured = (tlv_codec_t){&self->config.text, tlv_text_decode, tlv_text_encode};
            return 1;
        case OPENTLV_PYTHON_CODEC_DIGITS:
            self->config.digits = (tlv_digits_codec_config_t){(size_t)width};
            self->configured =
                (tlv_codec_t){&self->config.digits, tlv_digits_decode, tlv_digits_encode};
            return 1;
        case OPENTLV_PYTHON_CODEC_UINT8: self->codec = &tlv_codec_uint8; return 1;
        case OPENTLV_PYTHON_CODEC_UINT16_BE: self->codec = &tlv_codec_uint16_be; return 1;
        case OPENTLV_PYTHON_CODEC_UINT16_LE: self->codec = &tlv_codec_uint16_le; return 1;
        case OPENTLV_PYTHON_CODEC_UINT32_BE: self->codec = &tlv_codec_uint32_be; return 1;
        case OPENTLV_PYTHON_CODEC_UINT32_LE: self->codec = &tlv_codec_uint32_le; return 1;
        case OPENTLV_PYTHON_CODEC_INT64_MINIMAL_BE:
            self->codec = &tlv_codec_int64_minimal_be;
            return 1;
        case OPENTLV_PYTHON_CODEC_BYTES: self->codec = &tlv_codec_bytes; return 1;
        case OPENTLV_PYTHON_CODEC_IPV4: self->codec = &tlv_codec_ipv4; return 1;
        case OPENTLV_PYTHON_CODEC_IPV4_LIST: self->codec = &tlv_codec_ipv4_list; return 1;
        default: PyErr_SetString(PyExc_ValueError, "unknown codec kind"); return 0;
    }
}

/* Decodes into the codec's own representation, then widens it to the
 * uint64_t that TLV_QUERY_CODEC_UNSIGNED reads from scratch. */
static tlv_result_t widened_decode(const void* context, const uint8_t* data, size_t size,
                                   void* value, size_t capacity,
                                   tlv_codec_diagnostic_t* diagnostic) {
    const opentlv_python_codec* self = context;
    codec_object                object;
    tlv_result_t                code =
        self->codec->decode(self->codec->context, data, size, &object, sizeof object, diagnostic);
    if (code != TLV_OK) return code;
    if (capacity < sizeof(uint64_t))
        return tlv_codec_diagnostic_result(diagnostic, TLV_ERR_BUFFER_TOO_SHORT);
    uint64_t wide = self->kind == OPENTLV_PYTHON_CODEC_UINT8 ? object.u8
                    : self->kind == OPENTLV_PYTHON_CODEC_UINT16_BE ||
                            self->kind == OPENTLV_PYTHON_CODEC_UINT16_LE
                        ? object.u16
                        : object.u32;
    memcpy(value, &wide, sizeof wide);
    return TLV_OK;
}

int opentlv_python_codec_query(opentlv_python_codec* self, tlv_query_codec_adapter_t* adapter,
                               size_t* scratch_size) {
    *scratch_size = sizeof(uint64_t);
    switch (self->kind) {
        case OPENTLV_PYTHON_CODEC_NUMBER:
            *adapter = (tlv_query_codec_adapter_t){self->codec, TLV_QUERY_CODEC_UNSIGNED};
            return 1;
        case OPENTLV_PYTHON_CODEC_UINT8:
        case OPENTLV_PYTHON_CODEC_UINT16_BE:
        case OPENTLV_PYTHON_CODEC_UINT16_LE:
        case OPENTLV_PYTHON_CODEC_UINT32_BE:
        case OPENTLV_PYTHON_CODEC_UINT32_LE:
            self->widened = (tlv_codec_t){self, widened_decode, NULL};
            *adapter = (tlv_query_codec_adapter_t){&self->widened, TLV_QUERY_CODEC_UNSIGNED};
            return 1;
        case OPENTLV_PYTHON_CODEC_INT64_MINIMAL_BE:
            *adapter = (tlv_query_codec_adapter_t){self->codec, TLV_QUERY_CODEC_SIGNED};
            return 1;
        case OPENTLV_PYTHON_CODEC_BYTES:
        case OPENTLV_PYTHON_CODEC_TEXT:
            *adapter = (tlv_query_codec_adapter_t){self->codec, TLV_QUERY_CODEC_UTF8};
            *scratch_size = sizeof(tlv_value_t);
            return 1;
        default:
            PyErr_SetString(PyExc_TypeError, "Query cannot adapt this codec representation");
            return 0;
    }
}

static int fits(uint64_t value, uint64_t maximum, const char* type) {
    if (value <= maximum) return 1;
    PyErr_Format(PyExc_OverflowError, "value exceeds %s", type);
    return 0;
}

/* Adapts a Python value to the codec's C representation. Buffer kinds borrow
 * *buffer, which the caller releases when buffer->obj is set. */
static int encode_object(const opentlv_python_codec* self, PyObject* value, codec_object* object,
                         Py_buffer* buffer, const void** pointer, size_t* size) {
    *pointer = object;
    switch (self->kind) {
        case OPENTLV_PYTHON_CODEC_NUMBER:
        case OPENTLV_PYTHON_CODEC_UINT8:
        case OPENTLV_PYTHON_CODEC_UINT16_BE:
        case OPENTLV_PYTHON_CODEC_UINT16_LE:
        case OPENTLV_PYTHON_CODEC_UINT32_BE:
        case OPENTLV_PYTHON_CODEC_UINT32_LE: {
            unsigned long long number = PyLong_AsUnsignedLongLong(value);
            if (PyErr_Occurred()) return 0;
            switch (self->kind) {
                case OPENTLV_PYTHON_CODEC_UINT8:
                    object->u8 = (uint8_t)number;
                    *size = sizeof object->u8;
                    return fits(number, UINT8_MAX, "uint8");
                case OPENTLV_PYTHON_CODEC_UINT16_BE:
                case OPENTLV_PYTHON_CODEC_UINT16_LE:
                    object->u16 = (uint16_t)number;
                    *size = sizeof object->u16;
                    return fits(number, UINT16_MAX, "uint16");
                case OPENTLV_PYTHON_CODEC_UINT32_BE:
                case OPENTLV_PYTHON_CODEC_UINT32_LE:
                    object->u32 = (uint32_t)number;
                    *size = sizeof object->u32;
                    return fits(number, UINT32_MAX, "uint32");
                default:
                    object->u64 = (uint64_t)number;
                    *size = sizeof object->u64;
                    return 1;
            }
        }
        case OPENTLV_PYTHON_CODEC_INT64_MINIMAL_BE:
            object->i64 = (int64_t)PyLong_AsLongLong(value);
            *size = sizeof object->i64;
            return !PyErr_Occurred();
        default: break;
    }
    if (PyObject_GetBuffer(value, buffer, PyBUF_SIMPLE) < 0) return 0;
    const uint8_t* data = buffer->buf;
    size_t         length = (size_t)buffer->len;
    switch (self->kind) {
        case OPENTLV_PYTHON_CODEC_DIGITS:
            /* Digit strings are character arrays, required even when empty. */
            *pointer = length ? (const void*)data : (const void*)"";
            *size = length;
            return 1;
        case OPENTLV_PYTHON_CODEC_IPV4:
            if (length != sizeof object->address.bytes) {
                PyErr_SetString(PyExc_ValueError, "IPv4 address requires four bytes");
                return 0;
            }
            memcpy(object->address.bytes, data, length);
            *size = sizeof object->address;
            return 1;
        case OPENTLV_PYTHON_CODEC_IPV4_LIST:
            object->list.raw = (tlv_value_t){data, length};
            *size = sizeof object->list;
            return 1;
        default:
            object->span = (tlv_value_t){data, length};
            *size = sizeof object->span;
            return 1;
    }
}

static PyObject* address_bytes(const tlv_ipv4_t* address) {
    return PyBytes_FromStringAndSize((const char*)address->bytes, sizeof address->bytes);
}

/* Owned Python value for a decoded representation; IPv4 lists are tuples of
 * four-byte addresses copied through tlv_ipv4_list_at(). */
static PyObject* decoded_value(const opentlv_python_codec* self, const codec_object* object) {
    switch (self->kind) {
        case OPENTLV_PYTHON_CODEC_NUMBER: return PyLong_FromUnsignedLongLong(object->u64);
        case OPENTLV_PYTHON_CODEC_UINT8: return PyLong_FromUnsignedLong(object->u8);
        case OPENTLV_PYTHON_CODEC_UINT16_BE:
        case OPENTLV_PYTHON_CODEC_UINT16_LE: return PyLong_FromUnsignedLong(object->u16);
        case OPENTLV_PYTHON_CODEC_UINT32_BE:
        case OPENTLV_PYTHON_CODEC_UINT32_LE: return PyLong_FromUnsignedLong(object->u32);
        case OPENTLV_PYTHON_CODEC_INT64_MINIMAL_BE: return PyLong_FromLongLong(object->i64);
        case OPENTLV_PYTHON_CODEC_TEXT:
            /* C validated the ASCII repertoire. */
            return PyUnicode_FromStringAndSize((const char*)object->span.data,
                                               (Py_ssize_t)object->span.size);
        case OPENTLV_PYTHON_CODEC_IPV4: return address_bytes(&object->address);
        case OPENTLV_PYTHON_CODEC_IPV4_LIST: {
            size_t    count = (size_t)object->list.raw.size / sizeof(tlv_ipv4_t);
            PyObject* result = PyTuple_New((Py_ssize_t)count);
            for (size_t i = 0; result && i < count; ++i) {
                tlv_ipv4_t   address;
                tlv_result_t code = tlv_ipv4_list_at(&object->list, i, &address);
                PyObject*    item = code == TLV_OK ? address_bytes(&address) : NULL;
                if (code != TLV_OK) opentlv_python_raise_result(code);
                if (!item)
                    Py_CLEAR(result);
                else
                    PyTuple_SetItem(result, (Py_ssize_t)i, item);
            }
            return result;
        }
        default:
            return PyBytes_FromStringAndSize((const char*)object->span.data,
                                             (Py_ssize_t)object->span.size);
    }
}

static PyObject* codec_decode(const opentlv_python_codec* self, PyObject* input) {
    Py_buffer data;
    if (PyObject_GetBuffer(input, &data, PyBUF_SIMPLE) < 0) return NULL;
    tlv_codec_diagnostic_t diagnostic;
    tlv_result_t           code;
    PyObject*              result = NULL;
    if (self->kind == OPENTLV_PYTHON_CODEC_DIGITS) {
        /* Two digits per byte and the terminating NUL. */
        size_t size = (size_t)data.len;
        if (size > (SIZE_MAX - 1) / 2) {
            PyBuffer_Release(&data);
            opentlv_python_raise_result(TLV_ERR_OVERFLOW);
            return NULL;
        }
        char* digits = malloc(size * 2 + 1);
        if (!digits) {
            PyBuffer_Release(&data);
            return PyErr_NoMemory();
        }
        code = tlv_codec_decode(self->codec, data.buf, size, digits, size * 2 + 1, &diagnostic);
        if (code == TLV_OK) result = PyUnicode_FromString(digits);
        free(digits);
    } else {
        codec_object object;
        code = tlv_codec_decode(self->codec, data.buf, (size_t)data.len, &object, sizeof object,
                                &diagnostic);
        /* Spans borrow the input, so copy them before releasing it. */
        if (code == TLV_OK) result = decoded_value(self, &object);
    }
    PyBuffer_Release(&data);
    if (code != TLV_OK) opentlv_python_raise_codec(code, &diagnostic);
    return result;
}

static int overlaps(const Py_buffer* first, const Py_buffer* second) {
    uintptr_t a = (uintptr_t)first->buf, b = (uintptr_t)second->buf;
    return first->len && second->len && a < b + (uintptr_t)second->len &&
           b < a + (uintptr_t)first->len;
}

static PyObject* codec_encode(const opentlv_python_codec* self, int operation, PyObject* value,
                              PyObject* output) {
    codec_object object;
    Py_buffer    input = {0}, destination = {0};
    const void*  pointer;
    size_t       size, written = 0;
    PyObject*    result = NULL;
    if (operation != CODEC_ENCODE && operation != CODEC_MEASURE && operation != CODEC_ENCODE_INTO) {
        PyErr_SetString(PyExc_ValueError, "unknown codec operation");
        return NULL;
    }
    if (!encode_object(self, value, &object, &input, &pointer, &size)) goto done;
    tlv_codec_diagnostic_t diagnostic;
    tlv_result_t           code;
    if (operation == CODEC_ENCODE_INTO) {
        if (PyObject_GetBuffer(output, &destination, PyBUF_WRITABLE) < 0) goto done;
        if (input.obj && overlaps(&input, &destination)) {
            PyErr_SetString(PyExc_ValueError, "codec input and output must not overlap");
            goto done;
        }
        code = tlv_codec_encode(self->codec, pointer, size, destination.buf,
                                (size_t)destination.len, &written, &diagnostic);
        if (code == TLV_OK) result = PyLong_FromSize_t(written);
    } else {
        code = tlv_codec_encode(self->codec, pointer, size, NULL, 0, &written, &diagnostic);
        if (code == TLV_OK && operation == CODEC_MEASURE) result = PyLong_FromSize_t(written);
        if (code == TLV_OK && operation == CODEC_ENCODE) {
            uint8_t* bytes = malloc(written ? written : 1);
            if (!bytes) {
                PyErr_NoMemory();
                goto done;
            }
            code =
                tlv_codec_encode(self->codec, pointer, size, bytes, written, &written, &diagnostic);
            if (code == TLV_OK)
                result = PyBytes_FromStringAndSize((const char*)bytes, (Py_ssize_t)written);
            free(bytes);
        }
    }
    if (code != TLV_OK) opentlv_python_raise_codec(code, &diagnostic);
done:
    if (input.obj) PyBuffer_Release(&input);
    if (destination.obj) PyBuffer_Release(&destination);
    return result;
}

PyObject* opentlv_python_value_codec(PyObject* module, PyObject* args) {
    (void)module;
    int                  operation;
    PyObject *           specification, *value, *output = Py_None;
    opentlv_python_codec codec;
    if (!PyArg_ParseTuple(args, "iOO|O", &operation, &specification, &value, &output) ||
        !opentlv_python_codec_init(&codec, specification))
        return NULL;
    return operation == CODEC_DECODE ? codec_decode(&codec, value)
                                     : codec_encode(&codec, operation, value, output);
}

/* Python callbacks for one structure codec call. The encode callback runs
 * once; its bytes are reused for the size query and the validated write. */
typedef struct structure_call {
    PyObject*  decode;
    PyObject*  encode;
    Py_buffer* produced;
} structure_call;

static tlv_result_t structure_decode(const void* context, const tlv_format_t* format,
                                     const uint8_t* data, size_t size, void* value, size_t capacity,
                                     tlv_codec_diagnostic_t* diagnostic) {
    (void)format;
    const structure_call* call = context;
    if (capacity < sizeof(PyObject*))
        return tlv_codec_diagnostic_result(diagnostic, TLV_ERR_BUFFER_TOO_SHORT);
    PyObject* input = PyBytes_FromStringAndSize((const char*)data, (Py_ssize_t)size);
    PyObject* object = input ? PyObject_CallFunctionObjArgs(call->decode, input, NULL) : NULL;
    Py_XDECREF(input);
    /* The pending Python exception replaces this status. */
    if (!object) return tlv_codec_diagnostic_result(diagnostic, TLV_ERR_CALLBACK);
    memcpy(value, &object, sizeof object);
    return tlv_codec_diagnostic_result(diagnostic, TLV_OK);
}

static tlv_result_t structure_encode(const void* context, const tlv_format_t* format,
                                     const void* value, size_t size, uint8_t* data, size_t capacity,
                                     size_t* written, tlv_codec_diagnostic_t* diagnostic) {
    (void)format;
    const structure_call* call = context;
    if (size != sizeof(PyObject*))
        return tlv_codec_diagnostic_reason(diagnostic, TLV_ERR_INVALID_VALUE,
                                           TLV_CODEC_REASON_OBJECT);
    if (!call->produced->obj) {
        PyObject* object;
        memcpy(&object, value, sizeof object);
        PyObject* sequence = PyObject_CallFunctionObjArgs(call->encode, object, NULL);
        int status = sequence ? PyObject_GetBuffer(sequence, call->produced, PyBUF_SIMPLE) : -1;
        Py_XDECREF(sequence);
        if (status < 0) return tlv_codec_diagnostic_result(diagnostic, TLV_ERR_CALLBACK);
    }
    size_t count = (size_t)call->produced->len;
    if (data) {
        if (count > capacity)
            return tlv_codec_diagnostic_result(diagnostic, TLV_ERR_BUFFER_TOO_SHORT);
        if (count) memcpy(data, call->produced->buf, count);
    }
    *written = count;
    return tlv_codec_diagnostic_result(diagnostic, TLV_OK);
}

/* Measures through the callback, then writes and validates into temporary
 * storage, so caller output changes only after a validated success. */
static tlv_result_t structure_write(const tlv_structure_codec_t* codec, PyObject** value,
                                    int operation, PyObject* output, PyObject** result,
                                    tlv_codec_diagnostic_t* diagnostic) {
    size_t       size;
    tlv_result_t code =
        tlv_structure_encode(codec, value, sizeof *value, NULL, 0, &size, diagnostic);
    if (code != TLV_OK) return code;
    Py_buffer destination = {0};
    if (operation == CODEC_ENCODE_INTO) {
        if (PyObject_GetBuffer(output, &destination, PyBUF_WRITABLE) < 0) return TLV_ERR_CALLBACK;
        if (size > (size_t)destination.len) {
            /* The callback reports the short destination without writing. */
            code = tlv_structure_encode(codec, value, sizeof *value, destination.buf,
                                        (size_t)destination.len, &size, diagnostic);
            PyBuffer_Release(&destination);
            return code == TLV_OK ? TLV_ERR_CALLBACK : code;
        }
    }
    uint8_t* bytes = malloc(size ? size : 1);
    if (!bytes) {
        if (destination.obj) PyBuffer_Release(&destination);
        PyErr_NoMemory();
        return TLV_ERR_OUT_OF_MEMORY;
    }
    code = tlv_structure_encode(codec, value, sizeof *value, bytes, size, &size, diagnostic);
    if (code == TLV_OK) {
        if (operation == CODEC_ENCODE)
            *result = PyBytes_FromStringAndSize((const char*)bytes, (Py_ssize_t)size);
        else {
            if (operation == CODEC_ENCODE_INTO && size) memcpy(destination.buf, bytes, size);
            *result = PyLong_FromSize_t(size);
        }
    }
    free(bytes);
    if (destination.obj) PyBuffer_Release(&destination);
    return code;
}

PyObject* opentlv_python_structure_codec(PyObject* module, PyObject* args) {
    (void)module;
    int        operation;
    PyObject * value, *format_spec, *schema_obj, *decode, *encode, *output = Py_None;
    Py_ssize_t max_depth, max_elements;
    if (!PyArg_ParseTuple(args, "iOOOnnOO|O", &operation, &value, &format_spec, &schema_obj,
                          &max_depth, &max_elements, &decode, &encode, &output))
        return NULL;
    if (operation < CODEC_DECODE || operation > CODEC_ENCODE_INTO) {
        PyErr_SetString(PyExc_ValueError, "unknown codec operation");
        return NULL;
    }
    if (max_depth < 0 || max_elements < 0) {
        PyErr_SetString(PyExc_ValueError, "max_depth and max_elements must not be negative");
        return NULL;
    }
    PyObject*           format_owner;
    const tlv_format_t* format = opentlv_python_format_resolve(format_spec, &format_owner);
    if (!format) return NULL;
    tlv_structure_schema_t*       owned = NULL;
    const tlv_structure_schema_t* schema =
        schema_obj == Py_None ? NULL : opentlv_python_schema_acquire(schema_obj, &owned);
    PyObject* result = NULL;
    if (schema_obj != Py_None && !schema) goto done;
    Py_buffer              produced = {0};
    structure_call         call = {decode, encode, &produced};
    tlv_structure_codec_t  codec = {&call,
                                    format,
                                    schema,
                                    (size_t)max_depth,
                                    (size_t)max_elements,
                                    decode == Py_None ? NULL : structure_decode,
                                    encode == Py_None ? NULL : structure_encode};
    tlv_codec_diagnostic_t diagnostic;
    tlv_result_t           code;
    if (operation == CODEC_DECODE) {
        Py_buffer data;
        PyObject* object = NULL;
        if (PyObject_GetBuffer(value, &data, PyBUF_SIMPLE) < 0) goto done;
        code = tlv_structure_decode(&codec, data.buf, (size_t)data.len, &object, sizeof object,
                                    &diagnostic);
        PyBuffer_Release(&data);
        if (code == TLV_OK) result = object;
    } else
        code = structure_write(&codec, &value, operation, output, &result, &diagnostic);
    if (produced.obj) PyBuffer_Release(&produced);
    /* Raise before releasing the rule tree that diagnostic evidence may borrow. */
    if (code != TLV_OK && !PyErr_Occurred()) opentlv_python_raise_codec(code, &diagnostic);
done:
    opentlv_python_schema_release(owned);
    Py_XDECREF(format_owner);
    return result;
}
