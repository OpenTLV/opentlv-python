# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marek Cingel

"""Sequential Reader over the canonical C cursor."""
import _opentlv as _native
from opentlv.cursor import Decoded, _Cursor
from opentlv.error import NeedMoreDataError, OpenTLVError


class Reader(_Cursor):
    """Iterate Elements using the C Reader cursor.

    Bytes are retained without copying; other buffers are snapshotted. Views
    retain storage after Reader deletion or input replacement. final_input=False
    enables incremental input. NeedMoreDataError permits set_input() and retry.
    Other errors stop convenience iteration; read_source() permits explicit retry.
    """
    __slots__ = ("_failed",)

    def __init__(self, data, format=None, *, final_input=True):
        super().__init__(data, format, final_input=final_input)
        self._failed = False

    def read_source(self) -> Decoded:
        """Pull content and Layout in one decode, or raise a diagnostic/StopIteration."""
        return self._pull().decoded

    def __iter__(self):
        return self

    def visit(self, callback) -> None:
        """C Visitor processing; callback(element) returns Visit or None.

        Callback values are owned snapshots. STOP consumes the current element;
        subsequent visits resume without replay. Callback exceptions propagate.
        """
        self._visit(callback, False)

    def __next__(self):
        if self._failed:
            raise StopIteration
        try:
            return self.read_source().element
        except NeedMoreDataError:
            raise
        except OpenTLVError:
            self._failed = True
            raise
def read(data, format=None):
    """Read one complete Element and Layout through C; trailing bytes are unread.

    Returns Decoded; len(result.encoded) is the consumed byte count.
    Empty input raises EndError rather than iterator StopIteration.
    """
    from opentlv.error import EndError
    try:
        return Reader(data, format).read_source()
    except StopIteration:
        raise EndError(_native.RESULT_END) from None
