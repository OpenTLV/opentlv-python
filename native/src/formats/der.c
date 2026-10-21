// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#include "../format.h"
#include <tlv/builtins/asn1/der.h>

const tlv_format_t* opentlv_python_format_der(void) {
    return &tlv_format_der;
}
