from PyMuPDF import fitz as _fitz  # type: ignore
globals().update(_fitz.__dict__)
