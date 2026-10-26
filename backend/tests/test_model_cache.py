"""Fitted models kept on disk, each for the data revision it was fitted on."""

from pathlib import Path

from app.sim.model_cache import cached


def test_a_model_is_read_back_for_its_revision_and_fitted_again_for_new_data(
    tmp_path: Path,
) -> None:
    fits: list[int] = []

    def fit() -> dict[str, int]:
        fits.append(1)
        return {"fit": len(fits)}

    assert cached(tmp_path, "mpc", "100@2026-10-19", fit) == {"fit": 1}
    assert cached(tmp_path, "mpc", "100@2026-10-19", fit) == {"fit": 1}  # read, not refitted
    assert cached(tmp_path, "mpc", "101@2026-10-20", fit) == {"fit": 2}  # new data, new fit
    assert len(fits) == 2
    assert cached(None, "mpc", "100@2026-10-19", fit) == {"fit": 3}  # no directory: always fit


def test_an_unreadable_file_is_fitted_again(tmp_path: Path) -> None:
    cached(tmp_path, "mpc", "rev", lambda: 1)
    (path,) = tmp_path.glob("mpc-*.pkl")
    path.write_bytes(b"not a model")
    assert cached(tmp_path, "mpc", "rev", lambda: 2) == 2
    assert cached(tmp_path, "mpc", "rev", lambda: 3) == 2  # the good fit replaced it
