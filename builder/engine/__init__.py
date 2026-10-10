"""Rule engine: calendar core, customer text resolution, call state machine, snippet renderer.

Pure Python, standard library only (json, re, datetime). The same sources are concatenated by
snippet.render() into one self-contained code_exec snippet, so no module here may import anything
else, contain the sequences "{{" or "}}", or rely on package-relative names at run time beyond the
explicit `from .x import ...` lines that the renderer strips.
"""
from .step import step, new_state  # noqa: F401
from .snippet import render  # noqa: F401
