// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#include "../format.h"
#include <tlv/builtins/asn1/cer.h>

const tlv_format_t* opentlv_python_format_cer(void) {
    return &tlv_format_cer;
}
