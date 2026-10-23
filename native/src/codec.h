// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#ifndef OPENTLV_PYTHON_CODEC_H
#define OPENTLV_PYTHON_CODEC_H

#include <Python.h>
#include <tlv/codec/codec.h>
#include <tlv/codec/digits.h>
#include <tlv/codec/number.h>
#include <tlv/codec/text.h>
#include <tlv/query/adapters.h>
#include <tlv/schema/number.h>

/* Stable kinds shared with opentlv.codec specifications. */
enum opentlv_python_codec_kind {
    OPENTLV_PYTHON_CODEC_NUMBER,
    OPENTLV_PYTHON_CODEC_UINT8,
    OPENTLV_PYTHON_CODEC_UINT16_BE,
    OPENTLV_PYTHON_CODEC_UINT16_LE,
    OPENTLV_PYTHON_CODEC_UINT32_BE,
    OPENTLV_PYTHON_CODEC_UINT32_LE,
    OPENTLV_PYTHON_CODEC_INT64_MINIMAL_BE,
    OPENTLV_PYTHON_CODEC_BYTES,
    OPENTLV_PYTHON_CODEC_TEXT,
    OPENTLV_PYTHON_CODEC_DIGITS,
    OPENTLV_PYTHON_CODEC_IPV4,
    OPENTLV_PYTHON_CODEC_IPV4_LIST,
    OPENTLV_PYTHON_CODEC_SCHEMA_NUMBER
};

/* One Core descriptor and the configuration it borrows. Descriptors point
 * into this storage, so it must not be copied or moved after initialization. */
typedef struct opentlv_python_codec {
    int kind;
    union {
        tlv_number_codec_config_t number;
        tlv_text_codec_config_t   text;
        tlv_digits_codec_config_t digits;
        tlv_schema_number_t       schema_number;
    } config;
    /* Field Schema of a schema number; its Tag borrows the specification. */
    tlv_schema_entry_t entry;
    tlv_codec_t        configured;
    const tlv_codec_t* codec;
    /* uint64 view of a narrower unsigned codec for the Query adapter. */
    tlv_codec_t widened;
} opentlv_python_codec;

/* Raises _opentlv.Error with codec detail. */
void opentlv_python_raise_codec(tlv_result_t code, const tlv_codec_diagnostic_t* diagnostic);
/* Initializes from (kind, encoding or alphabet, width, digits or padding),
 * followed for a schema number by its (tag, min, max, flags, multiple) rule,
 * which must outlive the codec; returns 0 with a Python error. */
int opentlv_python_codec_init(opentlv_python_codec* self, PyObject* specification);
/* Fills a Query adapter borrowing self and its scratch size; returns 0 with
 * a Python error for representations Query cannot adapt. */
int opentlv_python_codec_query(opentlv_python_codec* self, tlv_query_codec_adapter_t* adapter,
                               size_t* scratch_size);
/* value_codec(operation, specification, value, output=None): operation 0
 * decodes, 1 encodes to bytes, 2 measures and 3 encodes into output. */
PyObject* opentlv_python_value_codec(PyObject* module, PyObject* args);
/* structure_codec(operation, value, format, schema, max_depth, max_elements,
 * decode, encode, output=None) with the value_codec operations. */
PyObject* opentlv_python_structure_codec(PyObject* module, PyObject* args);

#endif
