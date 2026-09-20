"""Alias module: SCENE_CATALOG.md calls the shared helpers ``common.py``,
the build task calls them ``helpers.py``. One implementation, two names, so
neither document is wrong and there is still exactly one module object.

    from common import TextMatrix, fmt_num      # == from helpers import ...

Also the home of REVEAL_CORRECT_VALUES (see below).
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

# ---------------------------------------------------------------------------
# REVEAL_CORRECT_VALUES -- the one switch that puts the answer back on screen.
#
# DEFAULT False, and it must stay False: the product's entire promise is that
# the student SEES the divergence geometrically and works out the fix. The
# reference panel therefore shows geometry and a masked "?" where the correct
# matrix / determinant / eigenvalue / solution / dimension / projection would
# otherwise be printed. The student's OWN matrix is always shown -- that is
# their work, not the answer.
#
# Turn it on for debugging, or for a future "show me the answer" escalation:
#
#     REVEAL_CORRECT_VALUES=1 .venv/bin/manim -qm ... grid_transform.py \
#         GridTransformCompare          # env var, one render
#
#     import common; common.REVEAL_CORRECT_VALUES = True   # in-process
#
# Templates never read this name directly; they call
# ``reveal_correct_values()``, which honours the env var, this flag and the
# identical one on ``helpers`` (same module, two names).
# ---------------------------------------------------------------------------
REVEAL_CORRECT_VALUES = _helpers.REVEAL_CORRECT_VALUES   # False
