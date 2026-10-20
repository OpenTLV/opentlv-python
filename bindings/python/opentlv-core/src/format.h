// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#ifndef OPENTLV_PYTHON_FORMAT_H
#define OPENTLV_PYTHON_FORMAT_H

#include <Python.h>
#include <tlv/config.h>
#include <tlv/format.h>

/* Stable IDs shared with opentlv.Format; unavailable IDs return NULL. */
const tlv_format_t* opentlv_python_format_for(int format_id);
/* Owned builtin/fixed descriptor; context storage is retained by the capsule. */
PyObject*           opentlv_python_format_owner(PyObject* specification);
const tlv_format_t* opentlv_python_format_pointer(PyObject* owner);
/* Adds availability flags to the module; returns -1 on a Python error. */
int opentlv_python_register_formats(PyObject* module);

#if OPENTLV_FORMAT_BER
const tlv_format_t* opentlv_python_format_ber(void);
#endif

#if OPENTLV_FORMAT_CER
const tlv_format_t* opentlv_python_format_cer(void);
#endif

#if OPENTLV_FORMAT_DER
const tlv_format_t* opentlv_python_format_der(void);
#endif

#if OPENTLV_EMV
const tlv_format_t* opentlv_python_format_emv(void);
#endif

#if OPENTLV_NFC
const tlv_format_t* opentlv_python_format_nfc_type2(void);
#endif

#if OPENTLV_LLDP
const tlv_format_t* opentlv_python_format_lldp(void);
#endif

#endif
