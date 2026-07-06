"""TTS backends package.

Backend modules are auto-discovered and imported here.
Each backend module registers itself with the global registry
when imported.
"""

import importlib
import pkgutil


def _discover_backends():
    """Import all modules in this package to trigger their registration."""
    package = __name__
    for _importer, modname, _ispkg in pkgutil.iter_modules(path=__path__):
        importlib.import_module(f"{package}.{modname}")


_discover_backends()

