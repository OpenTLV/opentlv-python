// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#ifndef OPENTLV_PYTHON_SCHEMA_H
#define OPENTLV_PYTHON_SCHEMA_H
#include <Python.h>
#include <tlv/schema/schema.h>
PyObject* opentlv_python_length_schema(PyObject*, PyObject*);
/* Checks a value constraint, validates a value or looks up its name. */
PyObject* opentlv_python_value_constraint(PyObject*, PyObject*);
/* Borrows a checked schema capsule's rule tree or builds one from a
 * serialized schema into *owned; NULL with a Python error. */
const tlv_structure_schema_t* opentlv_python_schema_acquire(PyObject*                schema,
                                                            tlv_structure_schema_t** owned);
/* Frees a tree from opentlv_python_schema_acquire(); NULL is ignored. */
void opentlv_python_schema_release(tlv_structure_schema_t* schema);
#endif
