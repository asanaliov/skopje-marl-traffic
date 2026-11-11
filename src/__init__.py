"""Core package for the Skopje traffic-control project."""

import os

if os.environ.get("SKOPJE_LIBSUMO") == "1":
    # libsumo bundles a newer sqlite3.dll than python's; on windows it only loads
    # if it comes first, before anything imports sqlite3 (filelock does)
    import libsumo  # noqa: F401
