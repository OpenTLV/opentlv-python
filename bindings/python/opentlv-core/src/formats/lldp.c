// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel

#include "../format.h"
#include <tlv/builtins/lldp/lldp.h>

const tlv_format_t* opentlv_python_format_lldp(void) {
    return &tlv_format_lldp;
}
