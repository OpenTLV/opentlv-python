// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#include "format.h"
#include <tlv/formats/fixed.h>
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
    format_owner* value = PyCapsule_GetPointer(owner, FORMAT_CAPSULE);
    return value ? &value->format : NULL;
}
PyObject* opentlv_python_format_owner(PyObject* specification) {
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

int opentlv_python_register_formats(PyObject* module) {
    if (PyModule_AddIntConstant(module, "HAS_BER", OPENTLV_FORMAT_BER) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_CER", OPENTLV_FORMAT_CER) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_DER", OPENTLV_FORMAT_DER) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_LLDP", OPENTLV_LLDP) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_EMV", OPENTLV_EMV) < 0) return -1;
    if (PyModule_AddIntConstant(module, "HAS_NFC", OPENTLV_NFC) < 0) return -1;
    return 0;
}
