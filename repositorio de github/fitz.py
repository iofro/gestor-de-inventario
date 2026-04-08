"""Compatibility wrapper for the :mod:`fitz` bindings from PyMuPDF.

PyMuPDF changed its top level package name from ``PyMuPDF`` to
``pymupdf`` starting with version 1.22. Older installations still export
the bindings via ``PyMuPDF``.  This small wrapper tries the new import
first and falls back to the legacy location so the rest of the code can
simply ``import fitz`` regardless of the installed version.
"""

try:  # PyMuPDF >= 1.22
    import pymupdf as _fitz  # type: ignore
except ModuleNotFoundError:  # Older versions
    from PyMuPDF import fitz as _fitz  # type: ignore

globals().update(_fitz.__dict__)
