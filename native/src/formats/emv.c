// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#include "../format.h"
#include <tlv/builtins/emv/format.h>

const tlv_format_t* opentlv_python_format_emv(void) {
    return &tlv_format_emv;
}
