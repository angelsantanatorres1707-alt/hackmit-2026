"""Manim scene templates for the hint renderer.

The scene modules are also loaded BY PATH by the manim CLI (which gives them
no package context), so they import each other as top-level modules after
putting this directory on sys.path. This package does the same, which keeps
exactly one module object per file however the backend reaches it:

    from backend.scenes import TEMPLATES, validate_params, render
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import SceneParamError  # noqa: F401,E402
from registry import (  # noqa: F401,E402
    ALIASES,
    FALLBACK,
    RENDER_LOCK,
    TEMPLATES,
    get,
    render,
    render_with_fallback,
    resolve,
    selftest,
    validate_params,
)

__all__ = [
    "ALIASES", "FALLBACK", "RENDER_LOCK", "TEMPLATES", "SceneParamError",
    "get", "render", "render_with_fallback", "resolve", "selftest",
    "validate_params",
]
