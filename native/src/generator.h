// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#ifndef OPENTLV_PYTHON_GENERATOR_H
#define OPENTLV_PYTHON_GENERATOR_H

#include <Python.h>

/* Options are (seed, case_index, max_elements, max_depth, max_value_size,
 * max_case_size, ((tag bytes, min_value_size, max_value_size), ...)). */
PyObject* opentlv_python_generator_workspace_size(PyObject* module, PyObject* options);
/* generate(format, options, output) -> bytes for output None, else written. */
PyObject* opentlv_python_generate(PyObject* module, PyObject* args);
/* Adds GENERATOR_VERSION to the module; returns -1 on a Python error. */
int opentlv_python_register_generator(PyObject* module);

#endif
