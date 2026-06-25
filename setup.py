"""Setup.py shim for environments that don't fully support PEP 517.

Modern installs should use ``pip install .`` which reads pyproject.toml
directly. This file exists as a fallback for:
  * Very old pip versions (< 21)
  * Tools that explicitly invoke ``python setup.py``
  * Editable installs on quirky environments

It does NOT duplicate metadata from pyproject.toml — it delegates entirely
to setuptools, which reads pyproject.toml when present.
"""

from setuptools import setup

setup()
