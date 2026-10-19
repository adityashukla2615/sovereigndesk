"""Typing aliases shared across the engine."""

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]
type ArrayLike = npt.ArrayLike


def as_float_array(values: ArrayLike) -> FloatArray:
    """Coerce to a float64 ndarray (no copy when already one).

    Equation:
        x ↦ x as IEEE-754 double precision
    """
    return np.asarray(values, dtype=np.float64)
