"""ml — machine-learning augmentation of the factor model (Epic 9).

Sits ABOVE `analytics` in the bounded-context DAG: it reads the persisted PIT factor snapshot and
market data, and nothing reads it back. ML is an *additional* signal — the transparent factor
composite remains the explainable default (`05` §5), so nothing here may alter scoring.
"""
