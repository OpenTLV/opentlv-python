// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
#ifndef OPENTLV_BINDING_QUERY_SCHEMA_H
#define OPENTLV_BINDING_QUERY_SCHEMA_H

/* Owning facade storage adaptation only. The C Schema/Query engine performs
 * selection, contextual evaluation and diagnostics. This header is outside
 * the allocation-free production compiler/loader/execution boundary. */
#include <tlv/schema/query.h>
#include <stdlib.h>
#include <string.h>

static inline void* opentlv_binding_aligned(size_t size, void** allocation) {
    if (size > SIZE_MAX - 15) return NULL;
    *allocation = malloc(size + 15);
    return *allocation ? (void*)(((uintptr_t)*allocation + 15) & ~(uintptr_t)15) : NULL;
}

static inline tlv_result_t
opentlv_binding_schema_run(const uint8_t* data, size_t size, const void* document,
                           const tlv_format_t* format, const tlv_schema_query_rule_t* rules,
                           size_t count, size_t depth, size_t nodes, size_t work, size_t contexts,
                           size_t value_capacity, int measure_values,
                           tlv_schema_query_diagnostic_t* diagnostic) {
    if (diagnostic) memset(diagnostic, 0, sizeof *diagnostic);
    size_t       selector, assertion, alignment;
    tlv_result_t rc =
        tlv_schema_query_size(rules, count, depth, nodes, &selector, &assertion, &alignment);
    if (rc != TLV_OK) return rc;
    if (depth == SIZE_MAX || depth + 1 > SIZE_MAX / sizeof(tlv_tree_frame_t) ||
        contexts > SIZE_MAX / sizeof(tlv_schema_query_context_t))
        return TLV_ERR_OVERFLOW;
    tlv_schema_query_workspace_t workspace = {0};
    void *                       selector_owner = NULL, *assertion_owner = NULL;
    workspace.selector = opentlv_binding_aligned(selector, &selector_owner);
    workspace.assertion = opentlv_binding_aligned(assertion, &assertion_owner);
    workspace.selector_size = selector;
    workspace.assertion_size = assertion;
    workspace.contexts = contexts ? calloc(contexts, sizeof *workspace.contexts) : NULL;
    workspace.context_capacity = contexts;
    workspace.frames = calloc(depth + 1, sizeof *workspace.frames);
    workspace.frame_capacity = depth + 1;
    if (!workspace.selector || !workspace.assertion || !workspace.frames ||
        (contexts && !workspace.contexts))
        rc = TLV_ERR_OUT_OF_MEMORY;
#if OPENTLV_DOCUMENT
    tlv_tree_writer_workspace_t staging = {0};
    uint8_t*                    values = NULL;
    if (rc == TLV_OK && document) {
        if (depth + 1 > SIZE_MAX / sizeof *staging.frames) rc = TLV_ERR_OVERFLOW;
        if (rc == TLV_OK && measure_values)
            rc = tlv_document_encoded_size(document, &value_capacity);
        if (rc == TLV_OK) {
            staging.frames = calloc(depth + 1, sizeof *staging.frames);
            staging.frame_capacity = depth + 1;
            values = malloc(value_capacity ? value_capacity : 1);
            staging.data = malloc(value_capacity ? value_capacity : 1);
            staging.data_capacity = value_capacity;
            staging.scratch = malloc(value_capacity ? value_capacity : 1);
            staging.scratch_capacity = value_capacity;
            if (!staging.frames || !values || !staging.data || !staging.scratch)
                rc = TLV_ERR_OUT_OF_MEMORY;
        }
        if (rc == TLV_OK)
            rc = tlv_schema_query_validate_document(document, rules, count, depth, nodes, work,
                                                    &workspace, values, value_capacity, &staging,
                                                    diagnostic);
    } else if (rc == TLV_OK)
        rc = tlv_schema_query_validate_buffer(data, size, format, rules, count, depth, nodes, work,
                                              &workspace, diagnostic);
    free(staging.frames);
    free(values);
    free(staging.data);
    free(staging.scratch);
#else
    (void)value_capacity;
    (void)measure_values;
    if (rc == TLV_OK)
        rc = document ? TLV_ERR_UNSUPPORTED
                      : tlv_schema_query_validate_buffer(data, size, format, rules, count, depth,
                                                         nodes, work, &workspace, diagnostic);
#endif
    free(workspace.frames);
    free(workspace.contexts);
    free(selector_owner);
    free(assertion_owner);
    return rc;
}
#endif
