// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Marek Cingel
#ifndef OPENTLV_PYTHON_LOCATION_H
#define OPENTLV_PYTHON_LOCATION_H
#include <Python.h>
#include <tlv/diagnostic.h>

static inline PyObject* opentlv_python_location(const tlv_location_t* location) {
    tlv_location_t unknown = {0};
    if (!location) location = &unknown;
    int known = location->kind != TLV_LOCATION_UNKNOWN;
    return Py_BuildValue("{s:s,s:s,s:N,s:N}", "domain",
                         tlv_location_domain_string(location->domain), "kind",
                         tlv_location_kind_string(location->kind), "begin",
                         known ? PyLong_FromSize_t(location->begin) : Py_NewRef(Py_None), "end",
                         known ? PyLong_FromSize_t(location->end) : Py_NewRef(Py_None));
}
#endif
