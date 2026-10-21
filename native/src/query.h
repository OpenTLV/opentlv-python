// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
#ifndef OPENTLV_PYTHON_QUERY_H
#define OPENTLV_PYTHON_QUERY_H
#include <Python.h>
PyObject* opentlv_python_program_create(PyObject*, PyObject*);
PyObject* opentlv_python_query_definition_resolve(PyObject*, PyObject*);
PyObject* opentlv_python_query_emv_resolve(PyObject*, PyObject*);
PyObject* opentlv_python_program_info(PyObject*, PyObject*);
PyObject* opentlv_python_program_render(PyObject*, PyObject*);
PyObject* opentlv_python_execution_create(PyObject*, PyObject*);
PyObject* opentlv_python_execution_size(PyObject*, PyObject*);
PyObject* opentlv_python_execution_feed(PyObject*, PyObject*);
PyObject* opentlv_python_execution_finish(PyObject*, PyObject*);
PyObject* opentlv_python_execution_bind(PyObject*, PyObject*);
PyObject* opentlv_python_execution_visit(PyObject*, PyObject*);
PyObject* opentlv_python_execution_info(PyObject*, PyObject*);
PyObject* opentlv_python_execution_result(PyObject*, PyObject*);
PyObject* opentlv_python_execution_control(PyObject*, PyObject*);
PyObject* opentlv_python_execution_document(PyObject*, PyObject*);
PyObject* opentlv_python_execution_edit(PyObject*, PyObject*);
PyObject* opentlv_python_query_schema(PyObject*, PyObject*);
PyObject* opentlv_python_execution_next(PyObject*, PyObject*);
PyObject* opentlv_python_execution_next_ordinal(PyObject*, PyObject*);
#endif
