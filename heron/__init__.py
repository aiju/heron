"""Heron: the importable side of the repository.

The package's subpackages are the repository's top-level folders: `infra/`
is heron.infra, `studies/` is heron.studies, and so on. This file adds the
repository root to the package's search path, so a plain checkout works
from the root (`python3 -m heron ...`) without installing anything;
`pip install -e .` does the same from anywhere and adds a `heron` command.
"""

import os as _os

__path__.append(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

ROOT = __path__[-1]
"""The repository root."""

BUILD = _os.path.join(ROOT, "build")
"""Generated files: ROM images, netlists, simulator binaries, scratch."""
