// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#ifndef OPENTLV_PYTHON_READER_H
#define OPENTLV_PYTHON_READER_H
#include <Python.h>
#include <tlv/reader/reader.h>
#include <tlv/document/document.h>
#include <tlv/query/program.h>
tlv_tree_reader_t*  opentlv_python_query_reader_begin(PyObject*, PyObject**);
void                opentlv_python_query_reader_end(PyObject*);
const tlv_source_t* opentlv_python_source_pointer(PyObject*);
tlv_document_t*     opentlv_python_document_pointer(PyObject*);
void                opentlv_python_raise_query(tlv_result_t, const tlv_query_diagnostic_t*);
PyObject*           opentlv_python_document_wrap(tlv_document_t*, PyObject*);
PyObject*           opentlv_python_builder_create(PyObject*, PyObject*);
PyObject*           opentlv_python_builder_consume(PyObject*, PyObject*);
PyObject*           opentlv_python_source_preserve(PyObject*, PyObject*);
void      opentlv_python_raise_reader(tlv_result_t code, const tlv_reader_diagnostic_t* diagnostic);
void      opentlv_python_raise_result(tlv_result_t code);
PyObject* opentlv_python_cursor_create(PyObject*, PyObject*);
PyObject* opentlv_python_cursor_event(PyObject*, PyObject*);
PyObject* opentlv_python_cursor_next(PyObject*, PyObject*);
PyObject* opentlv_python_cursor_input(PyObject*, PyObject*);
PyObject* opentlv_python_cursor_status(PyObject*, PyObject*);
PyObject* opentlv_python_cursor_skip(PyObject*, PyObject*);
PyObject* opentlv_python_cursor_visit(PyObject*, PyObject*);
PyObject* opentlv_python_query_create(PyObject*, PyObject*);
PyObject* opentlv_python_query_steps(PyObject*, PyObject*);
PyObject* opentlv_python_query_matches(PyObject*, PyObject*);
PyObject* opentlv_python_query_rebind(PyObject*, PyObject*);
PyObject* opentlv_python_query_visit(PyObject*, PyObject*);
#endif
