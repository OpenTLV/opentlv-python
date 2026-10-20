// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
#define PY_SSIZE_T_CLEAN
#include "query.h"
#include "location.h"
#include "reader.h"
#include "format.h"
#include <tlv/query/adapters.h>
#if OPENTLV_EMV
#include <tlv/builtins/emv/query.h>
#endif
#include <tlv/writer/tree.h>
#if OPENTLV_FORMAT_BER
#include <tlv/builtins/asn1/query.h>
#endif
#include <stdlib.h>
#include <string.h>
#include "../../../common/query_schema.h"

#define PROGRAM_NAME "opentlv.query_program"
#define EXECUTION_NAME "opentlv.query_execution"
typedef struct memory {
    void*  allocation;
    void*  data;
    size_t size;
} memory;
typedef struct program {
    memory                     image;
    const tlv_query_program_t* native;
    tlv_query_program_info_t   info;
    tlv_query_environment_t    environment;
    tlv_query_hook_t           hooks[4];
    PyObject*                  providers;
    PyObject*                  owners;
    tlv_query_tag_adapter_t    tags;
} program;
typedef struct execution {
    PyObject *        owner, *reader, *inputs, *bindings, *document;
    memory            workspace, values, staging_data, staging_scratch, frames;
    Py_buffer         external;
    tlv_query_exec_t* native;
    size_t            depth, nodes, work;
    int               retained, busy;
} execution;

static int allocate(memory* out, size_t bytes) {
    if (bytes > SIZE_MAX - 15) {
        PyErr_NoMemory();
        return 0;
    }
    out->allocation = malloc(bytes + 15);
    if (!out->allocation) {
        PyErr_NoMemory();
        return 0;
    }
    out->data = (void*)(((uintptr_t)out->allocation + 15) & ~(uintptr_t)15);
    out->size = bytes;
    return 1;
}
static void release(memory* out) {
    free(out->allocation);
    memset(out, 0, sizeof *out);
}
static PyObject* failure(tlv_result_t code, const tlv_query_diagnostic_t* diagnostic) {
    if (!PyErr_Occurred()) opentlv_python_raise_query(code, diagnostic);
    return NULL;
}
static int set_size(PyObject* dict, const char* key, size_t value) {
    PyObject* number = PyLong_FromSize_t(value);
    if (!number) return -1;
    int rc = PyDict_SetItemString(dict, key, number);
    Py_DECREF(number);
    return rc;
}
static PyObject* failure_fields(tlv_result_t code, const tlv_query_diagnostic_t* diagnostic,
                                PyObject* details) {
    failure(code, diagnostic);
    PyObject *type, *error, *traceback;
    PyErr_Fetch(&type, &error, &traceback);
    PyErr_NormalizeException(&type, &error, &traceback);
    PyObject* args = error ? PyObject_GetAttrString(error, "args") : NULL;
    if (args && PyTuple_Size(args) > 0) {
        PyObject* fields = PyTuple_GetItem(args, 0);
        if (PyDict_Check(fields)) PyDict_Update(fields, details);
    }
    Py_XDECREF(args);
    PyErr_Clear();
    PyErr_Restore(type, error, traceback);
    return NULL;
}
static int size_option(PyObject* options, const char* name, size_t* value) {
    PyObject* item = PyDict_GetItemString(options, name);
    if (!item) return 1;
    *value = PyLong_AsSize_t(item);
    return !PyErr_Occurred();
}
typedef struct {
    PyObject *names, *callback, *value;
} resolver_context;
static tlv_result_t resolve(const void* context, const char* space, size_t space_size,
                            const char* name, size_t name_size, tlv_tag_t* tag) {
    resolver_context* resolver = (resolver_context*)context;
    if (resolver->callback) {
        PyObject* ns =
            PyUnicode_DecodeUTF8(space_size ? space : "", (Py_ssize_t)space_size, "strict");
        PyObject* spelling = PyUnicode_DecodeUTF8(name, (Py_ssize_t)name_size, "strict");
        PyObject* resolved =
            ns && spelling ? PyObject_CallFunctionObjArgs(resolver->callback, ns, spelling, NULL)
                           : NULL;
        Py_XDECREF(ns);
        Py_XDECREF(spelling);
        if (!resolved) return TLV_ERR_INVALID_ARG;
        Py_XDECREF(resolver->value);
        resolver->value = resolved;
        if (resolved == Py_None) return TLV_ERR_INVALID_TAG;
        char*      data;
        Py_ssize_t size;
        if (PyBytes_AsStringAndSize(resolved, &data, &size) < 0) return TLV_ERR_INVALID_ARG;
        *tag = tlv_tag((const uint8_t*)data, (size_t)size);
        return TLV_OK;
    }
    PyObject* key = NULL;
    if (space_size) {
        PyObject* left = PyUnicode_DecodeUTF8(space, (Py_ssize_t)space_size, "strict");
        PyObject* right = PyUnicode_DecodeUTF8(name, (Py_ssize_t)name_size, "strict");
        key = left && right ? PyUnicode_FromFormat("%U:%U", left, right) : NULL;
        Py_XDECREF(left);
        Py_XDECREF(right);
    } else
        key = PyUnicode_DecodeUTF8(name, (Py_ssize_t)name_size, "strict");
    if (!key) return TLV_ERR_INVALID_ARG;
    PyObject* value = PyDict_GetItemWithError(resolver->names, key);
    Py_DECREF(key);
    if (!value) return PyErr_Occurred() ? TLV_ERR_INVALID_ARG : TLV_ERR_INVALID_TAG;
    char*      data;
    Py_ssize_t size;
    if (PyBytes_AsStringAndSize(value, &data, &size) < 0) return TLV_ERR_INVALID_ARG;
    *tag = tlv_tag((const uint8_t*)data, (size_t)size);
    return TLV_OK;
}
static tlv_result_t tag_decompose(const void* context, const tlv_tag_t* tag, int64_t* out,
                                  int slot) {
    const program* self = context;
    PyObject*      callbacks = PyTuple_GetItem(self->owners, 1);
    PyObject*      callback = PyTuple_GetItem(callbacks, slot);
    PyObject*      bytes = PyBytes_FromStringAndSize((const char*)tag->data, (Py_ssize_t)tag->size);
    PyObject*      value = bytes ? PyObject_CallFunctionObjArgs(callback, bytes, NULL) : NULL;
    Py_XDECREF(bytes);
    if (!value) return TLV_ERR_INVALID_ARG;
    if (!PyLong_Check(value) || PyBool_Check(value)) {
        Py_DECREF(value);
        PyErr_SetString(PyExc_TypeError, "Tag adapter must return int64");
        return TLV_ERR_INVALID_ARG;
    }
    int64_t result = PyLong_AsLongLong(value);
    Py_DECREF(value);
    if (PyErr_Occurred()) return TLV_ERR_INVALID_ARG;
    *out = result;
    return TLV_OK;
}
static tlv_result_t tag_class(const void* context, const tlv_tag_t* tag, int64_t* out) {
    return tag_decompose(context, tag, out, 1);
}
static tlv_result_t tag_number(const void* context, const tlv_tag_t* tag, int64_t* out) {
    return tag_decompose(context, tag, out, 2);
}
static void destroy_program(PyObject* capsule) {
    program* self = PyCapsule_GetPointer(capsule, PROGRAM_NAME);
    if (!self) return;
    release(&self->image);
    Py_XDECREF(self->providers);
    Py_XDECREF(self->owners);
    free(self);
}
static PyObject*    project(const tlv_tree_event_t* event);
static tlv_result_t decode_provider(const void* context, const tlv_tree_event_t* event,
                                    const uint8_t* data, size_t size, void* scratch,
                                    size_t capacity, tlv_query_result_t* result,
                                    tlv_codec_diagnostic_t* diagnostic) {
    tlv_codec_diagnostic_init(diagnostic, TLV_CODEC_OP_DECODE);
    PyObject* callback = (PyObject*)context;
    PyObject* input = PyBytes_FromStringAndSize((const char*)data, (Py_ssize_t)size);
    PyObject* metadata = event ? project(event) : Py_NewRef(Py_None);
    PyObject* value =
        input && metadata ? PyObject_CallFunctionObjArgs(callback, input, metadata, NULL) : NULL;
    Py_XDECREF(input);
    Py_XDECREF(metadata);
    if (!value) return tlv_codec_diagnostic_result(diagnostic, TLV_ERR_INVALID_VALUE);
    memset(result, 0, sizeof *result);
    tlv_result_t code = TLV_OK;
    if (PyLong_Check(value) && !PyBool_Check(value)) {
        result->kind = TLV_QUERY_RESULT_INTEGER;
        result->integer = PyLong_AsLongLong(value);
        if (PyErr_Occurred()) code = TLV_ERR_INVALID_VALUE;
    } else if (PyUnicode_Check(value)) {
        Py_ssize_t  length;
        const char* text = PyUnicode_AsUTF8AndSize(value, &length);
        if (!text)
            code = TLV_ERR_INVALID_VALUE;
        else if ((size_t)length > capacity)
            code = TLV_ERR_BUFFER_TOO_SHORT;
        else {
            if (length) memcpy(scratch, text, (size_t)length);
            result->kind = TLV_QUERY_RESULT_STRING;
            result->data = scratch;
            result->size = (size_t)length;
        }
    } else {
        PyErr_SetString(PyExc_TypeError, "Query provider must return int or str");
        code = TLV_ERR_INVALID_VALUE;
    }
    Py_DECREF(value);
    return tlv_codec_diagnostic_result(diagnostic, code);
}
static void dispose_execution(execution* self) {
    Py_XDECREF(self->owner);
    Py_XDECREF(self->reader);
    Py_XDECREF(self->inputs);
    Py_XDECREF(self->bindings);
    Py_XDECREF(self->document);
    if (self->external.obj) PyBuffer_Release(&self->external);
    release(&self->workspace);
    release(&self->values);
    release(&self->staging_data);
    release(&self->staging_scratch);
    release(&self->frames);
    free(self);
}
static void destroy_execution(PyObject* capsule) {
    execution* self = PyCapsule_GetPointer(capsule, EXECUTION_NAME);
    if (self) dispose_execution(self);
}
static execution* get_execution(PyObject* capsule) {
    execution* self = PyCapsule_GetPointer(capsule, EXECUTION_NAME);
    if (self && self->busy) {
        failure(TLV_ERR_INVALID_STATE, NULL);
        return NULL;
    }
    return self;
}

PyObject* opentlv_python_query_emv_resolve(PyObject* module, PyObject* args) {
    (void)module;
    const char *space, *name;
    Py_ssize_t  space_size, name_size;
    if (!PyArg_ParseTuple(args, "s#s#", &space, &space_size, &name, &name_size)) return NULL;
#if OPENTLV_EMV
    tlv_tag_t    tag;
    tlv_result_t rc =
        tlv_emv_query_resolve(NULL, space, (size_t)space_size, name, (size_t)name_size, &tag);
    if (rc != TLV_OK) return failure(rc, NULL);
    return PyBytes_FromStringAndSize((const char*)tag.data, (Py_ssize_t)tag.size);
#else
    return failure(TLV_ERR_UNSUPPORTED, NULL);
#endif
}

PyObject* opentlv_python_query_definition_resolve(PyObject* module, PyObject* args) {
    (void)module;
    PyObject *records, *space, *name;
    if (!PyArg_ParseTuple(args, "OOO", &records, &space, &name)) return NULL;
    Py_ssize_t  count = PyTuple_Size(records), space_size, name_size;
    const char* scope = PyUnicode_AsUTF8AndSize(space, &space_size);
    const char* spelling = PyUnicode_AsUTF8AndSize(name, &name_size);
    if (count < 0 || !scope || !spelling) return NULL;
    if ((size_t)count > SIZE_MAX / sizeof(tlv_query_definition_scope_t) ||
        (size_t)count > SIZE_MAX / sizeof(tlv_definition_registry_t))
        return failure(TLV_ERR_OVERFLOW, NULL);
    tlv_query_definition_scope_t* scopes = calloc(count ? (size_t)count : 1, sizeof *scopes);
    tlv_definition_registry_t* registries = calloc(count ? (size_t)count : 1, sizeof *registries);
    if (!scopes || !registries) {
        free(scopes);
        free(registries);
        return PyErr_NoMemory();
    }
    PyObject* result = NULL;
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject *namespace_name, *definitions;
        if (!PyArg_ParseTuple(PyTuple_GetItem(records, i), "OO", &namespace_name, &definitions))
            goto done;
        scopes[i].namespace_name = PyUnicode_AsUTF8AndSize(namespace_name, NULL);
        scopes[i].definitions = &registries[i];
        Py_ssize_t length = PyTuple_Size(definitions);
        if (!scopes[i].namespace_name || length < 0) goto done;
        if ((size_t)length > SIZE_MAX / sizeof(tlv_definition_t)) {
            failure(TLV_ERR_OVERFLOW, NULL);
            goto done;
        }
        tlv_definition_t* entries = calloc(length ? (size_t)length : 1, sizeof *entries);
        if (!entries) {
            PyErr_NoMemory();
            goto done;
        }
        registries[i].entries = entries;
        registries[i].count = (size_t)length;
        for (Py_ssize_t j = 0; j < length; ++j) {
            PyObject *bytes, *label;
            if (!PyArg_ParseTuple(PyTuple_GetItem(definitions, j), "OO", &bytes, &label)) goto done;
            char*      data;
            Py_ssize_t size;
            if (PyBytes_AsStringAndSize(bytes, &data, &size) < 0) goto done;
            entries[j].tag = tlv_tag((const uint8_t*)data, (size_t)size);
            entries[j].name = label == Py_None ? NULL : PyUnicode_AsUTF8AndSize(label, NULL);
            if (PyErr_Occurred()) goto done;
        }
    }
    tlv_query_definition_resolver_t resolver = {scopes, (size_t)count};
    tlv_tag_t                       tag;
    tlv_result_t rc = tlv_query_definition_resolve(&resolver, scope, (size_t)space_size, spelling,
                                                   (size_t)name_size, &tag);
    if (rc != TLV_OK)
        failure(rc, NULL);
    else
        result = PyBytes_FromStringAndSize((const char*)tag.data, (Py_ssize_t)tag.size);
done:
    for (Py_ssize_t i = 0; i < count; ++i) free((void*)registries[i].entries);
    free(registries);
    free(scopes);
    return result;
}

PyObject* opentlv_python_program_create(PyObject* module, PyObject* args) {
    (void)module;
    PyObject *text, *format_spec, *variables, *names, *options;
    int       image;
    if (!PyArg_ParseTuple(args, "OOOOOp", &text, &format_spec, &variables, &names, &options,
                          &image))
        return NULL;
    if (!PyDict_Check(variables) || !PyDict_Check(names) || !PyDict_Check(options)) {
        PyErr_SetString(PyExc_TypeError, "Query variables, names and options must be dictionaries");
        return NULL;
    }
    char*      data;
    Py_ssize_t length;
    if (PyBytes_AsStringAndSize(text, &data, &length) < 0) return NULL;
    program* self = calloc(1, sizeof *self);
    if (!self) return PyErr_NoMemory();
    PyObject* format_owner = opentlv_python_format_owner(format_spec);
    if (!format_owner) {
        Py_XDECREF(self->owners);
        free(self);
        return NULL;
    }
    PyObject* tags = PyDict_GetItemString(options, "tags");
    self->owners = PyTuple_Pack(2, format_owner, tags ? tags : Py_None);
    self->environment.format = opentlv_python_format_pointer(format_owner);
    Py_DECREF(format_owner);
    if (!self->owners) {
        Py_XDECREF(self->owners);
        free(self);
        return NULL;
    }
    size_t                  hook_count;
    const tlv_query_hook_t* hooks = tlv_query_builtin_hooks(&hook_count);
    memcpy(self->hooks, hooks, hook_count * sizeof *hooks);
#if OPENTLV_FORMAT_BER
    long format_id = PyLong_Check(format_spec) ? PyLong_AsLong(format_spec) : -1;
    if (format_id == 1 || format_id == 2 || format_id == 3) {
        self->environment.tags = &tlv_asn1_query_tags;
        self->hooks[hook_count++] = tlv_asn1_query_date;
    }
#endif
    if (tags) {
        unsigned long id;
        PyObject *    class_of, *number_of;
        if (!PyArg_ParseTuple(tags, "kOO", &id, &class_of, &number_of) || !id || id > UINT32_MAX ||
            (class_of != Py_None && !PyCallable_Check(class_of)) ||
            (number_of != Py_None && !PyCallable_Check(number_of))) {
            Py_XDECREF(self->owners);
            free(self);
            if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "invalid Tag adapter");
            return NULL;
        }
        self->tags =
            (tlv_query_tag_adapter_t){(uint32_t)id, self, class_of == Py_None ? NULL : tag_class,
                                      number_of == Py_None ? NULL : tag_number};
        self->environment.tags = &self->tags;
    }
    self->environment.hooks = self->hooks;
    self->environment.hook_count = hook_count;
    PyObject* providers = PyDict_GetItemString(options, "providers");
    if (providers) {
        if (!PyDict_Check(providers)) {
            Py_XDECREF(self->owners);
            free(self);
            PyErr_SetString(PyExc_TypeError, "providers must be a dictionary");
            return NULL;
        }
        self->providers = PyDict_Copy(providers);
        if (!self->providers) {
            Py_XDECREF(self->owners);
            free(self);
            return NULL;
        }
        Py_ssize_t provider_position = 0;
        PyObject * provider_key, *provider_value;
        while (PyDict_Next(providers, &provider_position, &provider_key, &provider_value)) {
            long          function = PyLong_AsLong(provider_key);
            unsigned long id;
            Py_ssize_t    capacity;
            PyObject*     callback;
            if (PyErr_Occurred() || function < 0 || function > 3 ||
                !PyArg_ParseTuple(provider_value, "knO", &id, &capacity, &callback) || !id ||
                id > UINT32_MAX || capacity < 0 || !PyCallable_Check(callback)) {
                Py_DECREF(self->providers);
                Py_XDECREF(self->owners);
                free(self);
                if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "invalid Query provider");
                return NULL;
            }
            size_t slot = 0;
            while (slot < hook_count &&
                   self->hooks[slot].function != (tlv_query_conversion_t)function)
                ++slot;
            if (slot == hook_count) ++hook_count;
            self->hooks[slot] = (tlv_query_hook_t){
                (uint32_t)id,   (tlv_query_conversion_t)function, (size_t)capacity, 1, callback,
                decode_provider};
        }
        self->environment.hook_count = hook_count;
    }
    tlv_query_compile_options_t config;
    tlv_query_compile_options_init(&config);
    config.environment = &self->environment;
    resolver_context resolver = {names, PyDict_GetItemString(options, "resolve"), NULL};
    config.resolve = resolve;
    config.resolve_context = &resolver;
    Py_ssize_t            count = PyDict_Size(variables);
    tlv_query_variable_t* declarations = NULL;
    PyObject*             keep_names = PyList_New(0);
    if (!keep_names || (size_t)count > SIZE_MAX / sizeof *declarations) goto python_error;
    if (count) {
        declarations = calloc((size_t)count, sizeof *declarations);
        if (!declarations) {
            PyErr_NoMemory();
            goto python_error;
        }
    }
    Py_ssize_t position = 0;
    PyObject * key, *value;
    size_t     index = 0;
    while (PyDict_Next(variables, &position, &key, &value)) {
        PyObject* name = PyUnicode_AsUTF8String(key);
        if (!name) goto python_error;
        if (PyList_Append(keep_names, name) < 0) {
            Py_DECREF(name);
            goto python_error;
        }
        declarations[index].name = PyBytes_AsString(name);
        declarations[index++].type = (tlv_query_result_kind_t)PyLong_AsLong(value);
        Py_DECREF(name);
        if (PyErr_Occurred()) goto python_error;
    }
    config.variables = declarations;
    config.variable_count = (size_t)count;
    if (!size_option(options, "max_text", &config.max_text) ||
        !size_option(options, "max_tokens", &config.max_tokens) ||
        !size_option(options, "max_nesting", &config.max_nesting) ||
        !size_option(options, "max_states", &config.max_states) ||
        !size_option(options, "max_pattern", &config.max_pattern) ||
        !size_option(options, "max_resolved_tag", &config.max_resolved_tag))
        goto python_error;
    value = PyDict_GetItemString(options, "optimize");
    if (value) {
        config.optimize = PyObject_IsTrue(value);
        if (config.optimize < 0) goto python_error;
    }
    tlv_query_diagnostic_t diagnostic = {0};
    size_t                 bytes, alignment;
    tlv_result_t rc = image ? tlv_query_program_load_scratch(data, (size_t)length, &config, &bytes,
                                                             &alignment, &diagnostic)
                            : tlv_query_compile_prepare_size(data, (size_t)length, &config, &bytes,
                                                             &alignment, &diagnostic);
    memory       scratch = {0};
    memory       validation = {0};
    const tlv_query_program_t* prepared = NULL;
    self->info.struct_size = sizeof self->info;
    if (rc == TLV_OK && !allocate(&scratch, bytes)) goto python_error;
    if (rc == TLV_OK && !image)
        rc = tlv_query_compile_prepare(data, (size_t)length, &config, scratch.data, scratch.size,
                                       &prepared, &self->info, &diagnostic);
    if (rc == TLV_OK && !image) {
        rc = tlv_query_program_load_scratch(prepared, self->info.program_size, &config, &bytes,
                                            &alignment, &diagnostic);
        if (rc == TLV_OK && !allocate(&validation, bytes)) {
            release(&scratch);
            goto python_error;
        }
    }
    if (rc == TLV_OK && !allocate(&self->image, image ? (size_t)length : self->info.program_size)) {
        release(&scratch);
        release(&validation);
        goto python_error;
    }
    if (rc == TLV_OK && image) {
        memcpy(self->image.data, data, (size_t)length);
        rc = tlv_query_program_load(self->image.data, self->image.size, &config, scratch.data,
                                    scratch.size, &self->native, &self->info, &diagnostic);
    } else if (rc == TLV_OK) {
        rc = tlv_query_compile_commit(prepared, self->info.program_size, &config, validation.data,
                                      validation.size, self->image.data, self->image.size,
                                      &self->info, &diagnostic);
        self->native = self->image.data;
    }
    release(&scratch);
    release(&validation);
    Py_XDECREF(resolver.value);
    free(declarations);
    Py_DECREF(keep_names);
    if (rc != TLV_OK || PyErr_Occurred()) {
        release(&self->image);
        Py_XDECREF(self->providers);
        Py_XDECREF(self->owners);
        free(self);
        return failure(rc, &diagnostic);
    }
    PyObject* capsule = PyCapsule_New(self, PROGRAM_NAME, destroy_program);
    if (!capsule) {
        release(&self->image);
        Py_XDECREF(self->providers);
        Py_XDECREF(self->owners);
        free(self);
    }
    return capsule;
python_error:
    Py_XDECREF(resolver.value);
    free(declarations);
    Py_XDECREF(keep_names);
    release(&self->image);
    Py_XDECREF(self->providers);
    Py_XDECREF(self->owners);
    free(self);
    if (!PyErr_Occurred()) PyErr_NoMemory();
    return NULL;
}

PyObject* opentlv_python_program_info(PyObject* module, PyObject* capsule) {
    (void)module;
    program* self = PyCapsule_GetPointer(capsule, PROGRAM_NAME);
    if (!self) return NULL;
    PyObject* info = PyDict_New();
    if (!info) return NULL;
#define FIELD(name)                                                                                \
    do {                                                                                           \
        if (set_size(info, #name, self->info.name) < 0) {                                          \
            Py_DECREF(info);                                                                       \
            return NULL;                                                                           \
        }                                                                                          \
    } while (0)
    FIELD(program_size);
    FIELD(program_alignment);
    FIELD(scratch_size);
    FIELD(scratch_alignment);
    FIELD(states);
    FIELD(language_version);
    FIELD(level);
    FIELD(result_kind);
    FIELD(expression_values);
    FIELD(instructions);
    FIELD(variable_slots);
    FIELD(codec_scratch);
    FIELD(pattern_bytes);
    FIELD(optimized_states);
    FIELD(expression_stack);
    FIELD(candidate_size);
    FIELD(candidate_alignment);
    FIELD(frame_states);
    FIELD(decision_timing);
    FIELD(stable_input_required);
    FIELD(constructed_values_required);
#undef FIELD
    PyObject* variables = PyList_New(0);
    if (!variables) {
        Py_DECREF(info);
        return NULL;
    }
    for (size_t i = 0; i < tlv_query_program_variable_count(self->native); ++i) {
        tlv_query_variable_info_t variable;
        tlv_result_t              rc = tlv_query_program_variable(self->native, i, &variable);
        if (rc != TLV_OK) {
            Py_DECREF(variables);
            Py_DECREF(info);
            return failure(rc, NULL);
        }
        PyObject* item =
            Py_BuildValue("(s#i)", variable.name, (Py_ssize_t)variable.name_size, variable.type);
        int failed = !item || PyList_Append(variables, item) < 0;
        Py_XDECREF(item);
        if (failed) {
            Py_DECREF(variables);
            Py_DECREF(info);
            return NULL;
        }
    }
    int failed = PyDict_SetItemString(info, "variables", variables) < 0;
    Py_DECREF(variables);
    if (failed) {
        Py_DECREF(info);
        return NULL;
    }
    return info;
}
PyObject* opentlv_python_program_render(PyObject* module, PyObject* args) {
    (void)module;
    PyObject* capsule;
    int       kind;
    if (!PyArg_ParseTuple(args, "Oi", &capsule, &kind)) return NULL;
    program* self = PyCapsule_GetPointer(capsule, PROGRAM_NAME);
    if (!self) return NULL;
    if (kind == 2) return PyBytes_FromStringAndSize(self->image.data, (Py_ssize_t)self->image.size);
    size_t       bytes;
    tlv_result_t rc = kind ? tlv_query_program_explain(self->native, NULL, 0, &bytes)
                           : tlv_query_program_format(self->native, NULL, 0, &bytes);
    if (rc != TLV_OK) return failure(rc, NULL);
    memory output = {0};
    if (!allocate(&output, bytes)) return NULL;
    rc = kind ? tlv_query_program_explain(self->native, output.data, bytes, &bytes)
              : tlv_query_program_format(self->native, output.data, bytes, &bytes);
    PyObject* result = rc == TLV_OK
                           ? PyUnicode_DecodeUTF8(output.data, (Py_ssize_t)bytes - 1, "strict")
                           : failure(rc, NULL);
    release(&output);
    return result;
}

PyObject* opentlv_python_execution_create(PyObject* module, PyObject* args) {
    (void)module;
    PyObject * owner, *external;
    Py_ssize_t depth, nodes, work;
    int        retained;
    if (!PyArg_ParseTuple(args, "OnnnpO", &owner, &depth, &nodes, &work, &retained, &external))
        return NULL;
    program* query = PyCapsule_GetPointer(owner, PROGRAM_NAME);
    if (!query) return NULL;
    if (depth < 0 || nodes <= 0 || work <= 0) return failure(TLV_ERR_INVALID_ARG, NULL);
    execution* self = calloc(1, sizeof *self);
    if (!self) return PyErr_NoMemory();
    self->owner = Py_NewRef(owner);
    self->depth = (size_t)depth;
    self->nodes = (size_t)nodes;
    self->work = (size_t)work;
    self->retained = retained;
    self->inputs = PyList_New(0);
    self->bindings = PyList_New(0);
    if (!self->inputs || !self->bindings) {
        dispose_execution(self);
        return NULL;
    }
    size_t       bytes, alignment;
    tlv_result_t rc =
        retained ? tlv_query_eval_size(query->native, self->depth, self->nodes, &bytes, &alignment)
                 : tlv_query_exec_size(query->native, self->depth, &bytes, &alignment);
    void*  storage = NULL;
    size_t capacity = 0;
    if (rc == TLV_OK && external != Py_None) {
        if (PyObject_GetBuffer(external, &self->external, PyBUF_WRITABLE | PyBUF_C_CONTIGUOUS) <
            0) {
            dispose_execution(self);
            return NULL;
        }
        storage = self->external.buf;
        capacity = (size_t)self->external.len;
    } else if (rc == TLV_OK) {
        if (!allocate(&self->workspace, bytes)) {
            dispose_execution(self);
            return NULL;
        }
        storage = self->workspace.data;
        capacity = bytes;
    }
    if (rc == TLV_OK)
        rc = retained ? tlv_query_eval_init(query->native, &query->environment, storage, capacity,
                                            self->depth, self->nodes, self->work, &self->native)
                      : tlv_query_exec_init(query->native, storage, capacity, self->depth,
                                            self->nodes, self->work, &self->native);
    if (rc != TLV_OK) {
        dispose_execution(self);
        return failure(rc, NULL);
    }
    PyObject* capsule = PyCapsule_New(self, EXECUTION_NAME, destroy_execution);
    if (!capsule) dispose_execution(self);
    return capsule;
}
PyObject* opentlv_python_execution_size(PyObject* module, PyObject* args) {
    (void)module;
    PyObject*  capsule;
    Py_ssize_t depth, nodes;
    int        retained;
    if (!PyArg_ParseTuple(args, "Onnp", &capsule, &depth, &nodes, &retained)) return NULL;
    program* self = PyCapsule_GetPointer(capsule, PROGRAM_NAME);
    if (!self) return NULL;
    if (depth < 0 || nodes < 0) return failure(TLV_ERR_INVALID_ARG, NULL);
    size_t       bytes, alignment;
    tlv_result_t rc =
        retained
            ? tlv_query_eval_size(self->native, (size_t)depth, (size_t)nodes, &bytes, &alignment)
            : tlv_query_exec_size(self->native, (size_t)depth, &bytes, &alignment);
    if (rc != TLV_OK) return failure(rc, NULL);
    if (bytes > PY_SSIZE_T_MAX) return failure(TLV_ERR_NATIVE_SIZE, NULL);
    return Py_BuildValue("(nn)", (Py_ssize_t)bytes, (Py_ssize_t)alignment);
}
PyObject* opentlv_python_execution_bind(PyObject* module, PyObject* args) {
    (void)module;
    PyObject *  capsule, *value;
    const char* name;
    int         type;
    if (!PyArg_ParseTuple(args, "OsiO", &capsule, &name, &type, &value)) return NULL;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    int64_t    number = 0;
    char*      data = NULL;
    Py_ssize_t size = 0;
    if (type == TLV_QUERY_RESULT_INTEGER)
        number = PyLong_AsLongLong(value);
    else if (PyBytes_AsStringAndSize(value, &data, &size) < 0)
        return NULL;
    if (PyErr_Occurred()) return NULL;
    /* Append before publishing borrowed storage to C; failure leaves C untouched. */
    if (PyList_Append(self->bindings, value) < 0) return NULL;
    tlv_query_diagnostic_t diagnostic = {0};
    tlv_result_t rc = tlv_query_exec_bind(self->native, name, (tlv_query_result_kind_t)type, number,
                                          (const uint8_t*)data, (size_t)size, &diagnostic);
    if (rc != TLV_OK) return failure(rc, &diagnostic);
    return Py_NewRef(Py_None);
}
static PyObject* project(const tlv_tree_event_t* event) {
    if (event->element.tag.size > PY_SSIZE_T_MAX || event->element.value.size > PY_SSIZE_T_MAX)
        return failure(TLV_ERR_NATIVE_SIZE, NULL);
    return Py_BuildValue("(iy#y#nn)", event->kind,
                         event->element.tag.size ? event->element.tag.data : (const uint8_t*)"",
                         (Py_ssize_t)event->element.tag.size,
                         event->element.value.size ? event->element.value.data : (const uint8_t*)"",
                         (Py_ssize_t)event->element.value.size, (Py_ssize_t)event->depth,
                         (Py_ssize_t)event->offset);
}
static tlv_visit_result_t visit(const tlv_tree_event_t* event, void* context) {
    PyObject* item = project(event);
    if (!item) return TLV_VISIT_ERROR;
    PyObject* result = PyObject_CallFunctionObjArgs(context, item, NULL);
    Py_DECREF(item);
    if (!result) return TLV_VISIT_ERROR;
    long action = result == Py_None ? 0 : PyLong_AsLong(result);
    Py_DECREF(result);
    if (PyErr_Occurred()) return TLV_VISIT_ERROR;
    return action == 0 ? TLV_VISIT_CONTINUE : action == 1 ? TLV_VISIT_STOP : TLV_VISIT_ERROR;
}
PyObject* opentlv_python_execution_feed(PyObject* module, PyObject* args) {
    (void)module;
    PyObject * capsule, *tag, *value, *source;
    Py_ssize_t depth, offset;
    int        kind, skipped;
    if (!PyArg_ParseTuple(args, "OiOOnnOp", &capsule, &kind, &tag, &value, &depth, &offset, &source,
                          &skipped))
        return NULL;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    if (self->reader || self->document) return failure(TLV_ERR_INVALID_STATE, NULL);
    if (depth < 0 || offset < 0) return failure(TLV_ERR_INVALID_ARG, NULL);
    char *     tag_data, *value_data;
    Py_ssize_t tag_size, value_size;
    if (PyBytes_AsStringAndSize(tag, &tag_data, &tag_size) < 0 ||
        PyBytes_AsStringAndSize(value, &value_data, &value_size) < 0)
        return NULL;
    tlv_tree_event_t event = {0};
    event.kind = (tlv_tree_event_kind_t)kind;
    event.element.tag = tlv_tag((const uint8_t*)tag_data, (size_t)tag_size);
    event.element.value.data = (const uint8_t*)value_data;
    event.element.value.size = (tlv_size_t)value_size;
    event.depth = (size_t)depth;
    event.offset = (size_t)offset;
    event.skipped = skipped;
    if (source != Py_None) {
        const tlv_source_t* original = opentlv_python_source_pointer(source);
        if (!original) return NULL;
        event.source = *original;
    }
    if (PyList_Append(self->inputs, tag) < 0 || PyList_Append(self->inputs, value) < 0 ||
        PyList_Append(self->inputs, source) < 0)
        return NULL;
    int                    matched;
    tlv_query_diagnostic_t diagnostic = {0};
    self->busy = 1;
    tlv_result_t rc = tlv_query_exec_feed(self->native, &event, &matched, &diagnostic);
    self->busy = 0;
    if (rc != TLV_OK) return failure(rc, &diagnostic);
    if (!matched) return Py_NewRef(Py_None);
    program* query = PyCapsule_GetPointer(self->owner, PROGRAM_NAME);
    if (!query) return NULL;
    if (!self->retained && query->info.level == TLV_QUERY_S1) {
        rc = tlv_query_exec_selected(self->native, &event);
        if (rc != TLV_OK) return failure(rc, NULL);
    }
    return project(&event);
}
PyObject* opentlv_python_execution_finish(PyObject* module, PyObject* capsule) {
    (void)module;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    if (self->reader || self->document) return failure(TLV_ERR_INVALID_STATE, NULL);
    tlv_query_diagnostic_t diagnostic = {0};
    self->busy = 1;
    tlv_result_t rc = tlv_query_exec_finish(self->native, &diagnostic);
    self->busy = 0;
    if (rc != TLV_OK) return failure(rc, &diagnostic);
    return Py_NewRef(Py_None);
}
PyObject* opentlv_python_execution_visit(PyObject* module, PyObject* args) {
    (void)module;
    PyObject *capsule, *reader_capsule, *callback;
    int       existence;
    if (!PyArg_ParseTuple(args, "OOOi", &capsule, &reader_capsule, &callback, &existence))
        return NULL;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    if (self->document || (self->reader && self->reader != reader_capsule))
        return failure(TLV_ERR_INVALID_STATE, NULL);
    if (!existence && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "Query visitor must be callable");
        return NULL;
    }
    PyObject*          input;
    tlv_tree_reader_t* reader = opentlv_python_query_reader_begin(reader_capsule, &input);
    if (!reader) return NULL;
    if (PyList_Append(self->inputs, input) < 0) {
        opentlv_python_query_reader_end(reader_capsule);
        return NULL;
    }
    if (!self->reader) self->reader = Py_NewRef(reader_capsule);
    self->busy = 1;
    tlv_query_diagnostic_t diagnostic = {0};
    int                    found = 0;
    tlv_result_t           rc =
        existence
            ? tlv_query_program_exists(reader, self->native, existence == 2, &found, &diagnostic)
            : tlv_query_program_visit(reader, self->native, visit, callback, &diagnostic);
    self->busy = 0;
    opentlv_python_query_reader_end(reader_capsule);
    if (PyErr_Occurred()) return NULL;
    if (rc != TLV_OK) return failure(rc, &diagnostic);
    return existence ? PyBool_FromLong(found) : Py_NewRef(Py_None);
}
PyObject* opentlv_python_execution_info(PyObject* module, PyObject* capsule) {
    (void)module;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    tlv_query_exec_info_t info = {0};
    info.struct_size = sizeof info;
    tlv_result_t rc = tlv_query_exec_info(self->native, &info);
    if (rc != TLV_OK) return failure(rc, NULL);
    return Py_BuildValue("{s:n,s:n,s:n,s:i,s:i,s:i}", "elements", (Py_ssize_t)info.elements, "work",
                         (Py_ssize_t)info.work, "skipped_subtrees",
                         (Py_ssize_t)info.skipped_subtrees, "finished", info.finished,
                         "full_validation", info.full_validation, "invalid", info.invalid);
}
PyObject* opentlv_python_execution_result(PyObject* module, PyObject* capsule) {
    (void)module;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    tlv_query_result_t result;
    tlv_result_t       rc = tlv_query_exec_result(self->native, &result);
    if (rc != TLV_OK) return failure(rc, NULL);
    switch (result.kind) {
        case TLV_QUERY_RESULT_BOOL: return PyBool_FromLong(result.boolean);
        case TLV_QUERY_RESULT_INTEGER: return PyLong_FromLongLong(result.integer);
        case TLV_QUERY_RESULT_BYTES:
            return PyBytes_FromStringAndSize((const char*)result.data, (Py_ssize_t)result.size);
        case TLV_QUERY_RESULT_STRING:
            return PyUnicode_DecodeUTF8((const char*)result.data, (Py_ssize_t)result.size,
                                        "strict");
        default: PyErr_SetString(PyExc_TypeError, "node results use next()"); return NULL;
    }
}
PyObject* opentlv_python_execution_control(PyObject* module, PyObject* args) {
    (void)module;
    PyObject*  capsule;
    int        kind;
    Py_ssize_t value;
    if (!PyArg_ParseTuple(args, "Oin", &capsule, &kind, &value)) return NULL;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    if (value < 0) return failure(TLV_ERR_INVALID_ARG, NULL);
    tlv_result_t rc = kind == 0 ? tlv_query_exec_context(self->native, (size_t)value)
                                : tlv_query_exec_pruning(self->native, value != 0);
    if (rc != TLV_OK) return failure(rc, NULL);
    return Py_NewRef(Py_None);
}
PyObject* opentlv_python_execution_document(PyObject* module, PyObject* args) {
    (void)module;
    PyObject * capsule, *document_capsule, *context;
    Py_ssize_t value_capacity;
    if (!PyArg_ParseTuple(args, "OOOn", &capsule, &document_capsule, &context, &value_capacity))
        return NULL;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    if (self->reader || self->document) return failure(TLV_ERR_INVALID_STATE, NULL);
    if (!self->retained || value_capacity < 0) return failure(TLV_ERR_INVALID_ARG, NULL);
    tlv_document_t* document = opentlv_python_document_pointer(document_capsule);
    if (!document) return NULL;
    tlv_node_t* node = context == Py_None ? NULL : PyLong_AsVoidPtr(context);
    if (PyErr_Occurred()) return NULL;
    program* query = PyCapsule_GetPointer(self->owner, PROGRAM_NAME);
    if (!query) return NULL;
    tlv_tree_writer_workspace_t staging = {0};
    if (query->info.constructed_values_required) {
        release(&self->frames);
        release(&self->values);
        release(&self->staging_data);
        release(&self->staging_scratch);
        if (self->depth == SIZE_MAX || self->depth + 1 > SIZE_MAX / sizeof(tlv_tree_writer_frame_t))
            return failure(TLV_ERR_OVERFLOW, NULL);
        if (!allocate(&self->frames, (self->depth + 1) * sizeof(tlv_tree_writer_frame_t)) ||
            !allocate(&self->values, (size_t)value_capacity) ||
            !allocate(&self->staging_data, (size_t)value_capacity) ||
            !allocate(&self->staging_scratch, (size_t)value_capacity))
            return NULL;
        staging.frames = self->frames.data;
        staging.frame_capacity = self->depth + 1;
        staging.data = self->staging_data.data;
        staging.data_capacity = (size_t)value_capacity;
        staging.scratch = self->staging_scratch.data;
        staging.scratch_capacity = (size_t)value_capacity;
    }
    self->document = Py_NewRef(document_capsule);
    tlv_query_diagnostic_t diagnostic = {0};
    self->busy = 1;
    tlv_result_t rc = tlv_document_query_evaluate(
        document, self->native, node, self->values.data, self->values.size,
        query->info.constructed_values_required ? &staging : NULL, &diagnostic);
    self->busy = 0;
    if (rc != TLV_OK) return failure(rc, &diagnostic);
    return Py_NewRef(Py_None);
}
PyObject* opentlv_python_query_schema(PyObject* module, PyObject* args) {
    (void)module;
    PyObject * records, *input, *format_spec;
    Py_ssize_t depth, nodes, work, contexts, value_capacity;
    if (!PyArg_ParseTuple(args, "OOOnnnnn", &records, &input, &format_spec, &depth, &nodes, &work,
                          &contexts, &value_capacity))
        return NULL;
    if (!PyTuple_Check(records)) {
        PyErr_SetString(PyExc_TypeError, "immutable Query rule tuple required");
        return NULL;
    }
    if (depth < 0 || nodes < 0 || work < 0 || contexts < 0 || value_capacity < -1)
        return failure(TLV_ERR_INVALID_ARG, NULL);
    Py_ssize_t count = PyTuple_Size(records);
    if ((size_t)count > SIZE_MAX / sizeof(tlv_schema_query_rule_t))
        return failure(TLV_ERR_OVERFLOW, NULL);
    tlv_schema_query_rule_t* rules = count ? calloc((size_t)count, sizeof *rules) : NULL;
    if (count && !rules) return PyErr_NoMemory();
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject* record = PyTuple_GetItem(records, i);
        PyObject *context, *assertion, *name;
        if (!PyArg_ParseTuple(record, "OOO", &context, &assertion, &name)) {
            free(rules);
            return NULL;
        }
        program*    selector = PyCapsule_GetPointer(context, PROGRAM_NAME);
        program*    predicate = PyCapsule_GetPointer(assertion, PROGRAM_NAME);
        const char* label = PyUnicode_AsUTF8AndSize(name, NULL);
        if (!selector || !predicate || !label) {
            free(rules);
            return NULL;
        }
        rules[i] = (tlv_schema_query_rule_t){selector->native, predicate->native,
                                             &predicate->environment, label};
    }
    const uint8_t*  data = NULL;
    size_t          size = 0;
    tlv_document_t* document = NULL;
    if (PyBytes_Check(input)) {
        data = (const uint8_t*)PyBytes_AsString(input);
        size = (size_t)PyBytes_Size(input);
    } else
        document = opentlv_python_document_pointer(input);
    PyObject* format_owner = PyErr_Occurred() ? NULL : opentlv_python_format_owner(format_spec);
    const tlv_format_t* format = format_owner ? opentlv_python_format_pointer(format_owner) : NULL;
    if (PyErr_Occurred() || !format) {
        free(rules);
        Py_XDECREF(format_owner);
        return PyErr_Occurred() ? NULL : failure(TLV_ERR_UNSUPPORTED, NULL);
    }
    tlv_schema_query_diagnostic_t diagnostic;
    tlv_result_t                  rc = opentlv_binding_schema_run(
        data, size, document, format, rules, (size_t)count, (size_t)depth, (size_t)nodes,
        (size_t)work, (size_t)contexts, value_capacity < 0 ? 0 : (size_t)value_capacity,
        value_capacity < 0, &diagnostic);
    free(rules);
    Py_DECREF(format_owner);
    if (rc != TLV_OK) {
        if (PyErr_Occurred()) return NULL;
        /* Only a failed assertion has Schema detail; other failures report None. Its
         * common evidence (location, path, expected text) is the Query error's own. */
        const tlv_schema_detail_t* schema = &diagnostic.query.detail.schema;
        PyObject*                  detail =
            diagnostic.query.cause != TLV_QUERY_CAUSE_SCHEMA
                ? Py_NewRef(Py_None)
                : Py_BuildValue("{s:i,s:s,s:y#,s:z}", "kind", (int)schema->kind, "kind_name",
                                tlv_schema_issue_kind_string(schema->kind), "tag",
                                schema->tag.size ? (const char*)schema->tag.data : "",
                                (Py_ssize_t)schema->tag.size, "field", schema->field);
        if (!detail) return NULL;
        PyObject* details =
            Py_BuildValue("{s:n,s:N}", "rule", (Py_ssize_t)diagnostic.rule, "schema", detail);
        if (!details) return NULL;
        failure_fields(rc, &diagnostic.query, details);
        Py_DECREF(details);
        return NULL;
    }
    return Py_NewRef(Py_None);
}
PyObject* opentlv_python_execution_edit(PyObject* module, PyObject* args) {
    (void)module;
    PyObject * capsule, *tag, *value;
    int        kind;
    Py_ssize_t capacity;
    if (!PyArg_ParseTuple(args, "OiOOn", &capsule, &kind, &tag, &value, &capacity)) return NULL;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    if (!self->document || capacity < 0 || (size_t)capacity > SIZE_MAX / sizeof(tlv_node_t*))
        return failure(TLV_ERR_INVALID_ARG, NULL);
    tlv_document_t* document = opentlv_python_document_pointer(self->document);
    if (!document) return NULL;
    char *     tag_data, *value_data;
    Py_ssize_t tag_size, value_size;
    if (PyBytes_AsStringAndSize(tag, &tag_data, &tag_size) < 0 ||
        PyBytes_AsStringAndSize(value, &value_data, &value_size) < 0)
        return NULL;
    tlv_node_t** targets = capacity ? calloc((size_t)capacity, sizeof *targets) : NULL;
    if (capacity && !targets) return PyErr_NoMemory();
    size_t                 applied = 0;
    tlv_query_diagnostic_t diagnostic = {0};
    self->busy = 1;
    tlv_result_t rc = tlv_document_query_edit(
        document, self->native, (tlv_document_query_edit_kind_t)kind,
        tlv_tag((const uint8_t*)tag_data, (size_t)tag_size), (const uint8_t*)value_data,
        (size_t)value_size, targets, (size_t)capacity, &applied, &diagnostic);
    self->busy = 0;
    free(targets);
    if (rc != TLV_OK) {
        failure(rc, &diagnostic);
        PyObject *type, *error, *traceback;
        PyErr_Fetch(&type, &error, &traceback);
        PyErr_NormalizeException(&type, &error, &traceback);
        PyObject* error_args = error ? PyObject_GetAttrString(error, "args") : NULL;
        if (error_args && PyTuple_Size(error_args) > 0) {
            PyObject* fields = PyTuple_GetItem(error_args, 0);
            if (PyDict_Check(fields)) set_size(fields, "applied", applied);
        }
        Py_XDECREF(error_args);
        PyErr_Clear();
        PyErr_Restore(type, error, traceback);
        return NULL;
    }
    return PyLong_FromSize_t(applied);
}
PyObject* opentlv_python_execution_next(PyObject* module, PyObject* capsule) {
    (void)module;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    if (self->document) {
        tlv_node_t*            node;
        tlv_query_diagnostic_t diagnostic = {0};
        tlv_result_t           rc = tlv_document_query_next(self->native, &node, &diagnostic);
        if (rc != TLV_OK) return failure(rc, rc == TLV_END ? NULL : &diagnostic);
        return PyLong_FromVoidPtr(node);
    }
    tlv_tree_event_t event;
    tlv_result_t     rc = tlv_query_result_next(self->native, &event);
    if (rc != TLV_OK) return failure(rc, NULL);
    return project(&event);
}
PyObject* opentlv_python_execution_next_ordinal(PyObject* module, PyObject* capsule) {
    (void)module;
    execution* self = get_execution(capsule);
    if (!self) return NULL;
    tlv_tree_event_t event;
    size_t           ordinal;
    tlv_result_t     rc = tlv_query_result_next_ordinal(self->native, &event, &ordinal);
    if (rc != TLV_OK) return failure(rc, NULL);
    return Py_BuildValue("(Nn)", project(&event), (Py_ssize_t)ordinal);
}
