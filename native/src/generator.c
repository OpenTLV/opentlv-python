// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#define PY_SSIZE_T_CLEAN
#include "generator.h"
#include "format.h"
#include "reader.h"
#include <tlv/generator.h>
#include <stdlib.h>

/* Adapts the options record; the candidate table borrows the record's tag
 * bytes and is released by the caller with free(). Core validates limits. */
static int parse_options(PyObject* record, tlv_generator_options_t* options) {
    unsigned long long seed, case_index;
    Py_ssize_t         elements, depth, value_size, case_size;
    PyObject*          candidates;
    if (!PyTuple_Check(record)) {
        PyErr_SetString(PyExc_TypeError, "generator options tuple required");
        return -1;
    }
    if (!PyArg_ParseTuple(record, "KKnnnnO!", &seed, &case_index, &elements, &depth, &value_size,
                          &case_size, &PyTuple_Type, &candidates))
        return -1;
    if (elements < 0 || depth < 0 || value_size < 0 || case_size < 0) {
        PyErr_SetString(PyExc_ValueError, "generator limits must not be negative");
        return -1;
    }
    size_t count = (size_t)PyTuple_Size(candidates);
    if (count > SIZE_MAX / sizeof(tlv_generator_candidate_t)) {
        opentlv_python_raise_result(TLV_ERR_OVERFLOW);
        return -1;
    }
    tlv_generator_candidate_t* table = count ? calloc(count, sizeof(*table)) : NULL;
    if (count && !table) {
        PyErr_NoMemory();
        return -1;
    }
    for (size_t i = 0; i < count; ++i) {
        PyObject*  candidate = PyTuple_GetItem(candidates, (Py_ssize_t)i);
        PyObject*  bytes;
        char*      tag;
        Py_ssize_t tag_size, minimum, maximum;
        if (!PyTuple_Check(candidate)) {
            PyErr_SetString(PyExc_TypeError, "invalid generator candidate record");
            free(table);
            return -1;
        }
        if (!PyArg_ParseTuple(candidate, "O!nn", &PyBytes_Type, &bytes, &minimum, &maximum) ||
            PyBytes_AsStringAndSize(bytes, &tag, &tag_size) < 0) {
            free(table);
            return -1;
        }
        if (minimum < 0 || maximum < 0) {
            PyErr_SetString(PyExc_ValueError, "candidate Value sizes must not be negative");
            free(table);
            return -1;
        }
        /* `{NULL, 0}` is the canonical empty Tag. */
        table[i].tag = tlv_tag(tag_size ? (const uint8_t*)tag : NULL, (size_t)tag_size);
        table[i].min_value_size = (size_t)minimum;
        table[i].max_value_size = (size_t)maximum;
    }
    options->seed = seed;
    options->case_index = case_index;
    options->max_elements = (size_t)elements;
    options->max_depth = (size_t)depth;
    options->max_value_size = (size_t)value_size;
    options->max_case_size = (size_t)case_size;
    options->candidates = table;
    options->candidate_count = count;
    return 0;
}

PyObject* opentlv_python_generator_workspace_size(PyObject* module, PyObject* record) {
    (void)module;
    tlv_generator_options_t options;
    if (parse_options(record, &options) < 0) return NULL;
    size_t       size = 0;
    tlv_result_t code = tlv_generator_workspace_size(&options, &size);
    free((void*)options.candidates);
    if (code != TLV_OK) {
        opentlv_python_raise_result(code);
        return NULL;
    }
    return PyLong_FromSize_t(size);
}

/* Workspace is owned per call and never exposed. An owned output of
 * max_case_size bytes shares its allocation, after the workspace. */
PyObject* opentlv_python_generate(PyObject* module, PyObject* args) {
    (void)module;
    PyObject *specification, *record, *destination;
    if (!PyArg_ParseTuple(args, "OOO", &specification, &record, &destination)) return NULL;
    tlv_generator_options_t options;
    if (parse_options(record, &options) < 0) return NULL;
    PyObject*           owner = NULL;
    PyObject*           result = NULL;
    Py_buffer           output;
    int                 borrowed = 0;
    uint8_t *           storage = NULL, *data;
    size_t              workspace = 0, capacity = options.max_case_size, written = 0;
    tlv_result_t        code;
    const tlv_format_t* format = opentlv_python_format_resolve(specification, &owner);
    if (!format) goto done;
    if (destination != Py_None) {
        if (PyObject_GetBuffer(destination, &output, PyBUF_WRITABLE) < 0) goto done;
        borrowed = 1;
        capacity = (size_t)output.len;
    }
    /* Capabilities precede configuration, matching tlv_generate(). */
    code = tlv_format_can_read(format) && tlv_format_can_write(format)
               ? tlv_generator_workspace_size(&options, &workspace)
               : TLV_ERR_UNSUPPORTED;
    if (code == TLV_OK && !borrowed && capacity > PY_SSIZE_T_MAX) code = TLV_ERR_NATIVE_SIZE;
    if (code == TLV_OK && !borrowed && capacity > SIZE_MAX - workspace) code = TLV_ERR_OVERFLOW;
    if (code != TLV_OK) {
        opentlv_python_raise_result(code);
        goto done;
    }
    storage = PyMem_Malloc(borrowed ? workspace : workspace + capacity);
    if (!storage) {
        PyErr_NoMemory();
        goto done;
    }
    data = borrowed ? (uint8_t*)output.buf : storage + workspace;
    code = tlv_generate(format, &options, data, capacity, storage, workspace, &written);
    if (code != TLV_OK)
        opentlv_python_raise_result(code);
    else if (borrowed)
        result = PyLong_FromSize_t(written);
    else
        result = PyBytes_FromStringAndSize((const char*)data, (Py_ssize_t)written);
done:
    PyMem_Free(storage);
    if (borrowed) PyBuffer_Release(&output);
    Py_XDECREF(owner);
    free((void*)options.candidates);
    return result;
}

int opentlv_python_register_generator(PyObject* module) {
    return PyModule_AddIntConstant(module, "GENERATOR_VERSION", TLV_GENERATOR_VERSION);
}
