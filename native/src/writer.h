// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#ifndef OPENTLV_PYTHON_WRITER_H
#define OPENTLV_PYTHON_WRITER_H
#include <Python.h>
#include <tlv/writer/writer.h>
void      opentlv_python_raise_writer(tlv_result_t, const tlv_writer_diagnostic_t*);
PyObject* opentlv_python_tree_writer_create(PyObject*, PyObject*);
PyObject* opentlv_python_tree_writer_tags(PyObject*, PyObject*);
PyObject* opentlv_python_tree_writer_event(PyObject*, PyObject*);
PyObject* opentlv_python_tree_writer_action(PyObject*, PyObject*);
PyObject* opentlv_python_tree_writer_measure(PyObject*, PyObject*);
#endif
