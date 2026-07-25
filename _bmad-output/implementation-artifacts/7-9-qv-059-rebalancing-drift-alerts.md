---
baseline_commit: 64d26c5e8b7fe9f7a93d0a1a480324cb21d4fca8
---

# Story 7.9: QV-059 — Rebalancing + drift alerts

Status: done

**Epic:** EPIC-PORT (Epic 7) · **Points:** 5 · **Depends:** QV-058 (RiskEngine + `compute_portfolio_weights`), QV-048 (alert evaluation + `insert_alert_event`)

## Story

As a user, I want suggested trades to reach target weights and drift alerts, so I stay on plan.

## Acceptance Criteria

1. **`POST /portfolios/{id}/rebalance`** — returns a `RebalancePlan` containing:
   - `as_of_date` (str): the latest available price date used
   - `total_drift` (str, Decimal): Σ|w_current_i − t_normalized_i|/2 over all positions that have a `target_weight`; 0 = balanced, 0.5 = entirely off-target
   - `needs_rebalance` (bool): `total_drift > drift_threshold`
   - `trades` (list): only positions where `|w_current_i − t_normalized_i| > drift_threshold`; each entry has `stock_id`, `symbol`, `direction` ("buy"|"sell"), `current_weight` (str), `target_weight` (str, normalized), `delta_weight` (str, signed: positive=buy)
   - Body: `{ "drift_threshold": 0.05 }` — optional, default 5%, must be in [0, 1]
   - 404 when portfolio is unknown/foreign (invisible via RLS → same "doesn't exist" response as other portfolio endpoints)
   - 422 (`validation_error`) when portfolio has no positions
   - 422 (`validation_error`) when no positions have `target_weight` set (user must run /optimize first)
   - 422 (`validation_error`) when no price data is available
   - No entitlement gate (rebalancing is a basic portfolio feature; no `rebalance` key in seed)
   - Disclaimer header + meta (same pattern as risk/optimize)
   - Trades sorted descending by `|delta_weight|` (largest first)
   [Source: `04` §3.5; `05` §1.3; sprint-07 QV-059]

2. **Portfolio drift alert type wired into `evaluate_alerts`**:
   - `"drift"` added to the `METRICS` allow-list in `alerts/rules.py` (so `validate_condition` accepts it)
   - `AlertEvaluationService.evaluate` (in `alerts/services.py`) handles `scope == "portfolio"` rules:
     - Fetches positions + latest PIT closes for all active portfolio-scope rules in one bulk query (`portfolio_drift_metrics` in `alerts/repositories.py`)
     - For each rule with `condition.metric == "drift"`: uses `matches(drift, op, threshold)` (the existing `evaluation.matches` function)
     - On match: calls existing `insert_alert_event(...)` with `type="portfolio_drift_alert"` payload and the same `dedup_key = as_of.isoformat()` as stock alerts
   - Cross-tenant safety: portfolio rules are read from the privileged (RLS-bypassing) session, identical to the existing stock-scope path
   - No migration needed: `alert_rules.scope IN ('stock','portfolio')` is already in migration 0010; `condition` is flexible jsonb
   [Source: `04` §3.7; `06` job catalog; QV-048]

3. **Tests**:
   - Unit tests for `RebalanceEngine`: drift math, threshold filtering, buy/sell direction, no-target-weight → None, `portfolio_total_drift` helper
   - Unit test: `validate_condition({"metric":"drift","op":"gte","value":0.1})` succeeds after `"drift"` is added to METRICS
   - Integration tests for `POST /portfolios/{id}/rebalance`: success (200, Decimal strings, trades), empty-portfolio (422), no-target-weights (422), unknown-portfolio (404)
   - Integration tests for drift alert evaluation: fires when drift ≥ threshold, deduplication works (second evaluate call → no new event), does not fire when drift < threshold

## Tasks / Subtasks

- [x] Task 1: `portfolio/rebalance.py` — `RebalanceEngine` + `portfolio_total_drift`
  - [x] 1a. Rename `_weights` → `compute_portfolio_weights` (public) in `portfolio/risk.py`; update the one call site in `RiskEngine.metrics`
  - [x] 1b. Create `backend/src/quantvista/portfolio/rebalance.py` with `TradeSuggestion`, `RebalancePlan`, `RebalanceEngine.suggest`, `portfolio_total_drift`
  - [x] 1c. Unit tests `backend/tests/test_rebalance_engine.py` (RED→GREEN)
  - [x] 1d. Run: `pytest tests/test_rebalance_engine.py tests/test_risk_engine.py -x` — risk tests must still pass after rename

- [x] Task 2: `schemas/rebalance.py` + `POST /portfolios/{id}/rebalance`
  - [x] 2a. Create `backend/src/quantvista/schemas/rebalance.py` — `RebalanceRequest`, `TradeSuggestionDTO`, `RebalanceResponse`
  - [x] 2b. Add endpoint to `api/routes_portfolios.py` (same file as existing portfolio endpoints)
  - [x] 2c. Integration tests `backend/tests/integration/test_api_rebalance.py` (RED→GREEN)

- [x] Task 3: Drift alert type — allow-list + evaluator extension
  - [x] 3a. Add `"drift"` to `METRICS` frozenset in `alerts/rules.py`
  - [x] 3b. Add `portfolio_drift_metrics(session, portfolio_ids, as_of)` to `alerts/repositories.py` (SQL + `portfolio_total_drift` call)
  - [x] 3c. Extend `AlertEvaluationService.evaluate` in `alerts/services.py` to handle portfolio-scope rules
  - [x] 3d. Integration tests for drift alert evaluation (RED→GREEN)

- [x] Task 4: Full-tree gates
  - [x] 4a. `ruff check . && ruff format --check .`
  - [x] 4b. `mypy src/quantvista --ignore-missing-imports`
  - [x] 4c. `lint-imports`
  - [x] 4d. `pytest tests/ -x --ignore=tests/integration -q` (full unit suite)
  - [x] 4e. `pytest tests/integration/ -x -q -m integration` (full integration suite)

## Dev Notes

### Architecture Context

**Bounded-context DAG** (from `.importlinter`, enforced by CI):
```
api | jobs        ← composition roots (import anything)
alerts            ← CAN import: portfolio, analytics, market_data, identity, core
portfolio         ← CAN import: analytics, market_data, identity, core
analytics         ← CAN import: market_data, identity, core
market_data | news
identity
core | schemas    ← MUST NOT import any domain context
```

**CRITICAL**: `alerts` can legally import from `portfolio` — this is exploited for the drift alert evaluator (imports `portfolio.rebalance.portfolio_total_drift`).

**CRITICAL**: `schemas` must NOT import from any domain context (foundation-purity contract). `TradeSuggestion`/`RebalancePlan` → `RebalancePlan`→ DTO mapping lives in the `api` layer.

### Task 1 Details — `portfolio/rebalance.py`

**Step 1a — Rename `_weights` in `risk.py`:**

Current private function at `portfolio/risk.py:60`:
```python
def _weights(positions, closes) -> dict[UUID, Decimal]:
```
Rename to `compute_portfolio_weights` (public). Update the one call at `risk.py:105` inside `RiskEngine.metrics`:
```python
weights = compute_portfolio_weights(positions, closes)
```
That is the only call site — the unit tests call `RiskEngine.metrics(...)` which calls it internally; no test calls `_weights` directly. `__all__` in `risk.py` should export `compute_portfolio_weights`.

**Step 1b — `portfolio/rebalance.py` design:**

```python
"""portfolio — RebalanceEngine (QV-059).

Pure compute: given positions (with shares + target_weight) and PIT closes, compute
market-value drift from targets and return suggested trades.

Weight basis: market-value (shares_i×close_i), same as RiskEngine (QV-058) — reuses
``compute_portfolio_weights`` from ``portfolio.risk``. Only positions WITH a
``target_weight`` participate in drift; those without target contribute to total market
value but have no target to drift from.

Target weights are normalized to sum to 1 before computing drift (they may not already
sum to 1 if the user only set partial targets, e.g. 0.80 across 4 of 5 names). This
means drift is always comparable regardless of whether targets are set for all names.
"""
```

**`portfolio_total_drift(positions, closes) -> Decimal | None`** — standalone public helper:
- Used by `alerts/repositories.py` (DAG-legal import) for drift alert evaluation
- Returns `None` when no position has a `target_weight` (caller treats as "no alert possible")
- Does NOT filter by a threshold — returns the raw total variation drift

```python
_Q = Decimal("0.000001")   # 6-dp quantize (matches risk.py)
_DEFAULT_DRIFT_THRESHOLD = Decimal("0.05")  # 5% per name default

def portfolio_total_drift(
    positions: list[dict[str, object]],
    closes: dict[UUID, Decimal],
) -> Decimal | None:
    """Σ|w_current_i − t_normalized_i|/2 over targeted positions. None if no targets."""
    weights = compute_portfolio_weights(positions, closes)
    targeted = [
        (UUID(str(p["stock_id"])), Decimal(str(p["target_weight"])))
        for p in positions
        if p.get("target_weight") is not None
    ]
    if not targeted:
        return None
    total_target = sum(tw for _, tw in targeted)
    if total_target <= 0:
        return None
    drift_sum = sum(abs(weights.get(sid, Decimal(0)) - tw / total_target) for sid, tw in targeted)
    return (drift_sum / 2).quantize(_Q, rounding=ROUND_HALF_UP)
```

**`TradeSuggestion`** (frozen dataclass):
```python
@dataclass(frozen=True)
class TradeSuggestion:
    stock_id: UUID
    symbol: str
    direction: str          # "buy" | "sell"
    current_weight: Decimal # quantized 6dp
    target_weight: Decimal  # normalized target, quantized 6dp
    delta_weight: Decimal   # target − current (positive=buy, negative=sell), quantized 6dp
```

**`RebalancePlan`** (frozen dataclass):
```python
@dataclass(frozen=True)
class RebalancePlan:
    as_of_date: str
    total_drift: Decimal
    needs_rebalance: bool
    trades: list[TradeSuggestion]  # sorted desc by |delta_weight|
```

**`RebalanceEngine.suggest`** signature:
```python
def suggest(
    self,
    positions: list[dict[str, object]],   # list_positions output — has stock_id, shares, target_weight, symbol
    closes: dict[UUID, Decimal],           # latest_closes output — UUID → Decimal
    as_of_date: str,
    *,
    drift_threshold: Decimal = _DEFAULT_DRIFT_THRESHOLD,
) -> RebalancePlan | None:
    """None when no position has target_weight (caller maps to 422)."""
```

Implementation:
1. Call `compute_portfolio_weights(positions, closes)` for current weights
2. Filter positions to `target_weight IS NOT NULL`; return None if empty
3. Normalize targets: `t_i = raw_target_i / Σraw_targets`
4. For each targeted position: compute `delta = t_i − current_weight_i`
5. Accumulate `drift_sum += abs(delta)`
6. Append to trades if `abs(delta) > drift_threshold`
7. `total_drift = drift_sum / 2` (quantized 6dp)
8. `needs_rebalance = total_drift > drift_threshold`
9. Sort trades by `abs(delta_weight)` descending

Symbols: `positions` list from `list_positions` already includes `"symbol"` (see `_position_row` in `portfolio/repositories.py`).

### Task 2 Details — Schema + Endpoint

**`schemas/rebalance.py`:**
```python
from pydantic import BaseModel, Field
from decimal import Decimal

class RebalanceRequest(BaseModel):
    drift_threshold: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)

class TradeSuggestionDTO(BaseModel):
    stock_id: str
    symbol: str
    direction: str           # "buy" | "sell"
    current_weight: str      # Decimal-as-string
    target_weight: str       # Decimal-as-string
    delta_weight: str        # Decimal-as-string (signed)

class RebalanceResponse(BaseModel):
    as_of_date: str
    total_drift: str         # Decimal-as-string
    needs_rebalance: bool
    trades: list[TradeSuggestionDTO]
```

**Foundation-purity**: `schemas/rebalance.py` imports only from Pydantic + stdlib. No imports from domain contexts. ✓

**Endpoint in `routes_portfolios.py`:**
```python
@router.post("/portfolios/{portfolio_id}/rebalance", response_model=Envelope[RebalanceResponse])
def rebalance_portfolio_endpoint(
    portfolio_id: UUID,
    body: RebalanceRequest,
    response: Response,
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[dict[str, Any]]:
    """Suggested trades to reach target weights (research signal, not advice — D1).

    No entitlement gate. Builds market-value weights from current positions + latest
    PIT closes, computes drift from target_weight fields, and returns trades for names
    that exceed the drift threshold. 422 when no positions, no target weights, or no
    price data.
    """
    if get_portfolio(session, portfolio_id) is None:  # RLS-invisible → 404
        raise PortfolioNotFound(portfolio_id)
    positions = list_positions(session, portfolio_id)
    if not positions:
        raise OptimizeError("portfolio has no positions to rebalance")
    as_of = latest_price_date(session)
    if as_of is None:
        raise OptimizeError("no price data available to rebalance")

    stock_ids = [UUID(str(p["stock_id"])) for p in positions]
    closes = latest_closes(session, stock_ids, as_of)

    from quantvista.portfolio.rebalance import RebalanceEngine
    plan = RebalanceEngine().suggest(
        positions, closes, as_of.isoformat(), drift_threshold=body.drift_threshold
    )
    if plan is None:
        raise OptimizeError("no target weights set; run /optimize first to get suggested targets")

    payload = RebalanceResponse(
        as_of_date=plan.as_of_date,
        total_drift=str(plan.total_drift),
        needs_rebalance=plan.needs_rebalance,
        trades=[
            TradeSuggestionDTO(
                stock_id=str(t.stock_id),
                symbol=t.symbol,
                direction=t.direction,
                current_weight=str(t.current_weight),
                target_weight=str(t.target_weight),
                delta_weight=str(t.delta_weight),
            )
            for t in plan.trades
        ],
    ).model_dump()
    _with_disclaimer(response)
    return Envelope.ok(payload, meta={"disclaimer": DISCLAIMER})
```

**Imports to add at top of `routes_portfolios.py`:**
- `from quantvista.schemas.rebalance import RebalanceRequest, RebalanceResponse, TradeSuggestionDTO`
- `from quantvista.portfolio.rebalance import RebalanceEngine` (lazy import inside handler avoids heavy domain load at app startup — OR import at module level since no extra is needed; `rebalance.py` uses only numpy via `compute_portfolio_weights` → `risk.py` → numpy; prefer lazy to match optimizer pattern)

Actually, `rebalance.py` does NOT require cvxpy, so there's no reason to lazy-import it. Import at module level. But to keep it consistent with the optimizer pattern, import inside the handler is fine either way. Use module-level import for simplicity.

**Error mapping**: `OptimizeError` already maps to 422 via the existing exception handler. Reuse it — no new exception class needed.

### Task 3 Details — Drift Alert Wiring

**Step 3a — `alerts/rules.py`:**
Add `"drift"` to the `METRICS` frozenset. Change:
```python
METRICS: frozenset[str] = frozenset({
    "composite_score", "fundamental_score", "momentum_score", "quality_score",
    "sentiment_score", "risk_score", "coverage", "pe", "pb", "roe", "roce", "debt_equity",
})
```
→ add `"drift"` to the set. `validate_condition` accepts it without any other changes.

**Step 3b — `alerts/repositories.py` — new function `portfolio_drift_metrics`:**

```python
from datetime import date
from quantvista.portfolio.rebalance import portfolio_total_drift  # alerts → portfolio: DAG-legal

def portfolio_drift_metrics(
    session: Session,
    portfolio_ids: Sequence[UUID],
    as_of: date,
) -> dict[UUID, float | None]:
    """Total-variation drift per portfolio (privileged session — for alert evaluator only).
    
    One SQL query fetches positions + PIT closes for all portfolios; drift is computed
    in Python via ``portfolio_total_drift``. ``None`` when a portfolio has no targets.
    """
    if not portfolio_ids:
        return {}
    rows = (
        session.execute(
            text(
                """
                SELECT pp.portfolio_id, pp.stock_id, pp.shares, pp.target_weight, s.symbol,
                       dp.close
                FROM portfolio_positions pp
                JOIN stocks s ON s.id = pp.stock_id
                LEFT JOIN LATERAL (
                    SELECT close FROM daily_prices
                    WHERE stock_id = pp.stock_id AND date <= :as_of
                    ORDER BY date DESC LIMIT 1
                ) dp ON true
                WHERE pp.portfolio_id = ANY(:ids)
                """  # noqa: S608
            ),
            {"ids": list(portfolio_ids), "as_of": as_of},
        )
        .mappings()
        .all()
    )
    # Group into per-portfolio positions list + closes dict
    pos_by: dict[UUID, list[dict[str, object]]] = {pid: [] for pid in portfolio_ids}
    closes_by: dict[UUID, dict[UUID, Decimal]] = {}
    for r in rows:
        pid, sid = UUID(str(r["portfolio_id"])), UUID(str(r["stock_id"]))
        pos_by[pid].append({
            "stock_id": str(sid),
            "shares": r["shares"],
            "target_weight": str(r["target_weight"]) if r["target_weight"] is not None else None,
            "symbol": r["symbol"] or "",
        })
        if r["close"] is not None:
            closes_by.setdefault(pid, {})[sid] = Decimal(str(r["close"]))

    return {
        pid: (lambda d: float(d) if d is not None else None)(
            portfolio_total_drift(pos_by[pid], closes_by.get(pid, {}))
        )
        for pid in portfolio_ids
    }
```

Note: `portfolio_total_drift` is imported at module level (not inside the function). The `LATERAL` pattern is the same as `latest_closes` / `latest_betas` in `market_data/repositories.py` — proven to work in this codebase.

**Step 3c — `alerts/services.py` — extend `AlertEvaluationService.evaluate`:**

Current structure:
```python
def evaluate(self, as_of: date, trigger: str) -> int:
    dedup_key = as_of.isoformat()
    with privileged_session_scope() as session:
        rules = [r for r in active_alert_rules(session) if r["scope"] == "stock"]
        metrics = stock_metrics(session, [r["target_id"] for r in rules])
        fired = 0
        for rule in rules:
            ...
    ...
    return fired
```

Extend to:
```python
def evaluate(self, as_of: date, trigger: str) -> int:
    dedup_key = as_of.isoformat()
    with privileged_session_scope() as session:
        all_rules = active_alert_rules(session)
        
        # --- stock-scope rules (unchanged) ---
        stock_rules = [r for r in all_rules if r["scope"] == "stock"]
        metrics = stock_metrics(session, [r["target_id"] for r in stock_rules])
        
        fired = 0
        for rule in stock_rules:
            cond = rule["condition"]
            value = metrics.get(rule["target_id"], {}).get(cond["metric"])
            if not matches(value, cond["op"], float(cond["value"])):
                continue
            payload = {
                "type": "metric_alert",
                "symbol": rule.get("target_symbol"),
                "company_name": rule.get("company_name"),
                "metric": cond["metric"],
                "op": cond["op"],
                "threshold": cond["value"],
                "value": value,
                "trigger": trigger,
            }
            if insert_alert_event(session, tenant_id=rule["tenant_id"],
                                  alert_rule_id=rule["id"], dedup_key=dedup_key,
                                  payload=payload):
                fired += 1
        
        # --- portfolio-scope rules (new: drift metric only) ---
        portfolio_rules = [r for r in all_rules if r["scope"] == "portfolio"]
        if portfolio_rules:
            port_ids = list({r["target_id"] for r in portfolio_rules})
            port_drifts = portfolio_drift_metrics(session, port_ids, as_of)
            
            for rule in portfolio_rules:
                cond = rule["condition"]
                if cond.get("metric") != "drift":
                    continue  # only "drift" is implemented for portfolio scope
                drift = port_drifts.get(rule["target_id"])
                if not matches(drift, cond["op"], float(cond["value"])):
                    continue
                payload = {
                    "type": "portfolio_drift_alert",
                    "portfolio_id": str(rule["target_id"]),
                    "metric": "drift",
                    "op": cond["op"],
                    "threshold": cond["value"],
                    "value": drift,
                    "trigger": trigger,
                }
                if insert_alert_event(session, tenant_id=rule["tenant_id"],
                                      alert_rule_id=rule["id"], dedup_key=dedup_key,
                                      payload=payload):
                    fired += 1

    self._log.info("alerts_evaluated", trigger=trigger, cycle=dedup_key, fired=fired)
    return fired
```

Add `portfolio_drift_metrics` to the import from `quantvista.alerts.repositories`.

### Task 3 — Integration Tests for Drift Alert (`tests/integration/test_api_drift_alert.py`)

Seed:
- Register a user + tenant
- Create a portfolio with positions (shares + target_weight)
- Seed daily_prices for those stocks (PIT-correct, non-NaN)
- Create an `alert_rule` via `create_alert_rule(session, scope="portfolio", target_id=portfolio_id, condition={"metric":"drift","op":"gte","value":0.05}, ...)`

Tests:
1. `test_portfolio_drift_alert_fires_when_threshold_breached` — portfolio heavily out of balance → `AlertEvaluationService().evaluate(today, "scores")` → `n_events == 1`
2. `test_portfolio_drift_alert_deduplicates` — run evaluate twice → still 1 event (ON CONFLICT DO NOTHING)
3. `test_portfolio_drift_alert_does_not_fire_when_balanced` — portfolio at exact targets → drift ≈ 0 → no event fired

Note: Use the same `admin_engine` fixture + `Session(admin_engine)` pattern as `test_api_risk.py`. Don't use `db_session` fixture.

### Patterns from QV-058 to Mirror

| Pattern | Location in QV-058 |
|--------|-------------------|
| `latest_closes(session, ids, as_of)` | `market_data/repositories.py` → reuse as-is |
| `list_positions(session, portfolio_id)` | `portfolio/repositories.py` → reuse as-is |
| `latest_price_date(session)` | `market_data/repositories.py` → reuse as-is |
| `_with_disclaimer(response)` + `DISCLAIMER` | `api/routes_stocks.py` → already imported |
| `Envelope.ok(payload, meta={"disclaimer": ...})` | `schemas/envelope.py` |
| `Session(admin_engine)` for integration tests | `tests/integration/test_api_risk.py` lines 68+ |
| `OptimizeError` → 422 `validation_error` | `routes_portfolios.py` exception handler |

### DB / Migration Constraints

**NO MIGRATION NEEDED** for this story:
- `alert_rules.scope IN ('stock','portfolio')` — already in migration 0010 (line 37): `CHECK (scope IN ('stock','portfolio'))`
- `alert_events` — already exists with flexible `payload` jsonb
- `portfolio_positions.target_weight` — already `numeric(9,6)` nullable (migration 0008)
- `daily_prices.close` — already `numeric(18,4)` (migration 0004)

### No New Python Dependencies

`RebalanceEngine` uses only:
- `decimal` (stdlib)
- `uuid` (stdlib)
- `quantvista.portfolio.risk.compute_portfolio_weights` (internal)

`portfolio_drift_metrics` uses only:
- `sqlalchemy.text` (already in requirements)
- `decimal` (stdlib)
- `quantvista.portfolio.rebalance.portfolio_total_drift` (new internal)

No new `pyproject.toml` entries needed.

### Test Coverage Expectations

- `portfolio/rebalance.py`: 100% (pure compute — all paths coverable in unit tests)
- `alerts/rules.py` change: 1 line; covered by existing + new unit test
- `alerts/repositories.py` new function: covered by integration test
- `alerts/services.py` new branch: covered by integration test
- API endpoint: covered by integration test

### Common Gotchas

1. **`_weights` rename**: Update both the `def` line AND the `__all__` in `risk.py`. The existing 10 unit tests in `test_risk_engine.py` call `RiskEngine().metrics(...)` which internally calls the renamed function — they do NOT import `_weights` directly, so they continue to pass.

2. **`portfolio_total_drift` import in `alerts/repositories.py`**: Import at module level (not inside function) to avoid hidden runtime errors. The `alerts → portfolio` dependency is DAG-legal so lint-imports will not flag it.

3. **Decimal/float boundary for drift alert**: `portfolio_drift_metrics` returns `dict[UUID, float | None]` (not `Decimal`) because `alerts.evaluation.matches(value: float | None, ...)` expects float. Convert with `float(drift)` at the boundary — do NOT use the Decimal directly.

4. **`as_of` for drift alert evaluation**: The `AlertEvaluationService.evaluate(as_of, trigger)` already receives `as_of` from the job (via `last_completed_session(date.today())`). Pass this same `as_of` to `portfolio_drift_metrics`.

5. **`target_id` type in alert rule**: `active_alert_rules` returns `r["target_id"]` as a `UUID` (from PG — SQLAlchemy maps `uuid` column to Python `UUID`). The `portfolio_drift_metrics` function takes `Sequence[UUID]`. Pass the set directly: `{r["target_id"] for r in portfolio_rules}`.

6. **LATERAL join in `portfolio_drift_metrics`**: The SQL reads ALL portfolio positions (not just those with `target_weight`) because `compute_portfolio_weights` needs ALL shares to compute total market value. `portfolio_total_drift` then filters to targeted ones internally.

7. **`drift_threshold` in `RebalanceRequest`**: Pydantic v2 serializes `Decimal` fields from JSON string or number. `ge=0` and `le=1` work correctly with `Decimal`.

8. **`needs_rebalance` flag**: Compare `total_drift > drift_threshold` (strict greater-than). A portfolio exactly AT the threshold is considered balanced (`needs_rebalance=False`).

### Existing Files Modified

| File | Change |
|------|--------|
| `portfolio/risk.py` | Rename `_weights` → `compute_portfolio_weights`; update call site; add to `__all__` |
| `api/routes_portfolios.py` | Add `POST .../rebalance` endpoint + new imports (`RebalanceRequest`, `RebalanceResponse`, `TradeSuggestionDTO`, `RebalanceEngine`) |
| `alerts/rules.py` | Add `"drift"` to `METRICS` frozenset |
| `alerts/repositories.py` | Add `portfolio_drift_metrics` function + imports (`date`, `portfolio_total_drift`) |
| `alerts/services.py` | Extend `AlertEvaluationService.evaluate` for portfolio scope + import `portfolio_drift_metrics` |

### New Files Created

| File | Purpose |
|------|---------|
| `portfolio/rebalance.py` | `TradeSuggestion`, `RebalancePlan`, `RebalanceEngine`, `portfolio_total_drift` |
| `schemas/rebalance.py` | `RebalanceRequest`, `TradeSuggestionDTO`, `RebalanceResponse` |
| `tests/test_rebalance_engine.py` | Unit tests for pure rebalance compute |
| `tests/integration/test_api_rebalance.py` | API integration tests |
| `tests/integration/test_drift_alert.py` | Drift alert evaluation integration tests |

## Dev Agent Record

### Implementation Plan
_To be filled by dev agent._

### Debug Log
_To be filled by dev agent._

### Completion Notes
_To be filled by dev agent._

## File List

_To be filled by dev agent._

## Change Log

_To be filled by dev agent._
