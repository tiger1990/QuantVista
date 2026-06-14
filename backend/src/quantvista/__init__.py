"""QuantVista backend — modular monolith.

Each bounded context under this package (identity, market_data, news, analytics,
portfolio, alerts, core) is a hard seam: contexts talk only through one another's
``interfaces`` module (Protocol/ABC) or domain events — never another context's
models, services, repositories, or DB tables. The allowed dependency DAG is enforced
in CI by import-linter (see ``backend/.importlinter``).
"""
