// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
#ifndef OPENTLV_BINDING_PATH_QUERY_H
#define OPENTLV_BINDING_PATH_QUERY_H

/* A V1 path that cannot become a matcher is a Query failure, not a Reader failure.
 * Bindings report it through their Query error projection: the Query kind of the
 * result, the EXPRESSION location tlv_query_parse_n() reported and no lower-layer
 * cause. This covers rejected path text and a failed tlv_query_matcher_init(),
 * whose result (for example an argument failure) has no location. */
#include <tlv/query/program.h>
#include <tlv/query/query.h>

/* `text` and `size` are the parsed path, or NULL and 0 when no text was parsed. A
 * LIMIT failure names the exhausted bound like other Query limits: the parser
 * rejects the step at index TLV_QUERY_MAX_STEPS with "path-steps", and any
 * earlier step only because the tag bytes would exceed TLV_QUERY_MAX_BYTES. */
static inline tlv_query_diagnostic_t opentlv_binding_path_failure(tlv_result_t            code,
                                                                  const tlv_diagnostic_t* parse,
                                                                  const char* text, size_t size) {
    tlv_query_diagnostic_t diagnostic = {0};
    if (parse) diagnostic.diagnostic = *parse;
    diagnostic.diagnostic.code = code;
    diagnostic.kind = code == TLV_ERR_SYNTAX  ? TLV_QUERY_ERROR_SYNTAX
                      : code == TLV_ERR_LIMIT ? TLV_QUERY_ERROR_LIMIT
                                              : TLV_QUERY_ERROR_ARGUMENT;
    diagnostic.cause = TLV_QUERY_CAUSE_NONE;
    if (code == TLV_ERR_LIMIT) {
        size_t step = 0, end = diagnostic.diagnostic.location.begin;
        for (size_t i = 0; text && i < end && i < size; ++i) step += text[i] == '/';
        diagnostic.limit = step >= TLV_QUERY_MAX_STEPS ? "path-steps" : "path-bytes";
        diagnostic.configured =
            step >= TLV_QUERY_MAX_STEPS ? TLV_QUERY_MAX_STEPS : TLV_QUERY_MAX_BYTES;
    }
    return diagnostic;
}
#endif
