"""portfolio — covariance estimators (QV-054).

The optimizer needs a covariance matrix Σ from a returns matrix. The plain **sample** covariance
is unstable when the number of assets approaches the number of observations (risk R7, ``09`` §5),
so the default is the **Ledoit-Wolf shrinkage** estimator: Σ = (1−δ)·S + δ·μ·I, shrinking the
sample covariance ``S`` toward the well-conditioned scaled-identity target (``μ = trace(S)/N``).
The shrinkage intensity δ ∈ [0, 1] is estimated analytically (Ledoit & Wolf, 2004).

Estimators sit behind a ``CovarianceEstimator`` Protocol so the optimizer never hard-codes one —
OAS / EWMA / factor-model estimators can be added later without touching the optimizer (the
pluggable seam agreed for the Epic-7 optimizer family). Pure NumPy; no scikit-learn in prod (our
hand-rolled Ledoit-Wolf is bit-exact vs ``sklearn.covariance.LedoitWolf``, verified in a dev test).

Convention: ``returns`` is shaped ``(T observations, N assets)`` — same as sklearn's ``X``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

FloatMatrix = NDArray[np.float64]


@runtime_checkable
class CovarianceEstimator(Protocol):
    """Turns a ``(T, N)`` returns matrix into an ``(N, N)`` covariance matrix."""

    def estimate(self, returns: FloatMatrix) -> FloatMatrix: ...


def _empirical_covariance(centered: FloatMatrix, n_samples: int) -> FloatMatrix:
    """MLE covariance (divides by ``n``, matching the Ledoit-Wolf derivation)."""
    cov: FloatMatrix = centered.T @ centered / n_samples
    return cov


def ledoit_wolf(returns: FloatMatrix) -> tuple[FloatMatrix, float]:
    """Return ``(shrunk_covariance, shrinkage_intensity)`` (Ledoit-Wolf, scaled-identity target).

    A faithful (non-blocked) reproduction of ``sklearn.covariance.ledoit_wolf`` — bit-exact within
    ``1e-10`` (cross-checked in tests) but with no scikit-learn dependency in production. Our
    universes (≤ ~200 names) are far below sklearn's 1000-column block threshold, so the single-pass
    form is exact.
    """
    X = np.asarray(returns, dtype=np.float64)
    n_samples, n_features = X.shape

    # One feature → shrinkage is irrelevant; return the plain variance.
    if n_features == 1:
        centered_1d = X - X.mean(0)
        return _empirical_covariance(centered_1d, n_samples), 0.0

    centered = X - X.mean(0)
    emp_cov = _empirical_covariance(centered, n_samples)
    mu = float(np.trace(emp_cov)) / n_features

    # Analytic shrinkage intensity δ (Ledoit-Wolf 2004), single-pass form.
    X2 = centered**2
    emp_cov_trace = np.sum(X2, axis=0) / n_samples
    beta_ = float(np.sum(X2.T @ X2))
    delta_ = float(np.sum((centered.T @ centered) ** 2)) / n_samples**2
    beta = 1.0 / (n_features * n_samples) * (beta_ / n_samples - delta_)
    delta = delta_ - 2.0 * mu * float(emp_cov_trace.sum()) + n_features * mu**2
    delta /= n_features
    beta = min(beta, delta)  # never shrink past 1 (would invert covariances)
    shrinkage = 0.0 if beta == 0 else beta / delta

    shrunk = (1.0 - shrinkage) * emp_cov
    shrunk.flat[:: n_features + 1] += shrinkage * mu  # add δ·μ to the diagonal
    return shrunk, shrinkage


class LedoitWolfEstimator:
    """Ledoit-Wolf shrinkage covariance — the default (stable when N approaches T)."""

    def estimate(self, returns: FloatMatrix) -> FloatMatrix:
        return ledoit_wolf(returns)[0]


class SampleCovarianceEstimator:
    """Plain unbiased sample covariance — a baseline; unstable for N ≈ T (prefer Ledoit-Wolf)."""

    def estimate(self, returns: FloatMatrix) -> FloatMatrix:
        X = np.asarray(returns, dtype=np.float64)
        if X.shape[1] == 1:
            centered = X - X.mean(0)
            return _empirical_covariance(centered, X.shape[0])
        cov: FloatMatrix = np.cov(X, rowvar=False, ddof=1)
        return np.atleast_2d(cov)


__all__ = [
    "CovarianceEstimator",
    "FloatMatrix",
    "LedoitWolfEstimator",
    "SampleCovarianceEstimator",
    "ledoit_wolf",
]
