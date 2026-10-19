"""Meta-tests that hold the engine to the project's quality bar.

* Every public function must document its formula in an ``Equation:`` docstring section.
* The engine stays pure: importing it must not pull in I/O, web or database libraries.
"""

import importlib
import inspect
import pkgutil
import subprocess
import sys
from collections.abc import Iterator
from types import FunctionType, ModuleType

import sovereign_engine

FORBIDDEN_IMPORTS = (
    *("httpx", "httpx2", "requests", "urllib3"),
    *("fastapi", "sqlalchemy", "redis", "app"),
)


def _engine_modules() -> Iterator[ModuleType]:
    yield sovereign_engine
    for info in pkgutil.walk_packages(sovereign_engine.__path__, prefix="sovereign_engine."):
        yield importlib.import_module(info.name)


def _public_functions(module: ModuleType) -> Iterator[FunctionType]:
    """Module-level functions and the public methods of module-level classes (not protocols)."""
    for name, obj in vars(module).items():
        if name.startswith("_") or getattr(obj, "__module__", None) != module.__name__:
            continue  # private, or a re-export that is checked in its home module
        if isinstance(obj, FunctionType):
            yield obj
        elif inspect.isclass(obj) and not getattr(obj, "_is_protocol", False):
            for attr, member in vars(obj).items():
                fn = member.__func__ if isinstance(member, classmethod | staticmethod) else member
                if not attr.startswith("_") and isinstance(fn, FunctionType):
                    yield fn


def test_every_public_function_documents_its_equation() -> None:
    missing = [
        f"{fn.__module__}.{fn.__qualname__}"
        for module in _engine_modules()
        for fn in _public_functions(module)
        if "Equation:" not in (inspect.getdoc(fn) or "")
    ]
    assert not missing, "public engine functions without an 'Equation:' docstring section:\n" + (
        "\n".join(missing)
    )


def test_engine_imports_no_io_libraries() -> None:
    probe = (
        "import importlib, pkgutil, sys, sovereign_engine\n"
        "for i in pkgutil.walk_packages(sovereign_engine.__path__, 'sovereign_engine.'):\n"
        "    importlib.import_module(i.name)\n"
        f"bad = sorted(m for m in {FORBIDDEN_IMPORTS!r} if m in sys.modules)\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed probe script, our own interpreter
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"engine imported I/O modules: {result.stdout.strip()}"
