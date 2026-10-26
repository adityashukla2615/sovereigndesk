"""Fitted models kept on disk between runs, each for the data revision it was fitted on.

The MPC predictor takes several CPU-seconds to fit. On a small instance (Render's free plan
has a tenth of a CPU) that stalls the whole app, ticks and every command, for over a minute.
The one-service image therefore fits it at build time (``python -m app.sim.model_cache``) and
the app reads it back in a fraction of a second. A file is only read back for the revision it
was written for, and only from the configured directory, which only this app writes.
"""

import hashlib
import logging
import pickle
from collections.abc import Callable
from pathlib import Path
from typing import cast

from app.config import get_settings
from app.data.service import DataService
from app.db.session import make_engine, make_session_factory
from app.sim.mpc import build_mpc

log = logging.getLogger(__name__)


def cached[T](directory: Path | None, name: str, revision: str, build: Callable[[], T]) -> T:
    """The model ``name`` for this data revision: read from ``directory`` if it holds one,
    else built and written there. Without a directory it is simply built."""
    if directory is None:
        return build()
    digest = hashlib.sha256(revision.encode()).hexdigest()[:16]
    path = directory / f"{name}-{digest}.pkl"
    if path.exists():
        try:
            with path.open("rb") as f:
                # Trusted: written by this app, into its own directory, for this revision.
                return cast(T, pickle.load(f))  # noqa: S301
        except Exception as exc:  # a partial or foreign file: fit again
            log.warning("model cache %s unreadable, fitting again: %s", path.name, exc)
    model = build()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        with partial.open("wb") as f:
            pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)
        partial.replace(path)
    except OSError as exc:  # a read-only disk costs only the next fit
        log.warning("model cache %s not written: %s", path.name, exc)
    return model


def main() -> None:
    """Fit the slow models on the stored data into SD_MODEL_CACHE_DIR: the image's build step."""
    settings = get_settings()
    if settings.model_cache_dir is None:
        raise SystemExit("SD_MODEL_CACHE_DIR is not set")
    engine = make_engine(settings.database_url)
    service = DataService(settings, make_session_factory(engine), {})
    cached(settings.model_cache_dir, "mpc", service.revision(), lambda: build_mpc(service))
    engine.dispose()


if __name__ == "__main__":
    main()
