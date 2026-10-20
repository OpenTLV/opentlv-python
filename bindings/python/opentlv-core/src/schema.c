// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#include "schema.h"
#include "reader.h"
#include <tlv/schema/schema.h>
#include <stdlib.h>

/* Temporary representation adaptation only; C owns lookup and validation. */
PyObject* opentlv_python_length_schema(PyObject* module, PyObject* args) {
    (void)module;
    PyObject *rules, *tag, *length;
    if (!PyArg_ParseTuple(args, "OOO", &rules, &tag, &length)) return NULL;
    if (!PyTuple_Check(rules) || !PyBytes_Check(tag)) {
        PyErr_SetString(PyExc_TypeError, "tuple of rules and immutable tag bytes required");
        return NULL;
    }
    size_t count = (size_t)PyTuple_Size(rules);
    if (count > SIZE_MAX / sizeof(tlv_schema_entry_t)) {
        opentlv_python_raise_result(TLV_ERR_OVERFLOW);
        return NULL;
    }
    tlv_schema_entry_t* entries = count ? calloc(count, sizeof(*entries)) : NULL;
    if (count && !entries) return PyErr_NoMemory();
    PyObject* result = NULL;
    for (size_t i = 0; i < count; ++i) {
        PyObject* rule = PyTuple_GetItem(rules, (Py_ssize_t)i);
        if (!PyTuple_Check(rule) || PyTuple_Size(rule) != 5 ||
            !PyBytes_Check(PyTuple_GetItem(rule, 0))) {
            PyErr_SetString(PyExc_TypeError, "invalid length rule record");
            goto done;
        }
        PyObject* identifier = PyTuple_GetItem(rule, 0);
        entries[i].tag =
            tlv_tag((const uint8_t*)PyBytes_AsString(identifier), (size_t)PyBytes_Size(identifier));
        entries[i].min_length = PyLong_AsSize_t(PyTuple_GetItem(rule, 1));
        if (PyErr_Occurred()) goto done;
        entries[i].max_length = PyLong_AsSize_t(PyTuple_GetItem(rule, 2));
        if (PyErr_Occurred()) goto done;
        unsigned long flags = PyLong_AsUnsignedLong(PyTuple_GetItem(rule, 3));
        if (PyErr_Occurred()) goto done;
        if (flags > UINT32_MAX) {
            PyErr_SetString(PyExc_OverflowError, "flags exceed uint32");
            goto done;
        }
        entries[i].flags = (uint32_t)flags;
        entries[i].length_multiple = PyLong_AsSize_t(PyTuple_GetItem(rule, 4));
        if (PyErr_Occurred()) goto done;
    }
    tlv_schema_t schema = {entries, count};
    tlv_tag_t    wanted = tlv_tag((const uint8_t*)PyBytes_AsString(tag), (size_t)PyBytes_Size(tag));
    const tlv_schema_entry_t* entry = tlv_schema_find(&schema, &wanted);
    if (length == Py_None) {
        result = entry ? PyLong_FromSize_t((size_t)(entry - entries)) : Py_NewRef(Py_None);
    } else {
        size_t size = PyLong_AsSize_t(length);
        if (PyErr_Occurred()) goto done;
        tlv_result_t code = entry ? tlv_schema_validate_length(entry, size) : TLV_ERR_SCHEMA;
        if (code != TLV_OK)
            opentlv_python_raise_reader(code, NULL);
        else
            result = Py_NewRef(Py_None);
    }
done:
    free(entries);
    return result;
}
