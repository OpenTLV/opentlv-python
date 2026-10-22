// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#define PY_SSIZE_T_CLEAN
#include "format.h"
#include "reader.h"
#include <tlv/formats/escaped.h>
#include <tlv/formats/fixed.h>
#include <tlv/formats/packed.h>
#include <tlv/formats/variable.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define COMPOSED_CAPSULE "opentlv.ComposedFormat"
/* Field encoding kinds; match the first item of opentlv.field native tuples. */
enum { FIELD_FIXED = 0, FIELD_VARIABLE = 1, FIELD_ESCAPED = 2 };
/* Specification kinds; match opentlv.composed_format. */
enum { COMPOSE_FIELDS = 0, COMPOSE_PACKED = 1 };
/* Packed identifier tables hold 2^width entries; wider fields would need
 * multi-megabyte tables. */
#define PACKED_TAG_MAX_WIDTH 16

/* Owns one descriptor, its immutable configuration and every borrowed table.
 * Core borrows config, field encodings, policies and tables for the lifetime
 * of the descriptor, so all of them live here until the capsule is destroyed. */
typedef struct composed {
    tlv_format_t format;
    union {
        tlv_binary_composition_t        binary;
        tlv_tagged_binary_composition_t tagged_binary;
        tlv_variable_format_t           variable;
        tlv_escaped_format_t            escaped;
        tlv_field_composition_t         fields;
        tlv_tagged_fields_composition_t tagged_fields;
        tlv_packed_layout_t             packed;
    } config;
    int                       tag_kind, length_kind;
    tlv_fixed_identifier_t    fixed_tag;
    tlv_variable_identifier_t variable_tag;
    tlv_identifier_policy_t   tag_policy;
    tlv_fixed_length_t        fixed_length;
    tlv_variable_length_t     variable_length;
    tlv_length_policy_t       length_policy;
    tlv_escaped_length_t      escaped_length;
    tlv_variable_format_t     variable; /* Field source for tagged variable framing. */
    tlv_constructed_bit_t     constructed;
    int                       has_constructed;
    tlv_tag_t*                tag_only;
    size_t                    count;
    uint8_t*                  tag_storage; /* Tag-only bytes or the packed identifier table. */
    uint8_t*                  forbidden;
} composed;

static void release(composed* self) {
    free(self->tag_only);
    free(self->tag_storage);
    free(self->forbidden);
    free(self);
}

static void destroy(PyObject* capsule) {
    composed* self = PyCapsule_GetPointer(capsule, COMPOSED_CAPSULE);
    if (self) release(self);
}

int opentlv_python_format_is_composed(PyObject* object) {
    return PyCapsule_IsValid(object, COMPOSED_CAPSULE);
}

const tlv_format_t* opentlv_python_composed_pointer(PyObject* capsule) {
    composed* self = PyCapsule_GetPointer(capsule, COMPOSED_CAPSULE);
    return self ? &self->format : NULL;
}

/* Every composition stores its descriptor context in config. */
static int is_constructed(const void* context, const tlv_tag_t* tag) {
    const composed* self = (const composed*)((const char*)context - offsetof(composed, config));
    return tlv_constructed_bit_predicate(&self->constructed, tag);
}

/* Field adapters for pairs without a dedicated Core composition; context is the owner. */
static tlv_result_t read_tag(const void* context, const uint8_t* data, size_t size, tlv_tag_t* tag,
                             size_t* consumed) {
    const composed* self = context;
    return self->tag_kind == FIELD_FIXED
               ? tlv_fixed_identifier_read(&self->fixed_tag, data, size, tag, consumed)
               : tlv_variable_identifier_read(&self->variable_tag, data, size, tag, consumed);
}

static tlv_result_t write_tag(const void* context, const tlv_tag_t* tag, uint8_t* data,
                              size_t capacity, size_t* written) {
    const composed* self = context;
    return self->tag_kind == FIELD_FIXED
               ? tlv_fixed_identifier_write(&self->fixed_tag, tag, data, capacity, written)
               : tlv_variable_identifier_write(&self->variable_tag, tag, data, capacity, written);
}

static tlv_result_t read_length(const void* context, const uint8_t* data, size_t size,
                                tlv_size_t* length, size_t* consumed) {
    const composed* self = context;
    switch (self->length_kind) {
        case FIELD_FIXED:
            return tlv_fixed_length_read(&self->fixed_length, data, size, length, consumed);
        case FIELD_VARIABLE:
            return tlv_variable_length_read(&self->variable_length, data, size, length, consumed);
        default:
            return tlv_escaped_length_read(&self->escaped_length, data, size, length, consumed);
    }
}

static tlv_result_t write_length(const void* context, tlv_size_t length, uint8_t* data,
                                 size_t capacity, size_t* written) {
    const composed* self = context;
    switch (self->length_kind) {
        case FIELD_FIXED:
            return tlv_fixed_length_write(&self->fixed_length, length, data, capacity, written);
        case FIELD_VARIABLE:
            return tlv_variable_length_write(&self->variable_length, length, data, capacity,
                                             written);
        default:
            return tlv_escaped_length_write(&self->escaped_length, length, data, capacity, written);
    }
}

/* Generic field composition validates configuration only when a field is
 * used. A sizing write checks configuration first, so only argument and
 * configuration errors reject the encoding here. */
static tlv_result_t probe_fields(const composed* self) {
    static const uint8_t probe = 0;
    tlv_tag_t            tag = tlv_tag(&probe, 1);
    size_t               written;
    tlv_result_t         rc = write_tag(self, &tag, NULL, 0, &written);
    if (rc == TLV_ERR_INVALID_ARG || rc == TLV_ERR_NULL_ARG) return rc;
    rc = write_length(self, 0, NULL, 0, &written);
    return rc == TLV_ERR_INVALID_ARG || rc == TLV_ERR_NULL_ARG ? rc : TLV_OK;
}

static int nonnegative(Py_ssize_t value, size_t* out) {
    if (value < 0) {
        PyErr_SetString(PyExc_ValueError, "format sizes must not be negative");
        return 0;
    }
    *out = (size_t)value;
    return 1;
}

static int count_value(PyObject* object, tlv_size_t* out) {
    unsigned long long value = PyLong_AsUnsignedLongLong(object);
    if (PyErr_Occurred()) return 0;
    *out = (tlv_size_t)value;
    return 1;
}

static tlv_byte_order_t byte_order(int big) {
    return big ? TLV_BYTE_ORDER_BIG_ENDIAN : TLV_BYTE_ORDER_LITTLE_ENDIAN;
}

static int field_kind(PyObject* specification) {
    if (!PyTuple_Check(specification) || PyTuple_Size(specification) < 1) {
        PyErr_SetString(PyExc_TypeError, "field encoding specification required");
        return -1;
    }
    long kind = PyLong_AsLong(PyTuple_GetItem(specification, 0));
    if (PyErr_Occurred()) return -1;
    return (int)kind;
}

static int parse_tag(composed* self, PyObject* specification) {
    int        kind = field_kind(specification);
    Py_ssize_t size;
    if (kind == FIELD_FIXED) {
        if (!PyArg_ParseTuple(specification, "in", &kind, &size)) return 0;
        self->tag_kind = FIELD_FIXED;
        return nonnegative(size, &self->fixed_tag.size);
    }
    if (kind != FIELD_VARIABLE) {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "unknown identifier encoding");
        return 0;
    }
    tlv_variable_identifier_t* tag = &self->variable_tag;
    PyObject*                  policy;
    if (!PyArg_ParseTuple(specification, "ibbbbnO", &kind, &tag->inline_mask, &tag->escape,
                          &tag->continuation_bit, &tag->payload_mask, &size, &policy) ||
        !nonnegative(size, &tag->max_size))
        return 0;
    self->tag_kind = FIELD_VARIABLE;
    if (policy == Py_None) return 1;
    const char* forbidden;
    Py_ssize_t  count;
    int         reject_zero, minimal;
    if (!PyArg_ParseTuple(policy, "y#pp", &forbidden, &count, &reject_zero, &minimal)) return 0;
    if (count) {
        self->forbidden = malloc((size_t)count);
        if (!self->forbidden) {
            PyErr_NoMemory();
            return 0;
        }
        memcpy(self->forbidden, forbidden, (size_t)count);
    }
    self->tag_policy = (tlv_identifier_policy_t){self->forbidden, (size_t)count,
                                                 (unsigned)reject_zero, (unsigned)minimal};
    tag->policy = &self->tag_policy;
    return 1;
}

static int parse_length(composed* self, PyObject* specification) {
    int        kind = field_kind(specification), big;
    Py_ssize_t size;
    PyObject * first, *second;
    switch (kind) {
        case FIELD_FIXED:
            if (!PyArg_ParseTuple(specification, "inp", &kind, &size, &big) ||
                !nonnegative(size, &self->fixed_length.size))
                return 0;
            self->fixed_length.byte_order = byte_order(big);
            break;
        case FIELD_VARIABLE: {
            tlv_variable_length_t* length = &self->variable_length;
            PyObject*              policy;
            if (!PyArg_ParseTuple(specification, "ibbpO", &kind, &length->long_form_bit,
                                  &length->payload_mask, &big, &policy))
                return 0;
            length->byte_order = byte_order(big);
            if (policy != Py_None) {
                tlv_length_policy_t* limits = &self->length_policy;
                int                  allow_short, allow_long, minimal;
                if (!PyArg_ParseTuple(policy, "pppnO", &allow_short, &allow_long, &minimal, &size,
                                      &first) ||
                    !nonnegative(size, &limits->max_long_octets) ||
                    !count_value(first, &limits->max_value))
                    return 0;
                limits->allow_short = (unsigned)allow_short;
                limits->allow_long = (unsigned)allow_long;
                limits->require_minimal = (unsigned)minimal;
                length->policy = limits;
            }
            break;
        }
        case FIELD_ESCAPED: {
            tlv_escaped_length_t* length = &self->escaped_length;
            if (!PyArg_ParseTuple(specification, "ibnpOO", &kind, &length->escape, &size, &big,
                                  &first, &second) ||
                !nonnegative(size, &length->extended_size) ||
                !count_value(first, &length->min_extended) ||
                !count_value(second, &length->max_length))
                return 0;
            length->byte_order = byte_order(big);
            break;
        }
        default:
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "unknown length encoding");
            return 0;
    }
    self->length_kind = kind;
    return 1;
}

/* Copies tag-only identifiers into one owned block; Core borrows the table. */
static int parse_tag_only(composed* self, PyObject* tags) {
    if (!PyTuple_Check(tags)) {
        PyErr_SetString(PyExc_TypeError, "tag_only must be a tuple of bytes");
        return 0;
    }
    Py_ssize_t count = PyTuple_Size(tags), total = 0;
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject* tag = PyTuple_GetItem(tags, i);
        if (!PyBytes_Check(tag)) {
            PyErr_SetString(PyExc_TypeError, "tag_only must be a tuple of bytes");
            return 0;
        }
        total += PyBytes_Size(tag);
    }
    if (!count) return 1;
    self->tag_only = calloc((size_t)count, sizeof *self->tag_only);
    self->tag_storage = malloc(total ? (size_t)total : 1);
    if (!self->tag_only || !self->tag_storage) {
        PyErr_NoMemory();
        return 0;
    }
    uint8_t* cursor = self->tag_storage;
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject* tag = PyTuple_GetItem(tags, i);
        size_t    size = (size_t)PyBytes_Size(tag);
        memcpy(cursor, PyBytes_AsString(tag), size);
        self->tag_only[i] = tlv_tag(cursor, size);
        cursor += size;
    }
    self->count = (size_t)count;
    return 1;
}

static int parse_constructed(composed* self, PyObject* constructed) {
    if (constructed == Py_None) return 1;
    tlv_constructed_bit_t* bit = &self->constructed;
    Py_ssize_t             index;
    if (!PyArg_ParseTuple(constructed, "nbb", &index, &bit->mask, &bit->value) ||
        !nonnegative(index, &bit->byte_index))
        return 0;
    self->has_constructed = 1;
    return 1;
}

/* Selects the dedicated Core composition for an encoding pair, or composes
 * the field primitives through the generic field composition. */
static tlv_result_t compose_fields(composed* self, tlv_element_order_t order,
                                   tlv_length_scope_t scope) {
    const tlv_constructed_bit_t* constructed = self->has_constructed ? &self->constructed : NULL;
    if (self->tag_kind == FIELD_FIXED && self->length_kind == FIELD_FIXED) {
        tlv_binary_composition_t binary = {self->fixed_tag, self->fixed_length, order, scope};
        if (!self->count) {
            self->config.binary = binary;
            return tlv_fixed_format_init(&self->format, &self->config.binary);
        }
        self->config.tagged_binary =
            (tlv_tagged_binary_composition_t){binary, self->tag_only, self->count};
        return tlv_tagged_binary_format_init(&self->format, &self->config.tagged_binary);
    }
    if (self->tag_kind == FIELD_VARIABLE && self->length_kind == FIELD_VARIABLE) {
        self->variable = (tlv_variable_format_t){self->variable_tag, self->variable_length, order,
                                                 scope, constructed};
        if (!self->count) {
            self->config.variable = self->variable;
            return tlv_variable_format_init(&self->format, &self->config.variable);
        }
        tlv_result_t rc =
            tlv_variable_fields_init(&self->config.tagged_fields.fields, &self->variable);
        if (rc != TLV_OK) return rc;
        self->config.tagged_fields.tag_only = self->tag_only;
        self->config.tagged_fields.count = self->count;
        return tlv_tagged_fields_format_init(&self->format, &self->config.tagged_fields);
    }
    if (self->tag_kind == FIELD_FIXED && self->length_kind == FIELD_ESCAPED) {
        self->config.escaped = (tlv_escaped_format_t){
            self->fixed_tag, self->escaped_length, order, scope, self->tag_only, self->count};
        return tlv_escaped_format_init(&self->format, &self->config.escaped);
    }
    tlv_result_t rc = probe_fields(self);
    if (rc != TLV_OK) return rc;
    tlv_field_composition_t fields = {self,      read_tag,     read_length, NULL,
                                      write_tag, write_length, order,       scope};
    if (!self->count) {
        self->config.fields = fields;
        return tlv_fields_format_init(&self->format, &self->config.fields);
    }
    self->config.tagged_fields =
        (tlv_tagged_fields_composition_t){fields, self->tag_only, self->count};
    return tlv_tagged_fields_format_init(&self->format, &self->config.tagged_fields);
}

/* Builds the canonical identifier table: entry i is i in tag_size big-endian bytes. */
static tlv_result_t compose_packed(composed* self, PyObject* args) {
    tlv_packed_layout_t* layout = &self->config.packed;
    Py_ssize_t           header, tag_size;
    unsigned int         tag_offset, tag_width, length_offset, length_width;
    int                  kind, big, scope;
    PyObject*            constructed;
    if (!PyArg_ParseTuple(args, "in(II)(II)pnpO", &kind, &header, &tag_offset, &tag_width,
                          &length_offset, &length_width, &big, &tag_size, &scope, &constructed) ||
        !nonnegative(header, &layout->header_size) || !nonnegative(tag_size, &layout->tag_size) ||
        !parse_constructed(self, constructed))
        return TLV_ERR_INVALID_ARG;
    if (tag_width > PACKED_TAG_MAX_WIDTH) {
        PyErr_SetString(PyExc_ValueError, "packed tag fields wider than 16 bits are unsupported");
        return TLV_ERR_INVALID_ARG;
    }
    layout->tag = (tlv_packed_field_t){layout->header_size, tag_offset, tag_width, byte_order(big)};
    layout->length =
        (tlv_packed_field_t){layout->header_size, length_offset, length_width, byte_order(big)};
    layout->length_scope = scope ? TLV_LENGTH_SCOPE_TAG_AND_VALUE : TLV_LENGTH_SCOPE_VALUE;
    /* Without a table Core would report the missing storage, not the width. */
    if (!tag_width || !layout->tag_size || layout->tag_size > 8) return TLV_ERR_INVALID_ARG;
    size_t entries = (size_t)1 << tag_width;
    self->tag_storage = malloc(entries * layout->tag_size);
    if (!self->tag_storage) {
        PyErr_NoMemory();
        return TLV_ERR_OUT_OF_MEMORY;
    }
    for (size_t i = 0; i < entries; ++i)
        for (size_t b = 0; b < layout->tag_size; ++b)
            self->tag_storage[i * layout->tag_size + b] =
                (uint8_t)((uint64_t)i >> (8 * (layout->tag_size - 1 - b)));
    layout->tag_storage = self->tag_storage;
    layout->tag_storage_size = entries * layout->tag_size;
    tlv_result_t rc = tlv_packed_layout_validate(layout);
    if (rc != TLV_OK) return rc;
    return tlv_format_init(&self->format, layout, tlv_packed_decode, tlv_packed_measure,
                           tlv_packed_encode);
}

/* format_compose(specification) -> capsule
 *
 * specification is (0, tag, length, ltv, tag_and_value, tag_only, constructed)
 * for field composition or (1, header_size, (tag offset, width), (length
 * offset, width), big_endian, tag_size, tag_and_value, constructed) for a
 * packed header. Core rejects invalid configuration with _opentlv.Error. */
PyObject* opentlv_python_format_compose(PyObject* module, PyObject* specification) {
    (void)module;
    if (!PyTuple_Check(specification) || PyTuple_Size(specification) < 1) {
        PyErr_SetString(PyExc_TypeError, "format specification tuple required");
        return NULL;
    }
    long kind = PyLong_AsLong(PyTuple_GetItem(specification, 0));
    if (PyErr_Occurred()) return NULL;
    composed* self = calloc(1, sizeof *self);
    if (!self) return PyErr_NoMemory();
    tlv_result_t rc;
    if (kind == COMPOSE_FIELDS) {
        PyObject *tag, *length, *tag_only, *constructed;
        int       ignored, ltv, tag_and_value;
        if (!PyArg_ParseTuple(specification, "iOOppOO", &ignored, &tag, &length, &ltv,
                              &tag_and_value, &tag_only, &constructed) ||
            !parse_tag(self, tag) || !parse_length(self, length) ||
            !parse_tag_only(self, tag_only) || !parse_constructed(self, constructed)) {
            release(self);
            return NULL;
        }
        rc =
            compose_fields(self, ltv ? TLV_ELEMENT_ORDER_LTV : TLV_ELEMENT_ORDER_TLV,
                           tag_and_value ? TLV_LENGTH_SCOPE_TAG_AND_VALUE : TLV_LENGTH_SCOPE_VALUE);
    } else if (kind == COMPOSE_PACKED) {
        rc = compose_packed(self, specification);
    } else {
        PyErr_SetString(PyExc_ValueError, "unknown format composition");
        rc = TLV_ERR_INVALID_ARG;
    }
    if (rc == TLV_OK && self->has_constructed) {
        const tlv_constructed_bit_t* bit = &self->constructed;
        if (!bit->mask || (bit->value & ~bit->mask))
            rc = TLV_ERR_INVALID_ARG;
        else if (!self->format.is_constructed)
            self->format.is_constructed = is_constructed;
    }
    if (rc != TLV_OK) {
        release(self);
        if (!PyErr_Occurred()) opentlv_python_raise_result(rc);
        return NULL;
    }
    PyObject* capsule = PyCapsule_New(self, COMPOSED_CAPSULE, destroy);
    if (!capsule) release(self);
    return capsule;
}
