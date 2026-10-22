// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#define PY_SSIZE_T_CLEAN
#include "format.h"
#include "reader.h"
#include <tlv/formats/fixed.h>
#include <tlv/size.h>
#include <stdlib.h>

#define FORMAT_CAPSULE "opentlv.FormatOwner"
typedef struct format_owner {
    tlv_format_t         format;
    tlv_fixed_format_t   fixed;
    struct format_owner* next;
    size_t               users;
    int                  configured;
} format_owner;
/* Accessed with the GIL. Equivalent Fixed descriptors share their immutable
 * context, preserving the native Query Format-identity contract. */
static format_owner* owners;
static void          destroy_format(PyObject* capsule) {
    format_owner* value = PyCapsule_GetPointer(capsule, FORMAT_CAPSULE);
    if (!value || --value->users) return;
    format_owner** link = &owners;
    while (*link != value) link = &(*link)->next;
    *link = value->next;
    free(value);
}
const tlv_format_t* opentlv_python_format_pointer(PyObject* owner) {
    if (opentlv_python_format_is_composed(owner)) return opentlv_python_composed_pointer(owner);
    format_owner* value = PyCapsule_GetPointer(owner, FORMAT_CAPSULE);
    return value ? &value->format : NULL;
}
const tlv_format_t* opentlv_python_format_resolve(PyObject* specification, PyObject** owner) {
    *owner = opentlv_python_format_owner(specification);
    return *owner ? opentlv_python_format_pointer(*owner) : NULL;
}
PyObject* opentlv_python_format_owner(PyObject* specification) {
    if (opentlv_python_format_is_composed(specification)) return Py_NewRef(specification);
    format_owner* value = calloc(1, sizeof *value);
    if (!value) return PyErr_NoMemory();
    if (PyTuple_Check(specification)) {
        value->configured = 1;
        Py_ssize_t tag, length;
        int        big;
        if (!PyArg_ParseTuple(specification, "nnp", &tag, &length, &big)) {
            free(value);
            return NULL;
        }
        if (tag < 1 || length < 1 || length > 8) {
            free(value);
            PyErr_SetString(PyExc_ValueError, "invalid FixedFormat widths");
            return NULL;
        }
        value->fixed.identifier.size = (size_t)tag;
        value->fixed.length.size = (size_t)length;
        value->fixed.length.byte_order =
            big ? TLV_BYTE_ORDER_BIG_ENDIAN : TLV_BYTE_ORDER_LITTLE_ENDIAN;
        value->fixed.element_order = TLV_ELEMENT_ORDER_TLV;
        value->fixed.length_scope = TLV_LENGTH_SCOPE_VALUE;
        if (tlv_fixed_format_init(&value->format, &value->fixed) != TLV_OK) {
            free(value);
            PyErr_SetString(PyExc_ValueError, "invalid FixedFormat");
            return NULL;
        }
    } else {
        long                id = PyLong_AsLong(specification);
        const tlv_format_t* format = PyErr_Occurred() ? NULL : opentlv_python_format_for((int)id);
        if (!format) {
            free(value);
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "unknown format");
            return NULL;
        }
        value->format = *format;
    }
    for (format_owner* existing = owners; existing; existing = existing->next) {
        if (value->configured && existing->configured &&
            value->fixed.identifier.size == existing->fixed.identifier.size &&
            value->fixed.length.size == existing->fixed.length.size &&
            value->fixed.length.byte_order == existing->fixed.length.byte_order) {
            free(value);
            value = existing;
            break;
        }
    }
    PyObject* capsule = PyCapsule_New(value, FORMAT_CAPSULE, destroy_format);
    if (!capsule) {
        if (!value->users) free(value);
        return NULL;
    }
    if (!value->users) {
        value->next = owners;
        owners = value;
    }
    ++value->users;
    return capsule;
}

const tlv_format_t* opentlv_python_format_for(int format_id) {
    switch (format_id) {
#if OPENTLV_FORMAT_BER
        case 1: return opentlv_python_format_ber();
#endif
#if OPENTLV_FORMAT_CER
        case 2: return opentlv_python_format_cer();
#endif
#if OPENTLV_FORMAT_DER
        case 3: return opentlv_python_format_der();
#endif
#if OPENTLV_LLDP
        case 4: return opentlv_python_format_lldp();
#endif
#if OPENTLV_EMV
        case 5: return opentlv_python_format_emv();
#endif
#if OPENTLV_NFC
        case 6: return opentlv_python_format_nfc_type2();
#endif
        default: return NULL;
    }
}

PyObject* opentlv_python_format_capabilities(PyObject* module, PyObject* specification) {
    (void)module;
    PyObject*           owner;
    const tlv_format_t* format = opentlv_python_format_resolve(specification, &owner);
    if (!format) return NULL;
    PyObject* result = Py_BuildValue("(NN)", PyBool_FromLong(tlv_format_can_read(format)),
                                     PyBool_FromLong(tlv_format_can_write(format)));
    Py_DECREF(owner);
    return result;
}

/* Measures a semantic element; returns the descriptor's owner, or NULL with an
 * exception set. The caller releases the owner and both buffers. */
static PyObject* measure(PyObject* args, Py_buffer* tag, Py_buffer* value, tlv_element_t* element,
                         tlv_encoding_t* encoding, const tlv_format_t** format) {
    PyObject* specification;
    if (!PyArg_ParseTuple(args, "Oy*y*", &specification, tag, value)) return NULL;
    PyObject* owner;
    *format = opentlv_python_format_resolve(specification, &owner);
    if (!*format) {
        PyBuffer_Release(tag);
        PyBuffer_Release(value);
        return NULL;
    }
    *element =
        (tlv_element_t){tlv_tag(tag->buf, (size_t)tag->len), {value->buf, (tlv_size_t)value->len}};
    tlv_format_error_t error;
    tlv_result_t       code = tlv_format_measure(*format, element, encoding, &error);
    if (code != TLV_OK) {
        opentlv_python_raise_format(code, "measure", &error, NULL);
        PyBuffer_Release(tag);
        PyBuffer_Release(value);
        Py_DECREF(owner);
        return NULL;
    }
    return owner;
}

/* format_measure(format, tag, value) -> (header, value, trailer, total) */
PyObject* opentlv_python_format_measure(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer           tag, value;
    tlv_element_t       element;
    tlv_encoding_t      encoding;
    const tlv_format_t* format;
    PyObject*           owner = measure(args, &tag, &value, &element, &encoding, &format);
    if (!owner) return NULL;
    PyBuffer_Release(&tag);
    PyBuffer_Release(&value);
    Py_DECREF(owner);
    return Py_BuildValue("(KKKK)", (unsigned long long)encoding.header,
                         (unsigned long long)encoding.value, (unsigned long long)encoding.trailer,
                         (unsigned long long)encoding.total);
}

/* format_encode(format, tag, value) -> bytes, sized by the measured total. */
PyObject* opentlv_python_format_encode(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer           tag, value;
    tlv_element_t       element;
    tlv_encoding_t      encoding;
    const tlv_format_t* format;
    PyObject*           owner = measure(args, &tag, &value, &element, &encoding, &format);
    if (!owner) return NULL;
    size_t       size = 0;
    PyObject*    result = NULL;
    tlv_result_t code = tlv_size_to_native(encoding.total, &size);
    if (code == TLV_OK && size > PY_SSIZE_T_MAX) code = TLV_ERR_NATIVE_SIZE;
    if (code != TLV_OK)
        opentlv_python_raise_result(code);
    else
        result = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)size);
    if (result) {
        size_t             written = 0;
        tlv_format_error_t error;
        code = tlv_format_encode(format, &element, (uint8_t*)PyBytes_AsString(result), size,
                                 &written, &error);
        if (code != TLV_OK) {
            opentlv_python_raise_format(code, "encode", &error, NULL);
            Py_CLEAR(result);
        }
    }
    PyBuffer_Release(&tag);
    PyBuffer_Release(&value);
    Py_DECREF(owner);
    return result;
}

int opentlv_python_register_formats(PyObject* module) {
    if (PyModule_AddIntConstant(module, "HAS_BER", OPENTLV_FORMAT_BER) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_CER", OPENTLV_FORMAT_CER) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_DER", OPENTLV_FORMAT_DER) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_LLDP", OPENTLV_LLDP) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_EMV", OPENTLV_EMV) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_NFC", OPENTLV_NFC) < 0) return -1;
    return 0;
}
