"""Unit tests for covariance estimators (portfolio.covariance, QV-054) — pure NumPy, no DB.

Ledoit-Wolf shrinkage is validated three ways: structural (symmetric + PSD), behavioural
(shrinks harder as the sample shrinks — risk R7), and a bit-exact cross-check against
``sklearn.covariance.LedoitWolf`` (dev-only, skipped if sklearn is absent — never a prod dep).
"""

from __future__ import annotations

import numpy as np
import pytest

from quantvista.portfolio.covariance import (
    CovarianceEstimator,
    LedoitWolfEstimator,
    SampleCovarianceEstimator,
    ledoit_wolf,
)


def _returns(n_samples: int, n_features: int, *, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # a factor + idiosyncratic noise → a realistic, non-diagonal covariance
    factor = rng.standard_normal((n_samples, 1))
    loadings = rng.uniform(0.5, 1.5, (1, n_features))
    noise = rng.standard_normal((n_samples, n_features)) * 0.5
    return (factor @ loadings + noise) * 0.02


def test_estimators_satisfy_protocol() -> None:
    assert isinstance(LedoitWolfEstimator(), CovarianceEstimator)
    assert isinstance(SampleCovarianceEstimator(), CovarianceEstimator)


def test_ledoit_wolf_is_symmetric() -> None:
    cov = LedoitWolfEstimator().estimate(_returns(120, 10))
    assert np.allclose(cov, cov.T)


def test_ledoit_wolf_is_psd() -> None:
    cov = LedoitWolfEstimator().estimate(_returns(60, 25))  # n≈T: sample cov would be unstable
    assert np.linalg.eigvalsh(cov).min() >= -1e-10


def test_shrinkage_intensity_in_unit_interval() -> None:
    _, delta = ledoit_wolf(_returns(80, 15))
    assert 0.0 <= delta <= 1.0


def test_shrinkage_grows_as_sample_shrinks() -> None:
    # fewer observations relative to assets → sample cov noisier → shrink harder (R7)
    _, delta_large = ledoit_wolf(_returns(500, 20, seed=1))
    _, delta_small = ledoit_wolf(_returns(30, 20, seed=1))
    assert delta_small > delta_large


def test_single_asset_returns_scalar_variance() -> None:
    cov = LedoitWolfEstimator().estimate(_returns(50, 1))
    assert cov.shape == (1, 1)
    assert cov[0, 0] > 0


def test_zero_variance_column_does_not_crash() -> None:
    r = _returns(40, 4)
    r[:, 2] = 0.0  # a constant (zero-variance) asset
    cov = LedoitWolfEstimator().estimate(r)
    assert np.all(np.isfinite(cov))
    assert np.allclose(cov, cov.T)


def test_sample_covariance_baseline_is_symmetric_psd() -> None:
    cov = SampleCovarianceEstimator().estimate(_returns(200, 8))
    assert np.allclose(cov, cov.T)
    assert np.linalg.eigvalsh(cov).min() >= -1e-10


def test_sample_covariance_single_asset() -> None:
    cov = SampleCovarianceEstimator().estimate(_returns(50, 1))
    assert cov.shape == (1, 1)
    assert cov[0, 0] > 0


def test_ledoit_wolf_matches_sklearn() -> None:
    sklearn_cov = pytest.importorskip("sklearn.covariance")
    r = _returns(90, 12, seed=7)
    mine, my_delta = ledoit_wolf(r)
    ref = sklearn_cov.LedoitWolf().fit(r)
    assert np.allclose(mine, ref.covariance_, atol=1e-10)
    assert abs(my_delta - ref.shrinkage_) < 1e-10
