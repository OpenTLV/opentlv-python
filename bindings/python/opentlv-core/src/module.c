// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

/* Py_LIMITED_API is defined on the command line by the CMake build
 * (Python_add_library(... USE_SABI 3.11 ...)). */
#include <Python.h>

#include <stdlib.h>
#include <limits.h>
#include <string.h>

#include "format.h"
#include "reader.h"
#include "query.h"
#include "location.h"
#include "schema.h"
#include "writer.h"
#include <tlv/config.h>
#if OPENTLV_EMV
#include <tlv/builtins/emv/emv_codec.h>
#endif
#include <tlv/formats/fixed.h>
#include <tlv/codec/codec.h>
#include <tlv/codec/number.h>
#include <tlv/document/document.h>
#include <tlv/result.h>
#include <tlv/definition.h>
#include <tlv/size.h>
#include <tlv/query/query.h>
#include <tlv/reader/reader.h>
#include <tlv/schema/schema.h>
#include <tlv/version.h>
#include <tlv/writer/writer.h>
#include "../../../common/path_query.h"

static PyObject* opentlv_python_error = NULL;

static PyObject* _opentlv_version_string(PyObject* module, PyObject* Py_UNUSED(args)) {
    (void)module;
    return PyUnicode_FromString(tlv_version_string());
}

static PyObject* _opentlv_result_string(PyObject* module, PyObject* args) {
    (void)module;
    int code;
    if (!PyArg_ParseTuple(args, "i", &code)) {
        return NULL;
    }
    return PyUnicode_FromString(tlv_result_string((tlv_result_t)code));
}

/* Sets dict[key] = value, or leaves an exception set and returns -1 if
 * `value` is NULL (an allocation failed) or the dict assignment fails.
 * Always consumes one reference to `value`. */
static int dict_set(PyObject* dict, const char* key, PyObject* value) {
    if (value == NULL) {
        return -1;
    }
    int rc = PyDict_SetItemString(dict, key, value);
    Py_DECREF(value);
    return rc;
}

static int dict_set_str_or_none(PyObject* dict, const char* key, const char* value) {
    return dict_set(dict, key, value != NULL ? PyUnicode_FromString(value) : Py_NewRef(Py_None));
}

static int dict_set_size_or_none(PyObject* dict, const char* key, int has, size_t value) {
    return dict_set(dict, key, has ? PyLong_FromSize_t(value) : Py_NewRef(Py_None));
}

static int dict_set_bytes_or_none(PyObject* dict, const char* key, int has, const uint8_t* data,
                                  size_t size) {
    return dict_set(dict, key,
                    has ? PyBytes_FromStringAndSize((const char*)data, (Py_ssize_t)size)
                        : Py_NewRef(Py_None));
}

static int common_fields(PyObject* result, const tlv_diagnostic_t* common) {
    if (!common) return 0;
    if (dict_set(result, "severity", PyLong_FromLong(common->severity)) < 0) return -1;
    PyObject* path = PyTuple_New(common->has_path ? (Py_ssize_t)common->path.length : 0);
    if (!path) {
        return -1;
    }
    for (size_t i = 0; common->has_path && i < common->path.length; ++i) {
        tlv_tag_t tag = common->path.tags[i];
        PyObject* item = PyBytes_FromStringAndSize((const char*)tag.data, (Py_ssize_t)tag.size);
        if (!item) {
            Py_DECREF(path);
            return -1;
        }
        PyTuple_SetItem(path, (Py_ssize_t)i, item);
    }
    if (dict_set(result, "path", path) < 0 ||
        dict_set(result, "has_path", PyBool_FromLong(common->has_path)) < 0 ||
        dict_set(result, "path_omitted", PyLong_FromSize_t(common->path.omitted)) < 0 ||
        dict_set_str_or_none(result, "expected", common->expected) < 0 ||
        dict_set_str_or_none(result, "actual", common->actual) < 0) {
        return -1;
    }
    PyObject* contexts = PyList_New(0);
    if (!contexts) {
        return -1;
    }
    for (const tlv_diagnostic_context_t* context = common->contexts; context;
         context = context->next) {
        PyObject* item = Py_BuildValue("{s:z,s:z,s:z}", "layer", context->layer, "key",
                                       context->key, "value", context->value);
        if (!item || PyList_Append(contexts, item) < 0) {
            Py_XDECREF(item);
            Py_DECREF(contexts);
            return -1;
        }
        Py_DECREF(item);
    }
    if (dict_set(result, "contexts", contexts) < 0) {
        return -1;
    }
    return 0;
}

/* Raises _opentlv.Error with a single dict argument. Every raise site
 * fills whichever keys its diagnostic supports; the rest are left absent, and
 * opentlv._from_native() treats a missing key the same as an explicit None.
 * If building the dict itself fails, an exception (typically MemoryError) is
 * already set, and is left in place instead of being overwritten. */
static void raise_error(PyObject* fields) {
    if (fields == NULL) {
        return;
    }
    PyErr_SetObject(opentlv_python_error, fields);
    Py_DECREF(fields);
}

static void raise_code_only(tlv_result_t code) {
    PyObject* fields = PyDict_New();
    if (fields == NULL) {
        return;
    }
    if (dict_set(fields, "code", PyLong_FromLong((long)code)) < 0) {
        Py_DECREF(fields);
        return;
    }
    raise_error(fields);
}

static PyObject* reader_parts_value(tlv_result_t code, const tlv_diagnostic_t* common,
                                    const tlv_reader_detail_t* diag) {
    PyObject* fields = PyDict_New();
    if (fields == NULL) {
        return NULL;
    }
    int         has_offset = common != NULL && common->location.kind;
    size_t      offset = has_offset ? common->location.begin : 0;
    const char* expected = common != NULL ? common->expected : NULL;
    const char* actual = common != NULL ? common->actual : NULL;
    const char* operation = diag != NULL ? tlv_reader_operation_string(diag->operation) : NULL;
    int         has_tag = diag != NULL && diag->has_tag;

    if (dict_set(fields, "code", PyLong_FromLong((long)code)) < 0 ||
        dict_set_size_or_none(fields, "offset", has_offset, offset) < 0 ||
        dict_set(fields, "location", opentlv_python_location(common ? &common->location : NULL)) <
            0 ||
        dict_set_str_or_none(fields, "expected", expected) < 0 ||
        dict_set_str_or_none(fields, "actual", actual) < 0 ||
        dict_set_str_or_none(fields, "operation", operation) < 0 ||
        dict_set_bytes_or_none(fields, "tag", has_tag, has_tag ? diag->tag.data : NULL,
                               has_tag ? diag->tag.size : 0) < 0 ||
        dict_set_bytes_or_none(fields, "raw_length", diag && diag->has_raw_length,
                               diag ? diag->raw_length.data : NULL,
                               diag ? diag->raw_length.size : 0) < 0 ||
        dict_set(fields, "declared_length",
                 diag && diag->has_declared_length
                     ? PyLong_FromUnsignedLongLong(diag->declared_length)
                     : Py_NewRef(Py_None)) < 0 ||
        dict_set_size_or_none(fields, "available", diag && diag->has_available,
                              diag ? diag->available : 0) < 0 ||
        dict_set_size_or_none(fields, "tag_offset", diag && diag->has_tag_offset,
                              diag ? diag->tag_offset : 0) < 0 ||
        dict_set_size_or_none(fields, "length_offset", diag && diag->has_length_offset,
                              diag ? diag->length_offset : 0) < 0 ||
        dict_set_size_or_none(fields, "value_offset", diag && diag->has_value_offset,
                              diag ? diag->value_offset : 0) < 0 ||
        dict_set_size_or_none(fields, "enclosing_end", diag && diag->has_enclosing_end,
                              diag ? diag->enclosing_end : 0) < 0 ||
        dict_set(fields, "required",
                 diag && diag->has_required ? PyLong_FromUnsignedLongLong(diag->required)
                                            : Py_NewRef(Py_None)) < 0) {
        Py_DECREF(fields);
        return NULL;
    }
    if (common_fields(fields, common) < 0) {
        Py_DECREF(fields);
        return NULL;
    }
    return fields;
}

static void raise_reader_parts(tlv_result_t code, const tlv_diagnostic_t* common,
                               const tlv_reader_detail_t* diag) {
    raise_error(reader_parts_value(code, common, diag));
}

static void raise_reader_error(tlv_result_t code, const tlv_reader_diagnostic_t* diag) {
    raise_reader_parts(code, diag ? &diag->diagnostic : NULL, diag ? &diag->detail : NULL);
}

static PyObject* codec_detail_value(const tlv_diagnostic_t*   common,
                                    const tlv_codec_detail_t* detail);

void opentlv_python_raise_query(tlv_result_t code, const tlv_query_diagnostic_t* diagnostic) {
    tlv_query_diagnostic_t state = {0};
    if (code == TLV_ERR_INVALID_STATE) {
        if (diagnostic) state = *diagnostic;
        state.kind = TLV_QUERY_ERROR_STATE;
        diagnostic = &state;
    }
    raise_reader_parts(code, diagnostic ? &diagnostic->diagnostic : NULL,
                       diagnostic && diagnostic->cause == TLV_QUERY_CAUSE_READER
                           ? &diagnostic->detail.reader
                           : NULL);
    if (!diagnostic || !PyErr_ExceptionMatches(opentlv_python_error)) return;
    /* Each Query field comes from one C member; common evidence is already set. */
    int       converted = diagnostic->cause == TLV_QUERY_CAUSE_CODEC;
    PyObject *type, *value, *traceback;
    PyErr_Fetch(&type, &value, &traceback);
    PyErr_NormalizeException(&type, &value, &traceback);
    PyObject* args = value ? PyObject_GetAttrString(value, "args") : NULL;
    PyObject* fields = args ? PyTuple_GetItem(args, 0) : NULL;
    if (fields &&
        (dict_set(fields, "query_kind", PyLong_FromLong(diagnostic->kind)) < 0 ||
         dict_set_str_or_none(fields, "query_kind_name",
                              tlv_query_error_kind_string(diagnostic->kind)) < 0 ||
         dict_set(fields, "expression", opentlv_python_location(&diagnostic->expression)) < 0 ||
         dict_set_str_or_none(fields, "limit", diagnostic->limit) < 0 ||
         dict_set(fields, "configured", PyLong_FromSize_t(diagnostic->configured)) < 0 ||
         dict_set(fields, "codec_detail",
                  converted ? codec_detail_value(&diagnostic->diagnostic, &diagnostic->detail.codec)
                            : Py_NewRef(Py_None)) < 0)) {
        Py_XDECREF(args);
        Py_XDECREF(type);
        Py_XDECREF(value);
        Py_XDECREF(traceback);
        return;
    }
    Py_XDECREF(args);
    PyErr_Restore(type, value, traceback);
}

static void raise_writer_error(tlv_result_t code, const tlv_writer_diagnostic_t* diag) {
    PyObject* fields = PyDict_New();
    if (fields == NULL) {
        return;
    }
    int         has_offset = diag != NULL && diag->diagnostic.location.kind;
    size_t      offset = has_offset ? diag->diagnostic.location.begin : 0;
    const char* expected = diag != NULL ? diag->diagnostic.expected : NULL;
    const char* actual = diag != NULL ? diag->diagnostic.actual : NULL;
    const char* operation = diag != NULL ? tlv_writer_operation_string(diag->operation) : NULL;
    int         has_tag = diag != NULL && diag->has_tag;
    int         has_length = diag != NULL && diag->has_length;
    size_t      length = has_length ? diag->length : 0;
    int         has_required = diag != NULL && diag->has_required;
    size_t      required = has_required ? diag->required : 0;
    int         has_available = diag != NULL && diag->has_available;
    size_t      available = has_available ? diag->available : 0;

    if (dict_set(fields, "code", PyLong_FromLong((long)code)) < 0 ||
        dict_set_size_or_none(fields, "offset", has_offset, offset) < 0 ||
        dict_set(fields, "location",
                 opentlv_python_location(diag ? &diag->diagnostic.location : NULL)) < 0 ||
        dict_set_str_or_none(fields, "expected", expected) < 0 ||
        dict_set_str_or_none(fields, "actual", actual) < 0 ||
        dict_set_str_or_none(fields, "operation", operation) < 0 ||
        dict_set_bytes_or_none(fields, "tag", has_tag, has_tag ? diag->tag.data : NULL,
                               has_tag ? diag->tag.size : 0) < 0 ||
        dict_set_size_or_none(fields, "length", has_length, length) < 0 ||
        dict_set_size_or_none(fields, "required", has_required, required) < 0 ||
        dict_set_size_or_none(fields, "available", has_available, available) < 0) {
        Py_DECREF(fields);
        return;
    }
    if (common_fields(fields, diag ? &diag->diagnostic : NULL) < 0) {
        Py_DECREF(fields);
        return;
    }
    raise_error(fields);
}

/* Schema finding of a diagnostic; Reader and argument failures carry none. */
static const tlv_schema_detail_t* schema_finding(const tlv_schema_diagnostic_t* diagnostic) {
    static const tlv_schema_detail_t none;
    return diagnostic->cause == TLV_SCHEMA_CAUSE_SCHEMA ? &diagnostic->detail.schema : &none;
}

/* Schema locations and native definition indices survive binding conversion. */
static void raise_schema_error(tlv_result_t code, const tlv_schema_diagnostic_t* diagnostic) {
    const tlv_schema_detail_t* detail = schema_finding(diagnostic);
    PyObject*                  fields = PyDict_New();
    if (!fields) return;
    if (dict_set(fields, "code", PyLong_FromLong(code)) < 0 ||
        dict_set_size_or_none(fields, "offset",
                              diagnostic->diagnostic.location.kind != TLV_LOCATION_UNKNOWN,
                              diagnostic->diagnostic.location.begin) < 0 ||
        dict_set(fields, "location", opentlv_python_location(&diagnostic->diagnostic.location)) <
            0 ||
        dict_set(fields, "kind", PyUnicode_FromString(tlv_schema_issue_kind_string(detail->kind))) <
            0 ||
        dict_set(fields, "definition_kind", PyLong_FromLong(detail->definition.kind)) < 0 ||
        dict_set_size_or_none(fields, "definition_index",
                              detail->definition.kind != TLV_SCHEMA_DEFINITION_UNKNOWN,
                              detail->definition.index) < 0) {
        Py_DECREF(fields);
        return;
    }
    if (common_fields(fields, &diagnostic->diagnostic) < 0) {
        Py_DECREF(fields);
        return;
    }
    raise_error(fields);
}

static void free_structure_schema(tlv_structure_schema_t* schema);

/* Frees a rule's owned field schema, copied tag bytes and, recursively, its
 * children schema, but not the rule struct itself: it lives inside its
 * parent schema's rules array. */
static void free_structure_rule_contents(const tlv_structure_rule_t* rule) {
    if (rule->entry) {
        free((void*)rule->entry->tag.data);
        free((void*)rule->entry->name);
    }
    free((void*)rule->entry);
    free_structure_schema((tlv_structure_schema_t*)rule->children);
}

static void free_structure_schema(tlv_structure_schema_t* schema) {
    if (schema == NULL) {
        return;
    }
    for (size_t i = 0; i < schema->count; i++) {
        free_structure_rule_contents(&schema->rules[i]);
    }
    free((void*)schema->rules);
    for (size_t i = 0; i < schema->group_count; ++i) free((void*)schema->groups[i].name);
    free((void*)schema->groups);
    free(schema);
}

static tlv_structure_schema_t* build_structure_schema(PyObject* schema_obj);
/* Own UTF-8 names rather than retaining pointers into temporary Python values. */
static char* schema_name_copy(PyObject* value) {
    if (value == Py_None) return NULL;
    PyObject* encoded = PyUnicode_AsUTF8String(value);
    if (!encoded) return NULL;
    char*      bytes = NULL;
    Py_ssize_t length = 0;
    if (PyBytes_AsStringAndSize(encoded, &bytes, &length) < 0) {
        Py_DECREF(encoded);
        return NULL;
    }
    if (memchr(bytes, 0, (size_t)length)) {
        Py_DECREF(encoded);
        PyErr_SetString(PyExc_ValueError, "schema names cannot contain NUL");
        return NULL;
    }
    char* copy = malloc((size_t)length + 1);
    if (copy)
        memcpy(copy, bytes, (size_t)length + 1);
    else
        PyErr_NoMemory();
    Py_DECREF(encoded);
    return copy;
}

/* Fills `out` from a (tag: bytes, min_length: int, max_length: int,
 * min_occurs: int, max_occurs: int, kind: int, children: schema | None,
 * flags: int, length_multiple: int, group: int, name: str | None)
 * tuple. Returns 1 on success; on failure an exception is set and `out` has
 * no allocation left to free (any partial allocation is cleaned up here). */
static int build_structure_rule(PyObject* rule_obj, tlv_structure_rule_t* out) {
    memset(out, 0, sizeof(*out));
    if (!PyTuple_Check(rule_obj) || PyTuple_Size(rule_obj) != 11) {
        PyErr_SetString(PyExc_TypeError, "each structure rule must be an 11-element tuple; use "
                                         "StructureRule instead of building one directly");
        return 0;
    }
    PyObject* tag_obj = PyTuple_GetItem(rule_obj, 0);
    PyObject* min_length_obj = PyTuple_GetItem(rule_obj, 1);
    PyObject* max_length_obj = PyTuple_GetItem(rule_obj, 2);
    PyObject* min_occurs_obj = PyTuple_GetItem(rule_obj, 3);
    PyObject* max_occurs_obj = PyTuple_GetItem(rule_obj, 4);
    PyObject* kind_obj = PyTuple_GetItem(rule_obj, 5);
    PyObject* children_obj = PyTuple_GetItem(rule_obj, 6);

    char*      tag_data = NULL;
    Py_ssize_t tag_size = 0;
    if (PyBytes_AsStringAndSize(tag_obj, &tag_data, &tag_size) < 0) {
        return 0;
    }
    uint8_t* tag_copy = NULL;
    if (tag_size > 0) {
        tag_copy = malloc((size_t)tag_size);
        if (tag_copy == NULL) {
            PyErr_NoMemory();
            return 0;
        }
        memcpy(tag_copy, tag_data, (size_t)tag_size);
    }

    size_t        min_length = PyLong_AsSize_t(min_length_obj);
    size_t        max_length = PyErr_Occurred() ? 0 : PyLong_AsSize_t(max_length_obj);
    size_t        min_occurs = PyErr_Occurred() ? 0 : PyLong_AsSize_t(min_occurs_obj);
    size_t        max_occurs = PyErr_Occurred() ? 0 : PyLong_AsSize_t(max_occurs_obj);
    long          kind = PyErr_Occurred() ? 0 : PyLong_AsLong(kind_obj);
    unsigned long flags =
        PyErr_Occurred() ? 0 : PyLong_AsUnsignedLong(PyTuple_GetItem(rule_obj, 7));
    size_t        multiple = PyErr_Occurred() ? 0 : PyLong_AsSize_t(PyTuple_GetItem(rule_obj, 8));
    unsigned long group =
        PyErr_Occurred() ? 0 : PyLong_AsUnsignedLong(PyTuple_GetItem(rule_obj, 9));
    if (!PyErr_Occurred() && (flags > UINT32_MAX || group > UINT32_MAX || kind < 0 || kind > 2))
        PyErr_SetString(PyExc_ValueError, "invalid rule flags, group or kind");
    if (PyErr_Occurred()) {
        free(tag_copy);
        return 0;
    }

    tlv_structure_schema_t* children = NULL;
    if (children_obj != Py_None) {
        children = build_structure_schema(children_obj);
        if (children == NULL) {
            free(tag_copy);
            return 0;
        }
    }

    tlv_schema_entry_t* entry = calloc(1, sizeof(*entry));
    if (!entry) {
        free(tag_copy);
        free_structure_schema(children);
        PyErr_NoMemory();
        return 0;
    }
    out->entry = entry;
    entry->tag.data = tag_copy;
    entry->tag.size = (size_t)tag_size;
    entry->min_length = min_length;
    entry->max_length = max_length;
    entry->flags = (uint32_t)flags;
    entry->length_multiple = multiple;
    entry->name = schema_name_copy(PyTuple_GetItem(rule_obj, 10));
    out->min_occurs = min_occurs;
    out->max_occurs = max_occurs;
    out->kind = (tlv_schema_kind_t)kind;
    out->children = children;
    out->group = (uint32_t)group;
    if (PyErr_Occurred()) {
        free_structure_rule_contents(out);
        memset(out, 0, sizeof(*out));
        return 0;
    }
    return 1;
}

/* Builds a schema from (allow_unknown, rules, order, groups),
 * as opentlv.StructureSchema._to_native() produces. Returns a
 * malloc'd tree that free_structure_schema() must free, or NULL with an
 * exception set. */
static tlv_structure_schema_t* build_structure_schema(PyObject* schema_obj) {
    if (!PyTuple_Check(schema_obj) || PyTuple_Size(schema_obj) != 4) {
        PyErr_SetString(PyExc_TypeError,
                        "schema must contain allow_unknown, rules, order and groups");
        return NULL;
    }
    PyObject* allow_unknown_obj = PyTuple_GetItem(schema_obj, 0);
    PyObject* rules_obj = PyTuple_GetItem(schema_obj, 1);
    int       allow_unknown = PyObject_IsTrue(allow_unknown_obj);
    if (allow_unknown < 0) {
        return NULL;
    }
    Py_ssize_t count = PySequence_Size(rules_obj);
    if (count < 0) {
        return NULL;
    }
    if ((size_t)count > SIZE_MAX / sizeof(tlv_structure_rule_t)) {
        raise_code_only(TLV_ERR_OVERFLOW);
        return NULL;
    }

    tlv_structure_schema_t* schema = malloc(sizeof(*schema));
    if (schema == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    schema->rules = NULL;
    schema->count = 0;
    schema->allow_unknown = allow_unknown;
    schema->groups = NULL;
    schema->group_count = 0;
    schema->order = TLV_SCHEMA_ORDER_ANY;
    if (count > 0) {
        tlv_structure_rule_t* rules = calloc((size_t)count, sizeof(*rules));
        if (rules == NULL) {
            PyErr_NoMemory();
            free(schema);
            return NULL;
        }
        schema->rules = rules;
    }

    for (Py_ssize_t i = 0; i < count; i++) {
        PyObject* rule_obj = PySequence_GetItem(rules_obj, i);
        if (rule_obj == NULL) {
            schema->count = (size_t)i;
            free_structure_schema(schema);
            return NULL;
        }
        int ok = build_structure_rule(rule_obj, (tlv_structure_rule_t*)&schema->rules[i]);
        Py_DECREF(rule_obj);
        if (!ok) {
            schema->count = (size_t)i;
            free_structure_schema(schema);
            return NULL;
        }
        schema->count = (size_t)(i + 1);
    }
    long      order = PyLong_AsLong(PyTuple_GetItem(schema_obj, 2));
    PyObject* group_objects = PyTuple_GetItem(schema_obj, 3);
    if (PyErr_Occurred() || (order != 0 && order != 1) || !PyTuple_Check(group_objects)) {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "invalid schema order or groups");
        free_structure_schema(schema);
        return NULL;
    }
    schema->order = (tlv_schema_order_t)order;
    size_t group_count = (size_t)PyTuple_Size(group_objects);
    if (group_count > SIZE_MAX / sizeof(tlv_structure_group_t)) {
        free_structure_schema(schema);
        raise_code_only(TLV_ERR_OVERFLOW);
        return NULL;
    }
    tlv_structure_group_t* groups = group_count ? calloc(group_count, sizeof(*groups)) : NULL;
    if (group_count && !groups) {
        free_structure_schema(schema);
        return (tlv_structure_schema_t*)PyErr_NoMemory();
    }
    schema->groups = groups;
    schema->group_count = group_count;
    for (size_t i = 0; i < group_count; ++i) {
        PyObject* item = PyTuple_GetItem(group_objects, (Py_ssize_t)i);
        if (!PyTuple_Check(item) || PyTuple_Size(item) != 4) {
            PyErr_SetString(PyExc_TypeError, "group must contain id, occurrence bounds and name");
            free_structure_schema(schema);
            return NULL;
        }
        unsigned long id = PyLong_AsUnsignedLong(PyTuple_GetItem(item, 0));
        groups[i].min_occurs = PyErr_Occurred() ? 0 : PyLong_AsSize_t(PyTuple_GetItem(item, 1));
        groups[i].max_occurs = PyErr_Occurred() ? 0 : PyLong_AsSize_t(PyTuple_GetItem(item, 2));
        if (!PyErr_Occurred() && id > UINT32_MAX)
            PyErr_SetString(PyExc_OverflowError, "group id exceeds uint32");
        if (PyErr_Occurred()) {
            free_structure_schema(schema);
            return NULL;
        }
        groups[i].id = (uint32_t)id;
        groups[i].name = schema_name_copy(PyTuple_GetItem(item, 3));
        if (PyErr_Occurred()) {
            free_structure_schema(schema);
            return NULL;
        }
    }
    return schema;
}

/* Copy every borrowed field before the schema and input are released. */
static PyObject* schema_diagnostic_value(const tlv_schema_diagnostic_t* diagnostic) {
    const tlv_schema_detail_t* detail = schema_finding(diagnostic);
    PyObject*                  path = PyTuple_New((Py_ssize_t)diagnostic->diagnostic.path.length);
    if (!path) return NULL;
    for (size_t i = 0; i < diagnostic->diagnostic.path.length; ++i) {
        tlv_tag_t tag = diagnostic->diagnostic.path.tags[i];
        PyObject* value = PyBytes_FromStringAndSize((const char*)tag.data, (Py_ssize_t)tag.size);
        if (!value) {
            Py_DECREF(path);
            return NULL;
        }
        PyTuple_SetItem(path, (Py_ssize_t)i, value);
    }
    PyObject* tag =
        PyBytes_FromStringAndSize((const char*)detail->tag.data, (Py_ssize_t)detail->tag.size);
    PyObject* offset = diagnostic->diagnostic.location.kind
                           ? PyLong_FromSize_t(diagnostic->diagnostic.location.begin)
                           : Py_NewRef(Py_None);
    PyObject* occurs = detail->has_occurs
                           ? Py_BuildValue("(KKK)", (unsigned long long)detail->min_occurs,
                                           (unsigned long long)detail->max_occurs,
                                           (unsigned long long)detail->occurs)
                           : Py_NewRef(Py_None);
    PyObject* length = detail->has_length
                           ? Py_BuildValue("(KKK)", (unsigned long long)detail->min_length,
                                           (unsigned long long)detail->max_length,
                                           (unsigned long long)detail->actual_length)
                           : Py_NewRef(Py_None);
    PyObject* form = detail->has_form ? Py_BuildValue("(ii)", (int)detail->expected_form,
                                                      detail->actual_constructed)
                                      : Py_NewRef(Py_None);
    /* N consumes each reference, including on failure. */
    return Py_BuildValue(
        "(iiisNNNziNNNKIKNin)", (int)diagnostic->diagnostic.code,
        (int)diagnostic->diagnostic.severity, (int)detail->kind,
        tlv_schema_issue_kind_string(detail->kind), tag, path, offset, detail->field,
        detail->is_group, occurs, length, form, (unsigned long long)detail->length_multiple,
        (unsigned int)detail->length_flags, (unsigned long long)diagnostic->diagnostic.path.omitted,
        opentlv_python_location(&diagnostic->diagnostic.location), (int)detail->definition.kind,
        (Py_ssize_t)detail->definition.index);
}

static PyObject* schema_diagnostic_report(const Py_buffer* buffer, const tlv_format_t* format,
                                          const tlv_structure_schema_t* schema, size_t max_depth,
                                          size_t max_elements, size_t capacity,
                                          tlv_schema_unknown_policy_t unknown) {
    tlv_schema_diagnostic_t* storage = capacity ? calloc(capacity, sizeof(*storage)) : NULL;
    if (capacity && !storage) return PyErr_NoMemory();
    tlv_schema_diagnostic_report_t report = {storage, capacity, 0};
    tlv_schema_diagnostic_t        offset = {0};
    tlv_result_t                   code =
        tlv_schema_validate_all_diag(buffer->buf, (size_t)buffer->len, format, schema, max_depth,
                                     max_elements, unknown, &report, &offset);
    PyObject* result = NULL;
    if (code == TLV_OK || code == TLV_ERR_SCHEMA) {
        size_t    stored = report.count < capacity ? report.count : capacity;
        PyObject* items = PyTuple_New((Py_ssize_t)stored);
        if (items) {
            for (size_t i = 0; i < stored; ++i) {
                PyObject* item = schema_diagnostic_value(&storage[i]);
                if (!item) {
                    Py_CLEAR(items);
                    break;
                }
                PyTuple_SetItem(items, (Py_ssize_t)i, item);
            }
            if (items) result = Py_BuildValue("(NN)", PyLong_FromSize_t(report.count), items);
        }
    } else
        raise_schema_error(code, &offset);
    free(storage);
    return result;
}

/* structure_validate(data, format, schema, max_depth, max_elements) -> None
 *
 * Validates `data` against `schema` (an opentlv.StructureSchema serialized
 * with _to_native()) using wire format `format`. Raises
 * _opentlv.Error with "code" and "offset" on the first violation or
 * wire-level error. */
static PyObject* _opentlv_structure_validate(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  buffer;
    PyObject*  format_obj;
    PyObject*  schema_obj;
    Py_ssize_t max_depth, max_elements;
    Py_ssize_t report_capacity = -1;
    int        unknown = 0;
    if (!PyArg_ParseTuple(args, "y*OOnn|ni", &buffer, &format_obj, &schema_obj, &max_depth,
                          &max_elements, &report_capacity, &unknown)) {
        return NULL;
    }
    tlv_fixed_format_t  fixed;
    tlv_format_t        descriptor;
    const tlv_format_t* format = NULL;
    if (PyTuple_Check(format_obj)) {
        Py_ssize_t tag_size, length_size;
        int        big_endian;
        if (!PyArg_ParseTuple(format_obj, "nnp", &tag_size, &length_size, &big_endian)) {
            PyBuffer_Release(&buffer);
            return NULL;
        }
        if (tag_size < 0 || length_size < 0) {
            PyBuffer_Release(&buffer);
            PyErr_SetString(PyExc_ValueError, "negative format width");
            return NULL;
        }
        fixed.identifier.size = (size_t)tag_size;
        fixed.length.size = (size_t)length_size;
        fixed.length.byte_order =
            big_endian ? TLV_BYTE_ORDER_BIG_ENDIAN : TLV_BYTE_ORDER_LITTLE_ENDIAN;
        fixed.element_order = TLV_ELEMENT_ORDER_TLV;
        fixed.length_scope = TLV_LENGTH_SCOPE_VALUE;
        tlv_result_t rc = tlv_fixed_format_init(&descriptor, &fixed);
        if (rc != TLV_OK) {
            PyBuffer_Release(&buffer);
            raise_code_only(rc);
            return NULL;
        }
        format = &descriptor;
    } else {
        long format_id = PyLong_AsLong(format_obj);
        if (PyErr_Occurred()) {
            PyBuffer_Release(&buffer);
            return NULL;
        }
        if (format_id >= 0 && format_id <= INT_MAX)
            format = opentlv_python_format_for((int)format_id);
    }
    if (format == NULL) {
        PyBuffer_Release(&buffer);
        PyErr_SetString(PyExc_ValueError, "unknown format");
        return NULL;
    }
    if (max_depth < 0 || max_elements < 0) {
        PyBuffer_Release(&buffer);
        PyErr_SetString(PyExc_ValueError, "max_depth and max_elements must not be negative");
        return NULL;
    }
    if (PyTuple_Size(args) > 5 &&
        (report_capacity < 0 ||
         (size_t)report_capacity > SIZE_MAX / sizeof(tlv_schema_diagnostic_t))) {
        PyBuffer_Release(&buffer);
        PyErr_SetString(PyExc_ValueError, "invalid report capacity");
        return NULL;
    }

    tlv_structure_schema_t* schema = build_structure_schema(schema_obj);
    if (schema == NULL) {
        PyBuffer_Release(&buffer);
        return NULL;
    }

    tlv_schema_diagnostic_t diagnostic;
    if (report_capacity >= 0) {
        PyObject* result = schema_diagnostic_report(&buffer, format, schema, (size_t)max_depth,
                                                    (size_t)max_elements, (size_t)report_capacity,
                                                    (tlv_schema_unknown_policy_t)unknown);
        free_structure_schema(schema);
        PyBuffer_Release(&buffer);
        return result;
    }
    tlv_result_t code =
        tlv_schema_validate((const uint8_t*)buffer.buf, (size_t)buffer.len, format, schema,
                            (size_t)max_depth, (size_t)max_elements, &diagnostic);
    free_structure_schema(schema);
    PyBuffer_Release(&buffer);
    if (code != TLV_OK) {
        raise_schema_error(code, &diagnostic);
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject* codec_detail_value(const tlv_diagnostic_t*   common,
                                    const tlv_codec_detail_t* detail) {
    PyObject* result =
        Py_BuildValue("{s:i,s:i,s:i,s:i,s:z,s:i}", "operation", detail->operation, "reported",
                      detail->reported, "violation", detail->violation, "reason", detail->reason,
                      "representation", detail->representation, "cause", detail->cause);
    if (!result) return NULL;
    if (dict_set_str_or_none(result, "operation_name",
                             tlv_codec_operation_string(detail->operation)) < 0 ||
        dict_set_str_or_none(result, "cause_name", tlv_codec_cause_string(detail->cause)) < 0 ||
        dict_set_str_or_none(result, "reason_name", tlv_codec_reason_string(detail->reason)) < 0 ||
        dict_set_str_or_none(result, "violation_name",
                             tlv_codec_violation_string(detail->violation)) < 0) {
        Py_DECREF(result);
        return NULL;
    }
    if (common_fields(result, common) < 0) {
        Py_DECREF(result);
        return NULL;
    }
    if (detail->cause == TLV_CODEC_CAUSE_READER &&
        dict_set(result, "reader",
                 reader_parts_value(common->code, common, &detail->detail.reader)) < 0) {
        Py_DECREF(result);
        return NULL;
    }
    if (detail->cause == TLV_CODEC_CAUSE_SCHEMA) {
        tlv_schema_diagnostic_t schema = {0};
        schema.diagnostic = *common;
        schema.cause = TLV_SCHEMA_CAUSE_SCHEMA;
        schema.detail.schema = detail->detail.schema;
        if (dict_set(result, "schema", schema_diagnostic_value(&schema)) < 0) {
            Py_DECREF(result);
            return NULL;
        }
    }
    return result;
}

static void raise_codec_error(tlv_result_t code, const tlv_codec_diagnostic_t* diagnostic) {
    PyObject* fields = PyDict_New();
    if (!fields) return;
    if (dict_set(fields, "code", PyLong_FromLong(code)) < 0 ||
        dict_set(fields, "location", opentlv_python_location(&diagnostic->diagnostic.location)) <
            0 ||
        dict_set(fields, "codec_detail",
                 codec_detail_value(&diagnostic->diagnostic, &diagnostic->codec)) < 0) {
        Py_DECREF(fields);
        return;
    }
    raise_error(fields);
}

/* Names do not participate in lookup; the facade retains them in its records. */
static PyObject* _opentlv_definition_find(PyObject* module, PyObject* args) {
    (void)module;
    PyObject *tags, *wanted;
    if (!PyArg_ParseTuple(args, "OO", &tags, &wanted)) return NULL;
    if (!PyTuple_Check(tags) || !PyBytes_Check(wanted)) {
        PyErr_SetString(PyExc_TypeError, "immutable tag tuple and bytes required");
        return NULL;
    }
    size_t count = (size_t)PyTuple_Size(tags);
    if (count > SIZE_MAX / sizeof(tlv_definition_t)) {
        raise_code_only(TLV_ERR_OVERFLOW);
        return NULL;
    }
    tlv_definition_t* entries = count ? calloc(count, sizeof(*entries)) : NULL;
    if (count && !entries) return PyErr_NoMemory();
    for (size_t i = 0; i < count; ++i) {
        PyObject* tag = PyTuple_GetItem(tags, (Py_ssize_t)i);
        if (!PyBytes_Check(tag)) {
            free(entries);
            PyErr_SetString(PyExc_TypeError, "immutable tag bytes required");
            return NULL;
        }
        entries[i].tag = tlv_tag((const uint8_t*)PyBytes_AsString(tag), (size_t)PyBytes_Size(tag));
    }
    tlv_tag_t tag = tlv_tag((const uint8_t*)PyBytes_AsString(wanted), (size_t)PyBytes_Size(wanted));
    tlv_definition_registry_t registry = {entries, count};
    const tlv_definition_t*   found = tlv_definition_find(&registry, &tag);
    PyObject* result = found ? PyLong_FromSize_t((size_t)(found - entries)) : Py_NewRef(Py_None);
    free(entries);
    return result;
}

static PyObject* _opentlv_number_codec(PyObject* module, PyObject* args) {
    (void)module;
    tlv_codec_diagnostic_t diagnostic;
    int                    operation, encoding;
    Py_ssize_t             width;
    PyObject*              digits_obj;
    PyObject*              input;
    PyObject*              output = Py_None;
    if (!PyArg_ParseTuple(args, "iinOO|O", &operation, &encoding, &width, &digits_obj, &input,
                          &output))
        return NULL;
    if (width < 0) {
        PyErr_SetString(PyExc_ValueError, "negative codec width");
        return NULL;
    }
    unsigned long digits = PyLong_AsUnsignedLong(digits_obj);
    if (PyErr_Occurred()) return NULL;
    if (digits > UINT_MAX) {
        PyErr_SetString(PyExc_OverflowError, "digits exceed unsigned int");
        return NULL;
    }
    tlv_number_codec_config_t config = {(tlv_number_encoding_t)encoding, (size_t)width,
                                        (unsigned int)digits};
    uint64_t                  value = 0;
    tlv_result_t              code;
    if (operation == 0) {
        Py_buffer data;
        if (PyObject_GetBuffer(input, &data, PyBUF_SIMPLE) < 0) return NULL;
        code = tlv_number_decode(&config, data.buf, (size_t)data.len, &value, sizeof(value),
                                 &diagnostic);
        PyBuffer_Release(&data);
        if (code != TLV_OK) {
            raise_codec_error(code, &diagnostic);
            return NULL;
        }
        return PyLong_FromUnsignedLongLong(value);
    }
    value = PyLong_AsUnsignedLongLong(input);
    if (PyErr_Occurred()) return NULL;
    size_t written = 0;
    if (operation == 3) {
        Py_buffer buffer;
        if (PyObject_GetBuffer(output, &buffer, PyBUF_WRITABLE) < 0) return NULL;
        code = tlv_number_encode(&config, &value, sizeof(value), buffer.buf, (size_t)buffer.len,
                                 &written, &diagnostic);
        PyBuffer_Release(&buffer);
        if (code != TLV_OK) {
            raise_codec_error(code, &diagnostic);
            return NULL;
        }
        return PyLong_FromSize_t(written);
    }
    if (operation != 1 && operation != 2) {
        PyErr_SetString(PyExc_ValueError, "unknown codec operation");
        return NULL;
    }
    code = tlv_number_encode(&config, &value, sizeof(value), NULL, 0, &written, &diagnostic);
    if (code != TLV_OK) {
        raise_codec_error(code, &diagnostic);
        return NULL;
    }
    if (operation == 2) return PyLong_FromSize_t(written);
    /* Numeric C representations never exceed nine bytes; size query already validates. */
    uint8_t bytes[9];
    code = tlv_number_encode(&config, &value, sizeof(value), bytes, sizeof(bytes), &written,
                             &diagnostic);
    if (code != TLV_OK) {
        raise_codec_error(code, &diagnostic);
        return NULL;
    }
    return PyBytes_FromStringAndSize((const char*)bytes, (Py_ssize_t)written);
}

#if OPENTLV_EMV
/* emv_decode_amount(data) -> int
 *
 * Decodes 6 bytes of BCD (EMV format n12) into an unscaled minor-unit
 * amount, using the public `tlv_emv_codec_amount` codec. Raises _opentlv.Error
 * on failure. */
static PyObject* _opentlv_emv_decode_amount(PyObject* module, PyObject* args) {
    (void)module;
    tlv_codec_diagnostic_t diagnostic;
    Py_buffer              buffer;
    if (!PyArg_ParseTuple(args, "y*", &buffer)) {
        return NULL;
    }
    uint64_t     value = 0;
    tlv_result_t code = tlv_codec_decode(&tlv_emv_codec_amount, (const uint8_t*)buffer.buf,
                                         (size_t)buffer.len, &value, sizeof(value), &diagnostic);
    PyBuffer_Release(&buffer);
    if (code != TLV_OK) {
        raise_codec_error(code, &diagnostic);
        return NULL;
    }
    return PyLong_FromUnsignedLongLong((unsigned long long)value);
}

/* emv_encode_amount(value) -> bytes
 *
 * Encodes an unscaled minor-unit amount as 6 bytes of BCD (EMV format n12),
 * using the public `tlv_emv_codec_amount` codec. Raises
 * _opentlv.Error on failure, for example if `value` does not fit
 * the format's 12-digit range. */
static PyObject* _opentlv_emv_encode_amount(PyObject* module, PyObject* args) {
    (void)module;
    tlv_codec_diagnostic_t diagnostic;
    unsigned long long     value_arg;
    if (!PyArg_ParseTuple(args, "K", &value_arg)) {
        return NULL;
    }
    uint64_t     value = (uint64_t)value_arg;
    uint8_t      data[16]; /* the amount codec always writes exactly 6 bytes; generous headroom */
    size_t       written = 0;
    tlv_result_t code = tlv_codec_encode(&tlv_emv_codec_amount, &value, sizeof(value), data,
                                         sizeof(data), &written, &diagnostic);
    if (code != TLV_OK) {
        raise_codec_error(code, &diagnostic);
        return NULL;
    }
    return PyBytes_FromStringAndSize((const char*)data, (Py_ssize_t)written);
}

#endif

#define DOCUMENT_CAPSULE_NAME "_opentlv.Document"

static void document_capsule_destructor(PyObject* capsule) {
    tlv_document_t* document =
        (tlv_document_t*)PyCapsule_GetPointer(capsule, DOCUMENT_CAPSULE_NAME);
    if (document != NULL) {
        tlv_document_free(document);
    }
    PyObject* owner = PyCapsule_GetContext(capsule);
    Py_XDECREF(owner);
}

/* Keep Format storage alive for documents built from a cursor-owned descriptor. */
PyObject* opentlv_python_document_wrap(tlv_document_t* document, PyObject* owner) {
    PyObject* capsule = PyCapsule_New(document, DOCUMENT_CAPSULE_NAME, document_capsule_destructor);
    if (!capsule) {
        tlv_document_free(document);
        return NULL;
    }
    if (owner) {
        if (PyCapsule_SetContext(capsule, owner) < 0) {
            Py_DECREF(capsule);
            return NULL;
        }
        Py_INCREF(owner);
    }
    return capsule;
}

/* Returns the document a capsule holds, or NULL with an exception set if
 * `capsule_obj` is not one of our document capsules. */
static tlv_document_t* document_from_capsule(PyObject* capsule_obj) {
    return (tlv_document_t*)PyCapsule_GetPointer(capsule_obj, DOCUMENT_CAPSULE_NAME);
}

tlv_document_t* opentlv_python_document_pointer(PyObject* capsule) {
    return document_from_capsule(capsule);
}

/* PyArg_ParseTuple "O&" converter: None -> NULL, an int from node_to_py() ->
 * that pointer. Returns 1 on success, 0 with an exception set on failure. */
static int py_to_node(PyObject* obj, void* out) {
    tlv_node_t** node_out = (tlv_node_t**)out;
    if (obj == Py_None) {
        *node_out = NULL;
        return 1;
    }
    void* ptr = PyLong_AsVoidPtr(obj);
    if (ptr == NULL && PyErr_Occurred()) {
        return 0;
    }
    *node_out = (tlv_node_t*)ptr;
    return 1;
}

static PyObject* node_to_py(tlv_node_t* node) {
    if (node == NULL) {
        Py_RETURN_NONE;
    }
    return PyLong_FromVoidPtr(node);
}

static PyObject* _opentlv_node_identity(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&", py_to_node, &node)) return NULL;
    return PyLong_FromUnsignedLongLong(tlv_node_identity(node));
}

/* Builds document options from a Python-supplied format ID and limits.
 * Returns 1 on success; on failure an exception is set and `*out` is
 * unusable. */
static int build_document_options(const tlv_format_t* format, Py_ssize_t max_depth,
                                  Py_ssize_t max_elements, tlv_document_options_t* out) {
    if (format == NULL) {
        PyErr_SetString(PyExc_ValueError, "unknown format");
        return 0;
    }
    if (max_depth < 0 || max_elements < 0) {
        PyErr_SetString(PyExc_ValueError, "max_depth and max_elements must not be negative");
        return 0;
    }
    tlv_result_t code = tlv_document_options_init(out, format);
    if (code != TLV_OK) {
        raise_code_only(code);
        return 0;
    }
    out->max_depth = (size_t)max_depth;
    out->max_elements = (size_t)max_elements;
    return 1;
}

/* document_create(format, max_depth, max_elements) -> capsule
 *
 * Creates an empty document. Raises _opentlv.Error on failure. */
static PyObject* _opentlv_document_create(PyObject* module, PyObject* args) {
    (void)module;
    PyObject*  format_spec;
    Py_ssize_t max_depth, max_elements;
    if (!PyArg_ParseTuple(args, "Onn", &format_spec, &max_depth, &max_elements)) {
        return NULL;
    }
    tlv_document_options_t options;
    PyObject*              owner = opentlv_python_format_owner(format_spec);
    if (!owner) return NULL;
    if (!build_document_options(opentlv_python_format_pointer(owner), max_depth, max_elements,
                                &options)) {
        Py_DECREF(owner);
        return NULL;
    }
    tlv_document_t* document = NULL;
    tlv_result_t    code = tlv_document_create(&options, &document);
    if (code != TLV_OK) {
        raise_code_only(code);
        Py_DECREF(owner);
        return NULL;
    }
    PyObject* capsule = opentlv_python_document_wrap(document, owner);
    Py_DECREF(owner);
    return capsule;
}

/* document_parse(data, format, max_depth, max_elements) -> capsule
 *
 * Parses `data` into a new owned document. Raises _opentlv.Error with
 * "code" and "offset" on failure. */
static PyObject* _opentlv_document_parse(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  buffer;
    PyObject*  format_spec;
    Py_ssize_t max_depth, max_elements;
    int        retain_source_locations = 0;
    if (!PyArg_ParseTuple(args, "y*Onn|p", &buffer, &format_spec, &max_depth, &max_elements,
                          &retain_source_locations)) {
        return NULL;
    }
    tlv_document_options_t options;
    PyObject*              owner = opentlv_python_format_owner(format_spec);
    if (!owner) {
        PyBuffer_Release(&buffer);
        return NULL;
    }
    if (!build_document_options(opentlv_python_format_pointer(owner), max_depth, max_elements,
                                &options)) {
        Py_DECREF(owner);
        PyBuffer_Release(&buffer);
        return NULL;
    }
    options.retain_source_locations = retain_source_locations;
    tlv_document_t*         document = NULL;
    tlv_reader_diagnostic_t diagnostic = {0};
    tlv_result_t code = tlv_document_parse((const uint8_t*)buffer.buf, (size_t)buffer.len, &options,
                                           &document, &diagnostic);
    PyBuffer_Release(&buffer);
    if (code != TLV_OK) {
        raise_reader_error(code, &diagnostic);
        Py_DECREF(owner);
        return NULL;
    }
    PyObject* capsule = opentlv_python_document_wrap(document, owner);
    Py_DECREF(owner);
    return capsule;
}

static PyObject* _opentlv_document_count(PyObject* module, PyObject* args) {
    (void)module;
    PyObject* capsule;
    if (!PyArg_ParseTuple(args, "O", &capsule)) {
        return NULL;
    }
    tlv_document_t* document = document_from_capsule(capsule);
    if (document == NULL) {
        return NULL;
    }
    return PyLong_FromSize_t(tlv_document_count(document));
}

static PyObject* _opentlv_document_first(PyObject* module, PyObject* args) {
    (void)module;
    PyObject* capsule;
    if (!PyArg_ParseTuple(args, "O", &capsule)) {
        return NULL;
    }
    tlv_document_t* document = document_from_capsule(capsule);
    if (document == NULL) {
        return NULL;
    }
    return node_to_py(tlv_document_first(document));
}

/* document_find(capsule, parent, tag) -> int | None */
static PyObject* _opentlv_document_find(PyObject* module, PyObject* args) {
    (void)module;
    PyObject*   capsule;
    tlv_node_t* parent;
    Py_buffer   tag_buf;
    if (!PyArg_ParseTuple(args, "OO&y*", &capsule, py_to_node, &parent, &tag_buf)) {
        return NULL;
    }
    tlv_document_t* document = document_from_capsule(capsule);
    if (document == NULL) {
        PyBuffer_Release(&tag_buf);
        return NULL;
    }
    tlv_tag_t   tag = tlv_tag((const uint8_t*)tag_buf.buf, (size_t)tag_buf.len);
    tlv_node_t* found = tlv_document_find(document, parent, tag);
    PyBuffer_Release(&tag_buf);
    return node_to_py(found);
}

/* document_find_path(capsule, query_text) -> int | None */
static PyObject* _opentlv_document_find_path(PyObject* module, PyObject* args) {
    (void)module;
    PyObject*   capsule;
    const char* text;
    if (!PyArg_ParseTuple(args, "Os", &capsule, &text)) {
        return NULL;
    }
    tlv_document_t* document = document_from_capsule(capsule);
    if (document == NULL) {
        return NULL;
    }
    tlv_query_t      query;
    tlv_diagnostic_t parse = {0};
    tlv_result_t     code = tlv_query_parse(text, &query, &parse);
    if (code != TLV_OK) {
        const tlv_query_diagnostic_t failure =
            opentlv_binding_path_failure(code, &parse, text, strlen(text));
        opentlv_python_raise_query(code, &failure);
        return NULL;
    }
    tlv_node_t* node = NULL;
    code = tlv_document_find_path(document, &query, &node);
    if (code != TLV_OK) {
        raise_reader_error(code, NULL);
        return NULL;
    }
    return node_to_py(node);
}

/* document_insert(capsule, parent, before, tag, value) -> int (the new node) */
static PyObject* _opentlv_document_insert(PyObject* module, PyObject* args) {
    (void)module;
    PyObject*   capsule;
    tlv_node_t* parent;
    tlv_node_t* before;
    Py_buffer   tag_buf, value_buf;
    if (!PyArg_ParseTuple(args, "OO&O&y*y*", &capsule, py_to_node, &parent, py_to_node, &before,
                          &tag_buf, &value_buf)) {
        return NULL;
    }
    tlv_document_t* document = document_from_capsule(capsule);
    if (document == NULL) {
        PyBuffer_Release(&tag_buf);
        PyBuffer_Release(&value_buf);
        return NULL;
    }
    tlv_tag_t    tag = tlv_tag((const uint8_t*)tag_buf.buf, (size_t)tag_buf.len);
    tlv_node_t*  node = NULL;
    tlv_result_t code = tlv_document_insert(
        document, parent, before, tag, (const uint8_t*)value_buf.buf, (size_t)value_buf.len, &node);
    PyBuffer_Release(&tag_buf);
    PyBuffer_Release(&value_buf);
    if (code != TLV_OK) {
        raise_code_only(code);
        return NULL;
    }
    return node_to_py(node);
}

static PyObject* _opentlv_document_encoded_size(PyObject* module, PyObject* args) {
    (void)module;
    int       format_id = -1;
    PyObject* capsule;
    if (!PyArg_ParseTuple(args, "O|i", &capsule, &format_id)) {
        return NULL;
    }
    tlv_document_t* document = document_from_capsule(capsule);
    if (document == NULL) {
        return NULL;
    }
    const tlv_format_t* destination = format_id == -1 ? NULL : opentlv_python_format_for(format_id);
    if (format_id != -1 && !destination) {
        PyErr_SetString(PyExc_ValueError, "unsupported destination Format");
        return NULL;
    }
    size_t       size = 0;
    tlv_result_t code = (destination ? tlv_document_encoded_size_as(document, destination, &size)
                                     : tlv_document_encoded_size(document, &size));
    if (code != TLV_OK) {
        raise_code_only(code);
        return NULL;
    }
    return PyLong_FromSize_t(size);
}

static PyObject* _opentlv_document_encode(PyObject* module, PyObject* args) {
    (void)module;
    int       format_id = -1;
    PyObject* capsule;
    if (!PyArg_ParseTuple(args, "O|i", &capsule, &format_id)) {
        return NULL;
    }
    tlv_document_t* document = document_from_capsule(capsule);
    if (document == NULL) {
        return NULL;
    }
    const tlv_format_t* destination = format_id == -1 ? NULL : opentlv_python_format_for(format_id);
    if (format_id != -1 && !destination) {
        PyErr_SetString(PyExc_ValueError, "unsupported destination Format");
        return NULL;
    }
    size_t       size = 0;
    tlv_result_t code = (destination ? tlv_document_encoded_size_as(document, destination, &size)
                                     : tlv_document_encoded_size(document, &size));
    if (code != TLV_OK) {
        raise_code_only(code);
        return NULL;
    }
    if (size > PY_SSIZE_T_MAX) {
        raise_code_only(TLV_ERR_NATIVE_SIZE);
        return NULL;
    }
    PyObject* result = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)size);
    if (result == NULL) {
        return NULL;
    }
    char*  buf = PyBytes_AsString(result);
    size_t written = 0;
    code =
        (destination ? tlv_document_encode_as(document, destination, (uint8_t*)buf, size, &written)
                     : tlv_document_encode(document, (uint8_t*)buf, size, &written));
    if (code != TLV_OK) {
        Py_DECREF(result);
        raise_code_only(code);
        return NULL;
    }
    if (written != size) {
        Py_DECREF(result);
        PyErr_SetString(PyExc_RuntimeError, "tlv_document_encode wrote a different size than "
                                            "tlv_document_encoded_size reported");
        return NULL;
    }
    return result;
}

static PyObject* _opentlv_node_first_child(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&", py_to_node, &node)) {
        return NULL;
    }
    return node_to_py(tlv_node_first_child(node));
}

static PyObject* _opentlv_node_next(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&", py_to_node, &node)) {
        return NULL;
    }
    return node_to_py(tlv_node_next(node));
}

static PyObject* _opentlv_node_parent(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&", py_to_node, &node)) {
        return NULL;
    }
    return node_to_py(tlv_node_parent(node));
}

static PyObject* _opentlv_node_next_same_tag(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&", py_to_node, &node)) {
        return NULL;
    }
    return node_to_py(tlv_node_next_same_tag(node));
}

static PyObject* _opentlv_node_tag(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&", py_to_node, &node)) {
        return NULL;
    }
    tlv_tag_t tag = tlv_node_tag(node);
    return PyBytes_FromStringAndSize((const char*)tag.data, (Py_ssize_t)tag.size);
}

static PyObject* _opentlv_node_is_constructed(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&", py_to_node, &node)) {
        return NULL;
    }
    return PyBool_FromLong(tlv_node_is_constructed(node));
}

static PyObject* _opentlv_node_value(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&", py_to_node, &node)) {
        return NULL;
    }
    const uint8_t* data = tlv_node_value_data(node);
    size_t         size = tlv_node_value_size(node);
    return PyBytes_FromStringAndSize((const char*)data, (Py_ssize_t)size);
}

static PyObject* _opentlv_node_set_value(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    Py_buffer   value_buf;
    if (!PyArg_ParseTuple(args, "O&y*", py_to_node, &node, &value_buf)) {
        return NULL;
    }
    tlv_result_t code =
        tlv_node_set_value(node, (const uint8_t*)value_buf.buf, (size_t)value_buf.len);
    PyBuffer_Release(&value_buf);
    if (code != TLV_OK) {
        raise_code_only(code);
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject* _opentlv_node_erase(PyObject* module, PyObject* args) {
    (void)module;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&", py_to_node, &node)) {
        return NULL;
    }
    tlv_node_erase(node);
    Py_RETURN_NONE;
}

static PyObject* _opentlv_node_encoded_size(PyObject* module, PyObject* args) {
    (void)module;
    int         format_id = -1;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&|i", py_to_node, &node, &format_id)) {
        return NULL;
    }
    const tlv_format_t* destination = format_id == -1 ? NULL : opentlv_python_format_for(format_id);
    if (format_id != -1 && !destination) {
        PyErr_SetString(PyExc_ValueError, "unsupported destination Format");
        return NULL;
    }
    size_t       size = 0;
    tlv_result_t code = (destination ? tlv_node_encoded_size_as(node, destination, &size)
                                     : tlv_node_encoded_size(node, &size));
    if (code != TLV_OK) {
        raise_code_only(code);
        return NULL;
    }
    return PyLong_FromSize_t(size);
}

static PyObject* _opentlv_node_encode(PyObject* module, PyObject* args) {
    (void)module;
    int         format_id = -1;
    tlv_node_t* node;
    if (!PyArg_ParseTuple(args, "O&|i", py_to_node, &node, &format_id)) {
        return NULL;
    }
    const tlv_format_t* destination = format_id == -1 ? NULL : opentlv_python_format_for(format_id);
    if (format_id != -1 && !destination) {
        PyErr_SetString(PyExc_ValueError, "unsupported destination Format");
        return NULL;
    }
    size_t       size = 0;
    tlv_result_t code = (destination ? tlv_node_encoded_size_as(node, destination, &size)
                                     : tlv_node_encoded_size(node, &size));
    if (code != TLV_OK) {
        raise_code_only(code);
        return NULL;
    }
    if (size > PY_SSIZE_T_MAX) {
        raise_code_only(TLV_ERR_NATIVE_SIZE);
        return NULL;
    }
    PyObject* result = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)size);
    if (result == NULL) {
        return NULL;
    }
    char*  buf = PyBytes_AsString(result);
    size_t written = 0;
    code = (destination ? tlv_node_encode_as(node, destination, (uint8_t*)buf, size, &written)
                        : tlv_node_encode(node, (uint8_t*)buf, size, &written));
    if (code != TLV_OK) {
        Py_DECREF(result);
        raise_code_only(code);
        return NULL;
    }
    if (written != size) {
        Py_DECREF(result);
        PyErr_SetString(
            PyExc_RuntimeError,
            "tlv_node_encode wrote a different size than tlv_node_encoded_size reported");
        return NULL;
    }
    return result;
}

/* read(data, offset, format) -> (tag: bytes, length_offset: int, length_size: int, value_offset:
 * int, value_length: int, consumed: int)
 *
 * Parses one element at `offset` in `data` using wire format `format` (an
 * opentlv.Format value) and raises _opentlv.Error on failure. `data` is
 * any buffer-protocol object; `value_offset`/`value_length` describe the
 * value as a range within `data`, so the caller can slice it without
 * copying. */
static PyObject* _opentlv_read(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  buffer;
    Py_ssize_t offset;
    int        format_id;
    if (!PyArg_ParseTuple(args, "y*ni", &buffer, &offset, &format_id)) {
        return NULL;
    }
    const tlv_format_t* format = opentlv_python_format_for(format_id);
    if (format == NULL) {
        PyBuffer_Release(&buffer);
        PyErr_SetString(PyExc_ValueError, "unknown format");
        return NULL;
    }
    if (offset < 0 || offset > buffer.len) {
        PyBuffer_Release(&buffer);
        PyErr_SetString(PyExc_ValueError, "offset is out of range for data");
        return NULL;
    }

    const uint8_t*          base = (const uint8_t*)buffer.buf;
    size_t                  size = (size_t)(buffer.len - offset);
    tlv_element_t           element;
    size_t                  consumed = 0;
    tlv_reader_diagnostic_t diag;
    tlv_reader_diagnostic_init(&diag);

    tlv_source_t source;
    tlv_result_t code =
        tlv_read_source_diag(base + offset, size, format, &element, &consumed, &source, &diag);
    if (code != TLV_OK) {
        raise_reader_error(code, &diag);
        PyBuffer_Release(&buffer);
        return NULL;
    }

    size_t value_length = 0;
    code = tlv_size_to_native(element.value.size, &value_length);
    if (code != TLV_OK) {
        PyBuffer_Release(&buffer);
        raise_code_only(code);
        return NULL;
    }
    Py_ssize_t value_offset =
        value_length == 0 ? 0 : (Py_ssize_t)((const uint8_t*)element.value.data - base);

    Py_ssize_t length_offset =
        source.length.size ? (Py_ssize_t)(source.data + source.length.offset - base) : 0;
    PyObject* tag_obj =
        PyBytes_FromStringAndSize((const char*)element.tag.data, (Py_ssize_t)element.tag.size);
    PyBuffer_Release(&buffer);
    if (tag_obj == NULL) {
        return NULL;
    }
    PyObject* consumed_obj = PyLong_FromSize_t(consumed);
    if (consumed_obj == NULL) {
        Py_DECREF(tag_obj);
        return NULL;
    }

    return Py_BuildValue("(NnnnnN)", tag_obj, length_offset, (Py_ssize_t)source.length.size,
                         value_offset, (Py_ssize_t)value_length, consumed_obj);
}

/* Copy an unvalidated range with the sequential Writer capacity/diagnostic contract. */
static PyObject* _opentlv_copy_encoded(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  buffer, encoded;
    Py_ssize_t offset;
    if (!PyArg_ParseTuple(args, "w*ny*", &buffer, &offset, &encoded)) return NULL;
    if (offset < 0 || offset > buffer.len) {
        PyBuffer_Release(&buffer);
        PyBuffer_Release(&encoded);
        PyErr_SetString(PyExc_ValueError, "offset is out of range for buffer");
        return NULL;
    }
    /* Raw copying deliberately does not use a Format. */
    tlv_writer_t writer = {NULL, (uint8_t*)buffer.buf, (size_t)buffer.len, (size_t)offset};
    tlv_writer_diagnostic_t diag;
    tlv_writer_diagnostic_init(&diag);
    tlv_result_t code = tlv_writer_copy_encoded_diag(&writer, (const uint8_t*)encoded.buf,
                                                     (size_t)encoded.len, &diag);
    PyBuffer_Release(&buffer);
    PyBuffer_Release(&encoded);
    if (code != TLV_OK) {
        raise_writer_error(code, &diag);
        return NULL;
    }
    return PyLong_FromSize_t(writer.pos - (size_t)offset);
}

/* write(buffer, offset, tag, value, format) -> written: int
 *
 * Encodes one element at `offset` in `buffer` using wire format `format` and
 * raises _opentlv.Error on failure, including insufficient capacity
 * (`code` 1, `required` set to the exact size needed). `buffer` must be a
 * writable buffer-protocol object (for example a bytearray); `tag` and
 * `value` may be any buffer-protocol object. */
static PyObject* _opentlv_write(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  buffer, tag_buf, value_buf;
    Py_ssize_t offset;
    int        format_id;
    if (!PyArg_ParseTuple(args, "w*ny*y*i", &buffer, &offset, &tag_buf, &value_buf, &format_id)) {
        return NULL;
    }
    const tlv_format_t* format = opentlv_python_format_for(format_id);
    if (format == NULL) {
        PyBuffer_Release(&buffer);
        PyBuffer_Release(&tag_buf);
        PyBuffer_Release(&value_buf);
        PyErr_SetString(PyExc_ValueError, "unknown format");
        return NULL;
    }
    if (offset < 0 || offset > buffer.len) {
        PyBuffer_Release(&buffer);
        PyBuffer_Release(&tag_buf);
        PyBuffer_Release(&value_buf);
        PyErr_SetString(PyExc_ValueError, "offset is out of range for buffer");
        return NULL;
    }

    tlv_tag_t               tag = tlv_tag((const uint8_t*)tag_buf.buf, (size_t)tag_buf.len);
    uint8_t*                dest = (uint8_t*)buffer.buf + offset;
    size_t                  capacity = (size_t)(buffer.len - offset);
    size_t                  written = 0;
    tlv_writer_diagnostic_t diag;
    tlv_writer_diagnostic_init(&diag);

    tlv_result_t code = tlv_write_diag(dest, capacity, format, tag, (const uint8_t*)value_buf.buf,
                                       (size_t)value_buf.len, &written, &diag);
    PyBuffer_Release(&tag_buf);
    PyBuffer_Release(&value_buf);
    PyBuffer_Release(&buffer);
    if (code != TLV_OK) {
        tlv_location_translate(&diag.diagnostic.location, (size_t)offset);
        raise_writer_error(code, &diag);
        return NULL;
    }
    return PyLong_FromSize_t(written);
}

/* encoded_size(tag, value_length, format) -> int
 *
 * Returns the encoded size of an element with `tag` and a value of
 * `value_length` bytes in wire format `format`, without writing anything.
 * Raises _opentlv.Error on failure. */
static PyObject* _opentlv_encoded_size(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  tag_buf;
    Py_ssize_t value_length;
    int        format_id;
    if (!PyArg_ParseTuple(args, "y*ni", &tag_buf, &value_length, &format_id)) {
        return NULL;
    }
    const tlv_format_t* format = opentlv_python_format_for(format_id);
    if (format == NULL) {
        PyBuffer_Release(&tag_buf);
        PyErr_SetString(PyExc_ValueError, "unknown format");
        return NULL;
    }
    if (value_length < 0) {
        PyBuffer_Release(&tag_buf);
        PyErr_SetString(PyExc_ValueError, "value_length must not be negative");
        return NULL;
    }

    tlv_tag_t    tag = tlv_tag((const uint8_t*)tag_buf.buf, (size_t)tag_buf.len);
    size_t       size = 0;
    tlv_result_t code = tlv_encoded_size(tag, (size_t)value_length, format, &size);
    PyBuffer_Release(&tag_buf);
    if (code != TLV_OK) {
        raise_code_only(code);
        return NULL;
    }
    return PyLong_FromSize_t(size);
}

static PyObject* _opentlv_element_encoded_size(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer tag_buf, value_buf;

    int format_id;
    if (!PyArg_ParseTuple(args, "y*y*i", &tag_buf, &value_buf, &format_id)) {
        return NULL;
    }
    const tlv_format_t* format = opentlv_python_format_for(format_id);
    if (format == NULL) {
        PyBuffer_Release(&tag_buf);
        PyBuffer_Release(&value_buf);
        PyErr_SetString(PyExc_ValueError, "unknown format");
        return NULL;
    }

    tlv_tag_t           tag = tlv_tag((const uint8_t*)tag_buf.buf, (size_t)tag_buf.len);
    size_t              size = 0;
    const tlv_element_t element = {tag, {(const uint8_t*)value_buf.buf, (tlv_size_t)value_buf.len}};
    tlv_writer_diagnostic_t diag;
    tlv_result_t            code = tlv_element_encoded_size_diag(&element, format, &size, &diag);
    if (code != TLV_OK) raise_writer_error(code, &diag);
    PyBuffer_Release(&tag_buf);
    PyBuffer_Release(&value_buf);
    if (code != TLV_OK) return NULL;
    return PyLong_FromSize_t(size);
}

/* Builds and validates a tlv_fixed_format_t from Python-parsed arguments.
 * Returns 1 on success; on failure a ValueError is set and *out is unusable. */
static int fixed_config_from_args(Py_ssize_t tag_size, Py_ssize_t length_size, int big_endian,
                                  tlv_fixed_format_t* out) {
    if (tag_size < 1) {
        PyErr_SetString(PyExc_ValueError, "tag_size must be at least 1");
        return 0;
    }
    if (length_size < 1 || length_size > 8) {
        PyErr_SetString(PyExc_ValueError, "length_size must be between 1 and 8");
        return 0;
    }
    out->identifier.size = (size_t)tag_size;
    out->length.size = (size_t)length_size;
    out->length.byte_order = big_endian ? TLV_BYTE_ORDER_BIG_ENDIAN : TLV_BYTE_ORDER_LITTLE_ENDIAN;
    out->element_order = TLV_ELEMENT_ORDER_TLV;
    out->length_scope = TLV_LENGTH_SCOPE_VALUE;
    return 1;
}

/* read_fixed(data, offset, tag_size, length_size, big_endian)
 *     -> (tag: bytes, length_offset: int, length_size: int, value_offset: int, value_length: int,
 * consumed: int)
 *
 * Like read(), but for the configurable fixed-width format: tag_size and
 * length_size are byte widths (length_size 1..8), and big_endian selects the
 * length field's byte order. Raises _opentlv.Error on failure. */
static PyObject* _opentlv_read_fixed(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  buffer;
    Py_ssize_t offset, tag_size, length_size;
    int        big_endian;
    if (!PyArg_ParseTuple(args, "y*nnnp", &buffer, &offset, &tag_size, &length_size, &big_endian)) {
        return NULL;
    }
    tlv_fixed_format_t config;
    if (!fixed_config_from_args(tag_size, length_size, big_endian, &config)) {
        PyBuffer_Release(&buffer);
        return NULL;
    }
    tlv_format_t format;
    tlv_result_t init_code = tlv_fixed_format_init(&format, &config);
    if (init_code != TLV_OK) {
        PyBuffer_Release(&buffer);
        raise_code_only(init_code);
        return NULL;
    }
    if (offset < 0 || offset > buffer.len) {
        PyBuffer_Release(&buffer);
        PyErr_SetString(PyExc_ValueError, "offset is out of range for data");
        return NULL;
    }

    const uint8_t*          base = (const uint8_t*)buffer.buf;
    size_t                  size = (size_t)(buffer.len - offset);
    tlv_element_t           element;
    size_t                  consumed = 0;
    tlv_reader_diagnostic_t diag;
    tlv_reader_diagnostic_init(&diag);

    tlv_source_t source;
    tlv_result_t code =
        tlv_read_source_diag(base + offset, size, &format, &element, &consumed, &source, &diag);
    if (code != TLV_OK) {
        raise_reader_error(code, &diag);
        PyBuffer_Release(&buffer);
        return NULL;
    }

    size_t value_length = 0;
    code = tlv_size_to_native(element.value.size, &value_length);
    if (code != TLV_OK) {
        PyBuffer_Release(&buffer);
        raise_code_only(code);
        return NULL;
    }
    Py_ssize_t value_offset =
        value_length == 0 ? 0 : (Py_ssize_t)((const uint8_t*)element.value.data - base);

    Py_ssize_t length_offset =
        source.length.size ? (Py_ssize_t)(source.data + source.length.offset - base) : 0;
    PyObject* tag_obj =
        PyBytes_FromStringAndSize((const char*)element.tag.data, (Py_ssize_t)element.tag.size);
    PyBuffer_Release(&buffer);
    if (tag_obj == NULL) {
        return NULL;
    }
    PyObject* consumed_obj = PyLong_FromSize_t(consumed);
    if (consumed_obj == NULL) {
        Py_DECREF(tag_obj);
        return NULL;
    }

    return Py_BuildValue("(NnnnnN)", tag_obj, length_offset, (Py_ssize_t)source.length.size,
                         value_offset, (Py_ssize_t)value_length, consumed_obj);
}

/* write_fixed(buffer, offset, tag, value, tag_size, length_size, big_endian) -> written: int
 *
 * Like write(), but for the configurable fixed-width format. Raises
 * _opentlv.Error on failure, including insufficient capacity. */
static PyObject* _opentlv_write_fixed(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  buffer, tag_buf, value_buf;
    Py_ssize_t offset, tag_size, length_size;
    int        big_endian;
    if (!PyArg_ParseTuple(args, "w*ny*y*nnp", &buffer, &offset, &tag_buf, &value_buf, &tag_size,
                          &length_size, &big_endian)) {
        return NULL;
    }
    tlv_fixed_format_t config;
    if (!fixed_config_from_args(tag_size, length_size, big_endian, &config)) {
        PyBuffer_Release(&buffer);
        PyBuffer_Release(&tag_buf);
        PyBuffer_Release(&value_buf);
        return NULL;
    }
    tlv_format_t format;
    tlv_result_t init_code = tlv_fixed_format_init(&format, &config);
    if (init_code != TLV_OK) {
        PyBuffer_Release(&buffer);
        PyBuffer_Release(&tag_buf);
        PyBuffer_Release(&value_buf);
        raise_code_only(init_code);
        return NULL;
    }
    if (offset < 0 || offset > buffer.len) {
        PyBuffer_Release(&buffer);
        PyBuffer_Release(&tag_buf);
        PyBuffer_Release(&value_buf);
        PyErr_SetString(PyExc_ValueError, "offset is out of range for buffer");
        return NULL;
    }

    tlv_tag_t               tag = tlv_tag((const uint8_t*)tag_buf.buf, (size_t)tag_buf.len);
    uint8_t*                dest = (uint8_t*)buffer.buf + offset;
    size_t                  capacity = (size_t)(buffer.len - offset);
    size_t                  written = 0;
    tlv_writer_diagnostic_t diag;
    tlv_writer_diagnostic_init(&diag);

    tlv_result_t code = tlv_write_diag(dest, capacity, &format, tag, (const uint8_t*)value_buf.buf,
                                       (size_t)value_buf.len, &written, &diag);
    PyBuffer_Release(&tag_buf);
    PyBuffer_Release(&value_buf);
    PyBuffer_Release(&buffer);
    if (code != TLV_OK) {
        tlv_location_translate(&diag.diagnostic.location, (size_t)offset);
        raise_writer_error(code, &diag);
        return NULL;
    }
    return PyLong_FromSize_t(written);
}

/* encoded_size_fixed(tag, value_length, tag_size, length_size, big_endian) -> int
 *
 * Like encoded_size(), but for the configurable fixed-width format. Raises
 * _opentlv.Error on failure. */
static PyObject* _opentlv_encoded_size_fixed(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  tag_buf;
    Py_ssize_t value_length, tag_size, length_size;
    int        big_endian;
    if (!PyArg_ParseTuple(args, "y*nnnp", &tag_buf, &value_length, &tag_size, &length_size,
                          &big_endian)) {
        return NULL;
    }
    tlv_fixed_format_t config;
    if (!fixed_config_from_args(tag_size, length_size, big_endian, &config)) {
        PyBuffer_Release(&tag_buf);
        return NULL;
    }
    tlv_format_t format;
    tlv_result_t init_code = tlv_fixed_format_init(&format, &config);
    if (init_code != TLV_OK) {
        PyBuffer_Release(&tag_buf);
        raise_code_only(init_code);
        return NULL;
    }
    if (value_length < 0) {
        PyBuffer_Release(&tag_buf);
        PyErr_SetString(PyExc_ValueError, "value_length must not be negative");
        return NULL;
    }

    tlv_tag_t    tag = tlv_tag((const uint8_t*)tag_buf.buf, (size_t)tag_buf.len);
    size_t       size = 0;
    tlv_result_t code = tlv_encoded_size(tag, (size_t)value_length, &format, &size);
    PyBuffer_Release(&tag_buf);
    if (code != TLV_OK) {
        raise_code_only(code);
        return NULL;
    }
    return PyLong_FromSize_t(size);
}

static PyObject* _opentlv_element_encoded_size_fixed(PyObject* module, PyObject* args) {
    (void)module;
    Py_buffer  tag_buf, value_buf;
    Py_ssize_t tag_size, length_size;
    int        big_endian;
    if (!PyArg_ParseTuple(args, "y*y*nnp", &tag_buf, &value_buf, &tag_size, &length_size,
                          &big_endian)) {
        return NULL;
    }
    tlv_fixed_format_t config;
    if (!fixed_config_from_args(tag_size, length_size, big_endian, &config)) {
        PyBuffer_Release(&tag_buf);
        PyBuffer_Release(&value_buf);
        return NULL;
    }
    tlv_format_t format;
    tlv_result_t init_code = tlv_fixed_format_init(&format, &config);
    if (init_code != TLV_OK) {
        PyBuffer_Release(&tag_buf);
        PyBuffer_Release(&value_buf);
        raise_code_only(init_code);
        return NULL;
    }

    tlv_tag_t           tag = tlv_tag((const uint8_t*)tag_buf.buf, (size_t)tag_buf.len);
    size_t              size = 0;
    const tlv_element_t element = {tag, {(const uint8_t*)value_buf.buf, (tlv_size_t)value_buf.len}};
    tlv_writer_diagnostic_t diag;
    tlv_result_t            code = tlv_element_encoded_size_diag(&element, &format, &size, &diag);
    if (code != TLV_OK) raise_writer_error(code, &diag);
    PyBuffer_Release(&tag_buf);
    PyBuffer_Release(&value_buf);
    if (code != TLV_OK) return NULL;
    return PyLong_FromSize_t(size);
}

void opentlv_python_raise_reader(tlv_result_t code, const tlv_reader_diagnostic_t* diagnostic) {
    raise_reader_error(code, diagnostic);
}

void opentlv_python_raise_result(tlv_result_t code) {
    raise_code_only(code);
}

void opentlv_python_raise_writer(tlv_result_t code, const tlv_writer_diagnostic_t* diagnostic) {
    raise_writer_error(code, diagnostic);
}

static PyObject* diagnostic_name(PyObject* module, PyObject* args) {
    (void)module;
    const char* category;
    int         value;
    if (!PyArg_ParseTuple(args, "si", &category, &value)) return NULL;
    if (!strcmp(category, "reader_operation"))
        return PyUnicode_FromString(tlv_reader_operation_string((tlv_reader_operation_t)value));
    if (!strcmp(category, "writer_operation"))
        return PyUnicode_FromString(tlv_writer_operation_string((tlv_writer_operation_t)value));
    if (!strcmp(category, "query_error_kind"))
        return PyUnicode_FromString(tlv_query_error_kind_string((tlv_query_error_kind_t)value));
    if (!strcmp(category, "codec_reason"))
        return PyUnicode_FromString(tlv_codec_reason_string((tlv_codec_reason_t)value));
    if (!strcmp(category, "schema_cause"))
        return PyUnicode_FromString(tlv_schema_cause_string((tlv_schema_cause_t)value));
    if (!strcmp(category, "query_cause"))
        return PyUnicode_FromString(tlv_query_cause_string((tlv_query_cause_t)value));
    if (!strcmp(category, "schema_issue_kind"))
        return PyUnicode_FromString(tlv_schema_issue_kind_string((tlv_schema_issue_kind_t)value));
    if (!strcmp(category, "schema_definition_kind"))
        return PyUnicode_FromString(
            tlv_schema_definition_kind_string((tlv_schema_definition_kind_t)value));
    if (!strcmp(category, "codec_operation"))
        return PyUnicode_FromString(tlv_codec_operation_string((tlv_codec_operation_t)value));
    if (!strcmp(category, "codec_cause"))
        return PyUnicode_FromString(tlv_codec_cause_string((tlv_codec_cause_t)value));
    if (!strcmp(category, "codec_violation"))
        return PyUnicode_FromString(tlv_codec_violation_string((tlv_codec_violation_t)value));
    if (!strcmp(category, "diagnostic_severity"))
        return PyUnicode_FromString(
            tlv_diagnostic_severity_string((tlv_diagnostic_severity_t)value));
    PyErr_SetString(PyExc_ValueError, "unknown diagnostic category");
    return NULL;
}

static PyMethodDef opentlv_python_methods[] = {
    {"diagnostic_name", diagnostic_name, METH_VARARGS, "Canonical C diagnostic category label."},
    {"node_identity", _opentlv_node_identity, METH_VARARGS,
     "Read checked traversal-independent node identity."},
    {"query_emv_resolve", opentlv_python_query_emv_resolve, METH_VARARGS,
     "Resolve canonical EMV Query names."},
    {"query_definition_resolve", opentlv_python_query_definition_resolve, METH_VARARGS,
     "Resolve a scoped Definition name through the canonical C adapter."},
    {"program_create", opentlv_python_program_create, METH_VARARGS,
     "Compile or validate an owned immutable Query image."},
    {"program_info", opentlv_python_program_info, METH_O, "Inspect compiled Query requirements."},
    {"program_render", opentlv_python_program_render, METH_VARARGS,
     "Format, explain or copy a compiled image."},
    {"execution_create", opentlv_python_execution_create, METH_VARARGS,
     "Create independent bounded execution."},
    {"execution_size", opentlv_python_execution_size, METH_VARARGS,
     "Discover caller workspace size and alignment."},
    {"execution_feed", opentlv_python_execution_feed, METH_VARARGS,
     "Feed a pinned complete canonical event."},
    {"execution_finish", opentlv_python_execution_finish, METH_O,
     "Finish balanced canonical events."},
    {"execution_bind", opentlv_python_execution_bind, METH_VARARGS,
     "Bind a typed variable with pinned storage."},
    {"execution_visit", opentlv_python_execution_visit, METH_VARARGS,
     "Visit or test existence through a TreeReader."},
    {"execution_info", opentlv_python_execution_info, METH_O,
     "Read execution counters and coverage."},
    {"execution_result", opentlv_python_execution_result, METH_O, "Copy a finalized scalar."},
    {"execution_control", opentlv_python_execution_control, METH_VARARGS,
     "Select context or explicit pruning."},
    {"execution_document", opentlv_python_execution_document, METH_VARARGS,
     "Evaluate a bounded Document snapshot."},
    {"execution_edit", opentlv_python_execution_edit, METH_VARARGS,
     "Edit a finalized Document selection through C."},
    {"query_schema", opentlv_python_query_schema, METH_VARARGS,
     "Validate contextual compiled Query assertions through C."},
    {"execution_next_ordinal", opentlv_python_execution_next_ordinal, METH_O,
     "Pull a finalized owned event with its native traversal ordinal."},
    {"execution_next", opentlv_python_execution_next, METH_O,
     "Pull a finalized node with native revision checks."},
    {"length_schema", opentlv_python_length_schema, METH_VARARGS,
     "Find or validate a length rule through the canonical C schema engine."},
    {"source_preserve", opentlv_python_source_preserve, METH_VARARGS,
     "Preserve retained immutable source bytes after C semantic equality checks."},
    {"document_builder_create", opentlv_python_builder_create, METH_VARARGS,
     "Materialize a whole stream or next subtree through the C builder."},
    {"document_builder_consume", opentlv_python_builder_consume, METH_O,
     "Resume materialization and transfer a completed document."},
    {"tree_writer_measure", opentlv_python_tree_writer_measure, METH_VARARGS,
     "Measure and stage a preorder source through C."},
    {"tree_writer_create", opentlv_python_tree_writer_create, METH_VARARGS,
     "Create bounded canonical tree output."},
    {"tree_writer_action", opentlv_python_tree_writer_action, METH_VARARGS,
     "Operate the canonical C Tree Writer."},
    {"cursor_create", opentlv_python_cursor_create, METH_VARARGS,
     "Create a canonical C Reader cursor."},
    {"cursor_event", opentlv_python_cursor_event, METH_O, "Pull a structural tree event."},
    {"tree_writer_tags", opentlv_python_tree_writer_tags, METH_VARARGS,
     "Configure bounded Tag storage."},
    {"tree_writer_event", opentlv_python_tree_writer_event, METH_VARARGS,
     "Consume a structural event."},
    {"cursor_next", opentlv_python_cursor_next, METH_O, "Pull complete content and source ranges."},
    {"cursor_input", opentlv_python_cursor_input, METH_VARARGS, "Replace a cursor input window."},
    {"cursor_status", opentlv_python_cursor_status, METH_O,
     "Return consumed bytes, absolute offset and final exhaustion."},
    {"cursor_skip", opentlv_python_cursor_skip, METH_O, "Skip the pending subtree."},
    {"cursor_visit", opentlv_python_cursor_visit, METH_VARARGS,
     "Visit through the C traversal engine."},
    {"query_create", opentlv_python_query_create, METH_O, "Parse or copy a canonical Query."},
    {"query_steps", opentlv_python_query_steps, METH_O, "Return query path tags."},
    {"query_rebind", opentlv_python_query_rebind, METH_VARARGS, "Reset or rebind V1 matcher."},
    {"query_matches", opentlv_python_query_matches, METH_VARARGS,
     "Feed a preorder item to the C matcher."},
    {"query_visit", opentlv_python_query_visit, METH_VARARGS,
     "Visit matches through the C Query engine."},
    {"version_string", _opentlv_version_string, METH_NOARGS,
     "Return the version of the linked OpenTLV C library, for example \"0.6.0\"."},
    {"result_string", _opentlv_result_string, METH_VARARGS,
     "Return the readable description of a tlv_result_t code."},
    {"read", _opentlv_read, METH_VARARGS,
     "Parse one element at an offset in a buffer using a wire format."},
    {"write", _opentlv_write, METH_VARARGS,
     "Encode one element at an offset in a writable buffer using a wire format."},
    {"copy_encoded", _opentlv_copy_encoded, METH_VARARGS,
     "Copy raw bytes into caller storage without format conversion."},
    {"element_encoded_size", _opentlv_element_encoded_size, METH_VARARGS,
     "Measure exact output storage using semantic content."},
    {"element_encoded_size_fixed", _opentlv_element_encoded_size_fixed, METH_VARARGS,
     "Measure exact output storage for a fixed format Element."},
    {"encoded_size", _opentlv_encoded_size, METH_VARARGS,
     "Compute the encoded size of an element without writing it."},
    {"read_fixed", _opentlv_read_fixed, METH_VARARGS,
     "Parse one element at an offset in a buffer using the configurable fixed-width format."},
    {"write_fixed", _opentlv_write_fixed, METH_VARARGS,
     "Encode one element at an offset in a writable buffer using the configurable "
     "fixed-width format."},
    {"encoded_size_fixed", _opentlv_encoded_size_fixed, METH_VARARGS,
     "Compute the encoded size of an element in the configurable fixed-width format."},
    {"structure_validate", _opentlv_structure_validate, METH_VARARGS,
     "Validate a buffer against a serialized structural schema."},
    {"definition_find", _opentlv_definition_find, METH_VARARGS,
     "Find the first generic C Definition."},
    {"number_codec", _opentlv_number_codec, METH_VARARGS, "Configured C numeric Value codec."},
#if OPENTLV_EMV
    {"emv_decode_amount", _opentlv_emv_decode_amount, METH_VARARGS,
     "Decode 6 bytes of BCD (EMV format n12) into an unscaled minor-unit amount."},
    {"emv_encode_amount", _opentlv_emv_encode_amount, METH_VARARGS,
     "Encode an unscaled minor-unit amount as 6 bytes of BCD (EMV format n12)."},
#endif
    {"document_create", _opentlv_document_create, METH_VARARGS, "Create an empty document."},
    {"document_parse", _opentlv_document_parse, METH_VARARGS,
     "Parse a buffer into a new owned document."},
    {"document_count", _opentlv_document_count, METH_VARARGS,
     "Return the number of elements in a document, including nested ones."},
    {"document_first", _opentlv_document_first, METH_VARARGS,
     "Return the first top-level node of a document, or None."},
    {"document_find", _opentlv_document_find, METH_VARARGS,
     "Find the first direct child of a node (or the top level) with a tag."},
    {"document_find_path", _opentlv_document_find_path, METH_VARARGS,
     "Find the first element addressed by a path query, for example \"6F/A5/50\"."},
    {"document_insert", _opentlv_document_insert, METH_VARARGS,
     "Insert a new element into a document and return its node."},
    {"document_encoded_size", _opentlv_document_encoded_size, METH_VARARGS,
     "Compute the encoded size of a whole document."},
    {"document_encode", _opentlv_document_encode, METH_VARARGS, "Encode a whole document."},
    {"node_first_child", _opentlv_node_first_child, METH_VARARGS,
     "Return the first child of a constructed node, or None."},
    {"node_next", _opentlv_node_next, METH_VARARGS, "Return the next sibling of a node, or None."},
    {"node_parent", _opentlv_node_parent, METH_VARARGS,
     "Return the parent of a node, or None for a top-level node."},
    {"node_next_same_tag", _opentlv_node_next_same_tag, METH_VARARGS,
     "Return the next sibling with the same tag as a node, or None."},
    {"node_tag", _opentlv_node_tag, METH_VARARGS, "Return the tag of a node."},
    {"node_is_constructed", _opentlv_node_is_constructed, METH_VARARGS,
     "Return whether a node's value holds nested elements."},
    {"node_value", _opentlv_node_value, METH_VARARGS,
     "Return the value bytes of a node (empty for a constructed node)."},
    {"node_set_value", _opentlv_node_set_value, METH_VARARGS, "Replace the value of a node."},
    {"node_erase", _opentlv_node_erase, METH_VARARGS,
     "Remove a node and all of its descendants from its document."},
    {"node_encoded_size", _opentlv_node_encoded_size, METH_VARARGS,
     "Compute the encoded size of one element with its descendants."},
    {"node_encode", _opentlv_node_encode, METH_VARARGS, "Encode one element with its descendants."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef opentlv_python_module = {
    PyModuleDef_HEAD_INIT,
    "_opentlv",
    "Raw declarations of the OpenTLV C API, registered directly as Python callables. "
    "Low-level; use the opentlv package instead.",
    -1,
    opentlv_python_methods,
};

PyMODINIT_FUNC PyInit__opentlv(void) {
    PyObject* module = PyModule_Create(&opentlv_python_module);
    if (module == NULL) {
        return NULL;
    }
    if (opentlv_python_register_formats(module) < 0) {
        Py_DECREF(module);
        return NULL;
    }
    /* Result codes come from tlv/result.h, so Python never hard-codes their numbers. */
    {
        static const struct {
            const char*  name;
            tlv_result_t value;
        } results[] = {
            {"RESULT_OK", TLV_OK},
            {"RESULT_END", TLV_END},
            {"RESULT_NEED_MORE_DATA", TLV_NEED_MORE_DATA},
            {"RESULT_TRUNCATED", TLV_ERR_TRUNCATED},
            {"RESULT_BUFFER_TOO_SHORT", TLV_ERR_BUFFER_TOO_SHORT},
            {"RESULT_INVALID_LENGTH", TLV_ERR_INVALID_LENGTH},
            {"RESULT_NULL_ARG", TLV_ERR_NULL_ARG},
            {"RESULT_OUT_OF_MEMORY", TLV_ERR_OUT_OF_MEMORY},
            {"RESULT_INVALID_TAG", TLV_ERR_INVALID_TAG},
            {"RESULT_VISITOR", TLV_ERR_VISITOR},
            {"RESULT_LIMIT", TLV_ERR_LIMIT},
            {"RESULT_SCHEMA", TLV_ERR_SCHEMA},
            {"RESULT_INVALID_ARG", TLV_ERR_INVALID_ARG},
            {"RESULT_INVALID_TAG_SIZE", TLV_ERR_INVALID_TAG_SIZE},
            {"RESULT_SYNTAX", TLV_ERR_SYNTAX},
            {"RESULT_OVERFLOW", TLV_ERR_OVERFLOW},
            {"RESULT_INVALID_VALUE", TLV_ERR_INVALID_VALUE},
            {"RESULT_UNSUPPORTED", TLV_ERR_UNSUPPORTED},
            {"RESULT_INVALID_SCHEMA", TLV_ERR_INVALID_SCHEMA},
            {"RESULT_NATIVE_SIZE", TLV_ERR_NATIVE_SIZE},
            {"RESULT_INVALID_STATE", TLV_ERR_INVALID_STATE},
            {"RESULT_CALLBACK", TLV_ERR_CALLBACK},
        };
        for (size_t i = 0; i < sizeof results / sizeof results[0]; ++i) {
            if (PyModule_AddIntConstant(module, results[i].name, (long)results[i].value) < 0) {
                Py_DECREF(module);
                return NULL;
            }
        }
    }

    /* Raised with a single dict argument carrying "code" and whichever
     * diagnostic keys the failing call supports; see raise_error() above.
     * Internal transport to the opentlv package, which maps it to a typed,
     * documented exception. */
    opentlv_python_error = PyErr_NewException("_opentlv.Error", NULL, NULL);
    if (opentlv_python_error == NULL) {
        Py_DECREF(module);
        return NULL;
    }
    if (PyModule_AddObjectRef(module, "Error", opentlv_python_error) < 0) {
        Py_DECREF(module);
        return NULL;
    }

    /* Raised with a single int argument: the tlv_result_t code. */

    return module;
}
