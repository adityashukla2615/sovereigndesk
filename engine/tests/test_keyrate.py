import numpy as np
import pytest

from sovereign_engine.bonds.cashflows import CashFlows
from sovereign_engine.bonds.keyrate import key_rate_durations, key_rate_weights, price_on_curve
from sovereign_engine.curves.nss import NelsonSiegelSvensson

CURVE = NelsonSiegelSvensson(0.045, -0.01, 0.012, 0.02, 1.8, 12.0)
KEYS = np.array([0.5, 2, 5, 10, 30.0])


def test_weights_partition_unity() -> None:
    t = np.linspace(0.01, 40, 200)
    w = key_rate_weights(t, KEYS)
    assert w.shape == (KEYS.size, t.size)
    assert np.allclose(w.sum(axis=0), 1.0)
    assert np.allclose(key_rate_weights(KEYS, KEYS), np.eye(KEYS.size))


def test_krds_add_up_to_parallel_duration() -> None:
    # Additivity is exact in the limit h → 0; separate and joint bumps differ at O(h²·T²).
    bond = CashFlows.bullet(0.04, periods=40, freq=2, first_period=0.3)
    h = 1e-6
    krd = key_rate_durations(bond, CURVE, KEYS, bump=h)
    t, z = bond.times, CURVE.zero_rate(bond.times)
    up = bond.amounts @ np.exp(-(z + h) * t)
    down = bond.amounts @ np.exp(-(z - h) * t)
    parallel = -(up - down) / (2 * h * price_on_curve(bond, CURVE))
    assert krd.sum() == pytest.approx(parallel, rel=1e-9)
    assert np.all(krd >= 0)


def test_zero_coupon_at_a_key_loads_only_that_key() -> None:
    zero = CashFlows(times=np.array([10.0]), amounts=np.array([100.0]))
    h = 1e-4
    krd = key_rate_durations(zero, CURVE, KEYS, bump=h)
    # Central difference of e^(−zT): sinh(hT)/h, which tends to the duration T as h → 0.
    assert krd[3] == pytest.approx(np.sinh(h * 10.0) / h, rel=1e-10)
    assert np.allclose(np.delete(krd, 3), 0.0)


def test_price_on_curve() -> None:
    bond = CashFlows.bullet(0.05, periods=6, freq=2)
    assert price_on_curve(bond, CURVE) == pytest.approx(
        float(bond.amounts @ CURVE.discount(bond.times))
    )
