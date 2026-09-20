"""Alias module: SCENE_CATALOG.md calls the shared helpers ``common.py``,
the build task calls them ``helpers.py``. One implementation, two names, so
neither document is wrong and there is still exactly one module object.

    from common import TextMatrix, fmt_num      # == from helpers import ...
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import helpers as _helpers  # noqa: E402

# Re-export every public name, without a star import (which would hide typos
# from pyflakes for anything that imports this module).
globals().update({k: v for k, v in vars(_helpers).items()
                  if not k.startswith("_")})
__all__ = [k for k in vars(_helpers) if not k.startswith("_")]
