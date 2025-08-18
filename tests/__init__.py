"""Test package configuration.

This module configures warnings filtering for the test suite. Some of the
dependencies used by the project expose SWIG-generated types (e.g. PyMuPDF)
that currently lack the ``__module__`` attribute, which triggers warnings on
recent Python versions. These warnings originate outside this repository, so
they are silenced here to keep the test output focused on actionable issues.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    message=r".*(SwigPyObject|SwigPyPacked|swigvarlink).*__module__.*",
)
