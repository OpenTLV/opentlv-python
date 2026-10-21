// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#include "writer.h"
#include "format.h"
#include <tlv/formats/fixed.h>
#include <tlv/writer/tree.h>
#include <stdlib.h>

#define WRITER_NAME "opentlv.tree_writer"
typedef struct writer_state {
    tlv_tree_writer_t        writer;
    tlv_format_t             format;
    tlv_fixed_format_t       fixed;
    tlv_tree_writer_frame_t* frames;
    uint8_t *                data, *scratch;
    uint8_t*                 tag_storage;
    PyObject**               tags;
    size_t                   depth;
    int                      busy;
} writer_state;

static void release_writer(writer_state* self) {
    for (size_t i = 0; i < self->depth; ++i) Py_DECREF(self->tags[i]);
    free(self->tags);
    free(self->frames);
    free(self->data);
    free(self->scratch);
    free(self->tag_storage);
    free(self);
}
static void destroy_writer(PyObject* capsule) {
    writer_state* self = PyCapsule_GetPointer(capsule, WRITER_NAME);
    if (self) release_writer(self);
}

PyObject* opentlv_python_tree_writer_create(PyObject* module, PyObject* args) {
    (void)module;
    int        format_id, big_endian;
    Py_ssize_t size, scratch, frames, depth, count, tag_size, length_size;
    if (!PyArg_ParseTuple(args, "innnnnnnp", &format_id, &size, &scratch, &frames, &depth, &count,
                          &tag_size, &length_size, &big_endian))
        return NULL;
    if (size < 0 || scratch < 0 || frames < 0 || depth < 0 || count < 0 ||
        (size_t)frames > SIZE_MAX / sizeof(tlv_tree_writer_frame_t) ||
        (size_t)frames > SIZE_MAX / sizeof(PyObject*)) {
        PyErr_SetString(PyExc_ValueError, "nonnegative bounded capacities required");
        return NULL;
    }
    writer_state* self = calloc(1, sizeof(*self));
    if (!self) return PyErr_NoMemory();
    tlv_result_t code = TLV_OK;
    if (format_id == -1) {
        if (tag_size < 1 || length_size < 1 || length_size > 8)
            code = TLV_ERR_INVALID_ARG;
        else {
            self->fixed.identifier.size = (size_t)tag_size;
            self->fixed.length.size = (size_t)length_size;
            self->fixed.length.byte_order =
                big_endian ? TLV_BYTE_ORDER_BIG_ENDIAN : TLV_BYTE_ORDER_LITTLE_ENDIAN;
            self->fixed.element_order = TLV_ELEMENT_ORDER_TLV;
            self->fixed.length_scope = TLV_LENGTH_SCOPE_VALUE;
            code = tlv_fixed_format_init(&self->format, &self->fixed);
        }
    } else {
        const tlv_format_t* format = opentlv_python_format_for(format_id);
        if (!format)
            code = TLV_ERR_INVALID_ARG;
        else
            self->format = *format;
    }
    if (code != TLV_OK) {
        release_writer(self);
        opentlv_python_raise_writer(code, NULL);
        return NULL;
    }
    self->data = size ? malloc((size_t)size) : NULL;
    self->scratch = scratch ? malloc((size_t)scratch) : NULL;
    self->frames = frames ? calloc((size_t)frames, sizeof(*self->frames)) : NULL;
    self->tags = frames ? calloc((size_t)frames, sizeof(*self->tags)) : NULL;
    if ((size && !self->data) || (scratch && !self->scratch) ||
        (frames && (!self->frames || !self->tags))) {
        release_writer(self);
        return PyErr_NoMemory();
    }
    code = tlv_tree_writer_init(&self->writer, self->data, (size_t)size, &self->format,
                                self->frames, (size_t)frames, self->scratch, (size_t)scratch,
                                (size_t)depth, (size_t)count);
    if (code != TLV_OK) {
        release_writer(self);
        opentlv_python_raise_writer(code, NULL);
        return NULL;
    }
    PyObject* capsule = PyCapsule_New(self, WRITER_NAME, destroy_writer);
    if (!capsule) release_writer(self);
    return capsule;
}

PyObject* opentlv_python_tree_writer_action(PyObject* module, PyObject* args) {
    (void)module;
    PyObject *capsule, *tag = Py_None, *value = Py_None;
    int       action;
    if (!PyArg_ParseTuple(args, "Oi|OO", &capsule, &action, &tag, &value)) return NULL;
    writer_state* self = PyCapsule_GetPointer(capsule, WRITER_NAME);
    if (!self) return NULL;
    if (self->busy) {
        PyErr_SetString(PyExc_RuntimeError, "Tree Writer is in a measurement callback");
        return NULL;
    }
    tlv_result_t            code = TLV_OK;
    tlv_writer_diagnostic_t diag;
    tlv_writer_diagnostic_init(&diag);
    if (action == 0 || action == 1) {
        if (!PyBytes_Check(tag) || (action == 1 && !PyBytes_Check(value))) {
            PyErr_SetString(PyExc_TypeError, "immutable tag and value bytes required");
            return NULL;
        }
        tlv_tag_t raw_tag =
            tlv_tag((const uint8_t*)PyBytes_AsString(tag), (size_t)PyBytes_Size(tag));
        if (action == 0) {
            code = tlv_tree_writer_begin_diag(&self->writer, raw_tag, &diag);
            if (code == TLV_OK) self->tags[self->depth++] = Py_NewRef(tag);
        } else {
            tlv_element_t element = {
                raw_tag,
                {(const uint8_t*)PyBytes_AsString(value), (tlv_size_t)PyBytes_Size(value)}};
            code = tlv_tree_writer_write_element_diag(&self->writer, &element, &diag);
        }
    } else if (action == 2) {
        code = tlv_tree_writer_end_diag(&self->writer, &diag);
        if (code == TLV_OK) Py_DECREF(self->tags[--self->depth]);
    } else if (action == 3) {
        code = tlv_tree_writer_finish(&self->writer);
    } else if (action != 4) {
        PyErr_SetString(PyExc_ValueError, "invalid Tree Writer operation");
        return NULL;
    }
    if (code != TLV_OK) {
        opentlv_python_raise_writer(code, &diag);
        return NULL;
    }
    if (action >= 3)
        return PyBytes_FromStringAndSize((const char*)self->data,
                                         (Py_ssize_t)tlv_tree_writer_size(&self->writer));
    return Py_NewRef(Py_None);
}

PyObject* opentlv_python_tree_writer_tags(PyObject* module, PyObject* args) {
    (void)module;
    PyObject*  capsule;
    Py_ssize_t capacity;
    if (!PyArg_ParseTuple(args, "On", &capsule, &capacity)) return NULL;
    writer_state* self = PyCapsule_GetPointer(capsule, WRITER_NAME);
    if (!self) return NULL;
    if (self->busy || capacity < -1) {
        PyErr_SetString(PyExc_ValueError, "invalid Tag storage configuration");
        return NULL;
    }
    uint8_t* storage = capacity < 0 ? NULL : malloc(capacity ? (size_t)capacity : 1);
    if (capacity >= 0 && !storage) return PyErr_NoMemory();
    tlv_result_t code = tlv_tree_writer_set_tag_storage(&self->writer, storage,
                                                        capacity < 0 ? 0 : (size_t)capacity);
    if (code != TLV_OK) {
        free(storage);
        opentlv_python_raise_writer(code, NULL);
        return NULL;
    }
    free(self->tag_storage);
    self->tag_storage = storage;
    return Py_NewRef(Py_None);
}

PyObject* opentlv_python_tree_writer_event(PyObject* module, PyObject* args) {
    (void)module;
    PyObject * capsule, *tag, *value;
    int        kind, skipped;
    Py_ssize_t depth;
    if (!PyArg_ParseTuple(args, "OinOOp", &capsule, &kind, &depth, &tag, &value, &skipped))
        return NULL;
    writer_state* self = PyCapsule_GetPointer(capsule, WRITER_NAME);
    if (!self) return NULL;
    if (self->busy) {
        PyErr_SetString(PyExc_RuntimeError, "Tree Writer is busy");
        return NULL;
    }
    if (depth < 0 || !PyBytes_Check(tag) || !PyBytes_Check(value)) {
        PyErr_SetString(PyExc_ValueError, "nonnegative depth and immutable bytes required");
        return NULL;
    }
    tlv_tree_event_t event = {0};
    event.kind = (tlv_tree_event_kind_t)kind;
    event.depth = (size_t)depth;
    event.skipped = skipped;
    event.element.tag = tlv_tag((const uint8_t*)PyBytes_AsString(tag), (size_t)PyBytes_Size(tag));
    event.element.value =
        (tlv_value_t){(const uint8_t*)PyBytes_AsString(value), (tlv_size_t)PyBytes_Size(value)};
    tlv_writer_diagnostic_t diag;
    tlv_writer_diagnostic_init(&diag);
    tlv_result_t code = tlv_tree_writer_write_event_diag(&self->writer, &event, &diag);
    if (code != TLV_OK) {
        opentlv_python_raise_writer(code, &diag);
        return NULL;
    }
    if (kind == TLV_TREE_BEGIN) self->tags[self->depth++] = Py_NewRef(tag);
    if (kind == TLV_TREE_END) Py_DECREF(self->tags[--self->depth]);
    return Py_NewRef(Py_None);
}

typedef struct measure_source {
    PyObject* iterator;
    PyObject* retained;
} measure_source;

static tlv_result_t measure_next(void* context, tlv_element_t* element, size_t* depth,
                                 int* constructed) {
    measure_source* source = context;
    PyObject*       item = PyIter_Next(source->iterator);
    if (!item) return PyErr_Occurred() ? TLV_ERR_INVALID_ARG : TLV_END;
    PyObject * tag, *value;
    Py_ssize_t item_depth;
    if (!PyArg_ParseTuple(item, "OOnp", &tag, &value, &item_depth, constructed)) {
        Py_DECREF(item);
        return TLV_ERR_INVALID_ARG;
    }
    if (!PyBytes_Check(tag) || !PyBytes_Check(value) || item_depth < 0) {
        PyErr_SetString(PyExc_ValueError, "immutable bytes and nonnegative depth required");
        Py_DECREF(item);
        return TLV_ERR_INVALID_ARG;
    }
    /* C retains parent Tags. Retain all supplied immutable records until return,
     * including when a later callback fails and diagnostics reference a Tag. */
    if (PyList_Append(source->retained, item) < 0) {
        Py_DECREF(item);
        return TLV_ERR_OUT_OF_MEMORY;
    }
    element->tag = tlv_tag((const uint8_t*)PyBytes_AsString(tag), (size_t)PyBytes_Size(tag));
    element->value.data = (const uint8_t*)PyBytes_AsString(value);
    element->value.size = (tlv_size_t)PyBytes_Size(value);
    *depth = (size_t)item_depth;
    Py_DECREF(item);
    return TLV_OK;
}

static tlv_result_t measure_event_next(void* context, tlv_tree_event_t* event) {
    measure_source* source = context;
    PyObject*       item = PyIter_Next(source->iterator);
    if (!item) return PyErr_Occurred() ? TLV_ERR_INVALID_ARG : TLV_END;
    PyObject * tag, *value;
    Py_ssize_t depth;
    int        kind, skipped;
    if (!PyArg_ParseTuple(item, "inOOp", &kind, &depth, &tag, &value, &skipped)) {
        Py_DECREF(item);
        return TLV_ERR_INVALID_ARG;
    }
    if (depth < 0 || !PyBytes_Check(tag) || !PyBytes_Check(value)) {
        Py_DECREF(item);
        return TLV_ERR_INVALID_ARG;
    }
    if (PyList_Append(source->retained, item) < 0) {
        Py_DECREF(item);
        return TLV_ERR_OUT_OF_MEMORY;
    }
    *event = (tlv_tree_event_t){0};
    event->kind = (tlv_tree_event_kind_t)kind;
    event->depth = (size_t)depth;
    event->skipped = skipped;
    event->element.tag = tlv_tag((const uint8_t*)PyBytes_AsString(tag), (size_t)PyBytes_Size(tag));
    event->element.value =
        (tlv_value_t){(const uint8_t*)PyBytes_AsString(value), (tlv_size_t)PyBytes_Size(value)};
    Py_DECREF(item);
    return TLV_OK;
}

PyObject* opentlv_python_tree_writer_measure(PyObject* module, PyObject* args) {
    (void)module;
    PyObject *capsule, *items;
    int       events = 0;
    if (!PyArg_ParseTuple(args, "OO|p", &capsule, &items, &events)) return NULL;
    writer_state* self = PyCapsule_GetPointer(capsule, WRITER_NAME);
    if (!self) return NULL;
    if (self->busy || self->writer.count) {
        PyErr_SetString(PyExc_ValueError, "measurement requires an unused Tree Writer");
        return NULL;
    }
    self->busy = 1;
    measure_source source = {PyObject_GetIter(items), NULL};
    if (source.iterator) source.retained = PyList_New(0);
    if (!source.iterator || !source.retained) {
        Py_XDECREF(source.iterator);
        self->busy = 0;
        return NULL;
    }
    tlv_tree_writer_workspace_t workspace = {
        self->frames,  self->writer.capacity,         self->data, self->writer.output.capacity,
        self->scratch, self->writer.scratch_capacity, 0,          0};
    tlv_writer_diagnostic_t diagnostic;
    tlv_writer_diagnostic_init(&diagnostic);
    size_t       size = 0;
    tlv_result_t code =
        events ? tlv_tree_writer_measure_events(&self->format, measure_event_next, &source,
                                                &workspace, self->writer.max_depth,
                                                self->writer.max_elements, &size, &diagnostic)
               : tlv_tree_writer_measure(&self->format, measure_next, &source, &workspace,
                                         self->writer.max_depth, self->writer.max_elements, &size,
                                         &diagnostic);
    PyObject* result = NULL;
    if (!PyErr_Occurred()) {
        if (code == TLV_OK) {
            result = PyBytes_FromStringAndSize((const char*)self->data, (Py_ssize_t)size);
        } else {
            opentlv_python_raise_writer(code, &diagnostic);
            PyObject *type, *error, *traceback;
            PyErr_Fetch(&type, &error, &traceback);
            PyErr_NormalizeException(&type, &error, &traceback);
            PyObject* data = PyLong_FromSize_t(workspace.required_data);
            PyObject* scratch = PyLong_FromSize_t(workspace.required_scratch);
            if (error && data && scratch) {
                if (PyObject_SetAttrString(error, "required_data", data) < 0 ||
                    PyObject_SetAttrString(error, "required_scratch", scratch) < 0)
                    PyErr_Clear();
            }
            Py_XDECREF(data);
            Py_XDECREF(scratch);
            PyErr_Restore(type, error, traceback);
        }
    }
    Py_DECREF(source.retained);
    Py_DECREF(source.iterator);
    self->busy = 0;
    return result;
}
