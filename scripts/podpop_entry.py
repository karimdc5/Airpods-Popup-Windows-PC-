"""PyInstaller entry point (the package's __main__ can't be frozen directly)."""

from podpop.__main__ import main

raise SystemExit(main())
