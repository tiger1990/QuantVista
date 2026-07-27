---
baseline_commit: 3517e40f34cffd371c3c092d3480da9f13b54772
---

# Story 8.3: QV-064 — Survivorship-free historical universe

Status: done

**Epic:** EPIC-BT (Epic 8) · **Points:** 5 · **Depends:** QV-013 (schema: `stocks.delisted_on`, `index_constituents` PIT membership), QV-019 (`sync_index_constituents` / `reconcile_constituents` — the writer that keeps membership survivorship-free)

> **The survivorship-free membership resolver for backtests.** Given a rebalance date `D`, resolve the index's membership *as it was on `D`* — **including names that were later delisted or dropped** — from the `index_constituents` effective-range table. This is the universe QV-065 feeds into `BacktestDataAccess.ranked_universe`. Today the only membership reader is `active_universe` (`effective_to IS NULL` + `is_active`), which sees **only current members** — the textbook survivorship bias (`05` §4.2, cardinal sin #2). This story adds the as-of read and surfaces it on the single backtest seam, plus the last-valid-price primitive QV-065 needs to force-exit a delisted holding. It does **not** run the rebalance loop (QV-065) and adds **no new table, migration, or API**.

## Story

As a quant, I want the *historical* index membership including delisted names, so backtests aren't survivorship-biased.

## Acceptance Criteria

1. **As-of membership read (survivorship-free)** — a new `historical_universe(session, index_code, market_code, as_of) -> list[UUID]` in `market_data/repositories.py` (beside `active_universe`) returns every constituent whose membership range **contains `as_of`**: `effective_from <= as_of AND (effective_to IS NULL OR effective_to > as_of)`. It **must NOT** filter on `stocks.is_active` or `stocks.delisted_on` — a name that was a member on `D` but delisted afterward **is** in the universe at `D`. Deterministic order (by `symbol`, or `stock_id` — stable).
   [Source: `05` §4.2; `index_constituents` schema `0003` — `effective_from`/`effective_to`, drops set `effective_to = as_of` and never delete (`reconcile_constituents`)]

2. **Half-open interval semantics** — membership is `[effective_from, effective_to)`: a name is a member on `effective_from`, and **not** a member on its `effective_to` (drop) date. So `as_of == effective_to` → excluded; `as_of == effective_from` → included. (Matches `reconcile_constituents`: "dropped as-of `D`" means not a member from `D` onward. Schema CHECK guarantees `effective_to > effective_from`.)
   [Source: `market_data/repositories.reconcile_constituents` docstring; `0003` CHECK]

3. **Surfaced on the single backtest seam** — `BacktestDataAccess.universe_as_of(as_of, *, index_code="NIFTY200", market="NSE") -> list[UUID]` (QV-063's `analytics/backtest_data.py`) delegates to `historical_universe`, so QV-065 reads universe + ranking + returns through the **one** PIT seam: `universe = data.universe_as_of(D)` → `data.ranked_universe(D, universe, …)` → `data.returns_as_of(D, …)`. No bypass, no direct table read in the engine.
   [Source: QV-063 `backtest_data.py` — "the ONLY seam the engine reads through"; DAG `analytics → market_data` already allowed]

4. **Forced-exit price primitive (delisting)** — a new `last_adjusted_close_as_of(session, stock_ids, as_of) -> dict[UUID, tuple[date, Decimal]]` in `market_data/repositories.py` returns, per stock, the **last adjusted-close bar on or before `as_of`** (`max(date) WHERE date <= as_of`, its `adj_close`). This is the price QV-065 uses to force-exit a holding that leaves the universe because it delisted — "forced exit at last valid price" (`05` §4.2). Names with no bar `<= as_of` are simply absent from the map (engine handles). Surface it on the seam as `BacktestDataAccess.last_price_as_of(as_of, stock_ids)`.
   [Source: `05` §4.2 "Delisting handled as a forced exit at last valid price"; `daily_prices.adj_close`]

5. **Survivorship-free proven by a real-Postgres regression** — an integration test (`@pytest.mark.integration`, runs in the required `backend-rls` gate, non-skippable) seeds one index with a mix and asserts `historical_universe(D)` is **exactly** the as-of set. The load-bearing case: a name that is `is_active=false, delisted_on > D` **and** has `effective_to > D` **is included at `D`** (the cardinal-sin guard) — and is **excluded** once `as_of >= effective_to`. Cover: open member (`from<=D`, `to NULL`) → in; member later dropped (`from<=D<to`) → in; dropped before D (`to<=D`) → out; not-yet-member (`from>D`) → out; boundary `as_of==effective_to` → out; `as_of==effective_from` → in. Plus `last_adjusted_close_as_of` returns the last bar `<= as_of` for a delisted name.
   [Source: `tests/integration/test_reference_schema.py` seeding helpers (`_new_stock(delisted_on=…)`, constituent insert); QV-037/QV-063 real-PG regression precedent]

6. **Tests + gates** — unit-ish selection cases via the integration seed; coverage ≥80% on the new code. Full-tree gates green (ruff, ruff format, **bare `mypy`**, lint-imports **3/3**, bandit, pip-audit). **No new table / migration / API** — pure read layer over existing `index_constituents` + `daily_prices`.
   [Source: testing rules; QV-063 precedent]

---

## Dev Notes

### Placement & DAG

- **`market_data/repositories.py`** gets `historical_universe(...)` (next to `active_universe`, line ~90) and `last_adjusted_close_as_of(...)` (near the price helpers). Same module, same style (module-level `text()` SQL constant + thin function, frozen dataclass only if a record type is needed — plain `list[UUID]` / `dict` is enough here).
- **`analytics/backtest_data.py`** (QV-063) gets two thin methods — `universe_as_of` and `last_price_as_of` — that just call the repo functions on `self._session`. DAG `analytics → market_data` is already a kept contract; **confirm `lint-imports` stays 3/3**. No new context, no DAG edit.
- Python 3.13, mypy strict (**run bare `mypy`** — it reads `files = [src/quantvista, tests, scripts]` from `pyproject.toml`; `mypy src tests` drops the `scripts` root and false-flags an import, learned in QV-063). ids are `UUID`; prices stay `Decimal` (never float on the wire).

### Reuse — do NOT re-implement (critical)

- **The table is already survivorship-free.** `reconcile_constituents` (QV-019) closes drops with `effective_to = as_of` and **never deletes**; `stocks.delisted_on` records the delist date. So the *history* already exists — QV-064 only adds the **as-of read** over it. Do NOT add columns, a new table, or a migration.
- **Mirror `active_universe`'s shape** (`market_data/repositories.py:61-95`) for the SQL/JOIN style, but: (a) swap the `effective_to IS NULL` predicate for the as-of range, (b) **drop the `AND s.is_active` join filter** (that filter is exactly the survivorship bias), (c) still JOIN `markets` to scope by `market_code`. Bind `as_of` as a parameter.
- **`daily_prices.adj_close`** is the adjusted close (QV-017 fills it; raw-close placeholder otherwise). `last_adjusted_close_as_of` reads `adj_close`, not `close`.
- **Seed helpers already exist** — `tests/integration/test_reference_schema.py` has `_new_market`, `_new_stock(conn, market_id, delisted_on=…, is_active=…)`, and a constituent insert (`id, index_code, stock_id, effective_from, effective_to, weight`). Reuse that exact shape; do not invent a new seeding style.

### Membership semantics (the whole point — get this exactly right)

Universe at `D` = `{ stock_id : effective_from <= D AND (effective_to IS NULL OR effective_to > D) }`, **no `is_active` / `delisted_on` filter**. Truth table (all for index `X`, market `NSE`):

| name | effective_from | effective_to | is_active | in universe at `D`? |
|------|---------------|--------------|-----------|---------------------|
| open member | `< D` | `NULL` | true | ✅ yes |
| dropped-after-`D` (later delisted) | `< D` | `> D` | **false** | ✅ **yes** (survivorship-free) |
| dropped-before-`D` | `< D` | `<= D` | false | ❌ no |
| not-yet-member | `> D` | `NULL`/any | true | ❌ no |
| boundary `D == effective_to` | `< D` | `== D` | any | ❌ no (half-open) |
| boundary `D == effective_from` | `== D` | `NULL` | true | ✅ yes |

The "dropped-after-`D`" row is the load-bearing case — it's the exact name a survivorship-biased reader (today's `active_universe`) wrongly omits, silently inflating historical returns.

### Forced exit at last valid price (why AC-4 exists)

QV-065 holds positions between rebalances. If a held name delists mid-hold, it leaves the universe at the next rebalance `D'` (its `effective_to <= D'`), and the engine must **exit the position at the last price that actually traded**, not at a stale or zero price. `last_adjusted_close_as_of(session, [held_ids], D')` gives `{id: (last_bar_date, adj_close)}`; QV-065 prices the forced exit off that. QV-064 only provides the primitive — the exit *loop* is QV-065.

### Scope boundary

- QV-064 = membership resolution + forced-exit price primitive. The **rebalance loop, transaction costs, slippage, turnover, benchmark** are QV-065 (depends on QV-064). The **bias regression suite** (permanent CI guards for both cardinal sins) is QV-066 (also depends on QV-064) — QV-064's own test proves the survivorship guard for *this* seam; QV-066 generalizes it.
- Dev data has **no delisted names** in the live Nifty-200 (all active) — so the survivorship-free behavior is proven by a **synthetic seeded universe** in the integration test (as QV-037/QV-063 do), not against live data.

### Previous-story / epic intelligence

- **QV-063 (just merged, PR #72)** built `BacktestDataAccess(session)` in `analytics/backtest_data.py` as "the ONLY seam the engine reads through," explicitly deferring membership: *"Survivorship-free membership is QV-064 — `universe` is caller-supplied."* QV-064 fills that gap by adding `universe_as_of`/`last_price_as_of` to that same class. Keep the class's discipline: every method takes `as_of` and is bounded by it; no "latest"/unbounded read.
- QV-063 also made `scripts` an importable package and established: **run bare `mypy`** for the real gate; the leakage/regression test seeds a synthetic universe on the `admin_engine` and cleans up in the fixture teardown.

### Git intelligence (recent)

`3517e40 feat: PIT data access for backtests (QV-063) #72` · `541b4e1 QV-062 #71`. The QV-063 test file (`tests/integration/test_backtest_data.py`) is the closest template for the new test's fixture/cleanup shape; `test_reference_schema.py` is the template for constituent+delisted seeding.

### Project context reference

`_bmad-output/project-context.md` — backend `backend/src/quantvista/<context>/`; import-linter `root_package = quantvista`; money as `Decimal` via `str`; PIT correctness is the cardinal rule of Epic 8.

## Tasks / Subtasks

### Task 1: `historical_universe` repository read (AC-1, AC-2)
- [x] Add module-level `text()` SQL constant + `historical_universe(session, index_code, market_code, as_of) -> list[UUID]` in `market_data/repositories.py`, beside `active_universe`.
- [x] Range predicate `effective_from <= :as_of AND (effective_to IS NULL OR effective_to > :as_of)`; JOIN `markets` for `market_code`; **no `is_active` filter**; deterministic `ORDER BY`.

### Task 2: `last_adjusted_close_as_of` primitive (AC-4)
- [x] Add `last_adjusted_close_as_of(session, stock_ids, as_of) -> dict[UUID, tuple[date, Decimal]]` reading the last `adj_close` bar `<= as_of` per stock (`DISTINCT ON (stock_id) … ORDER BY stock_id, date DESC`). Empty/absent for names with no prior bar. Guard empty `stock_ids`.

### Task 3: Surface on the backtest seam (AC-3)
- [x] Add `universe_as_of(as_of, *, index_code="NIFTY200", market="NSE")` and `last_price_as_of(as_of, stock_ids)` to `BacktestDataAccess`, delegating to Tasks 1–2. Docstrings note the survivorship-free guarantee.
- [x] Confirm `lint-imports` stays 3/3 (analytics → market_data).

### Task 4: Survivorship-free regression (AC-5)
- [x] New `tests/integration/test_historical_universe.py` (`pytestmark = pytest.mark.integration`), seeding via the `test_reference_schema.py` pattern on `admin_engine`; rolled-back transaction (no residue).
- [x] Seed one index with the six truth-table rows (incl. a `is_active=false, delisted_on>D, effective_to>D` name). Assert `historical_universe(D)` is exactly `{open, dropped-after-D, boundary-from}`; assert boundaries (`as_of==effective_to` out, `as_of==effective_from` in); assert the delisted name drops out at `as_of>=effective_to`.
- [x] Seed `daily_prices` for the delisted name; assert `last_adjusted_close_as_of` returns its last bar `<= as_of` (and via `BacktestDataAccess.last_price_as_of`).

### Task 5: Gates + sprint status (AC-6)
- [x] Full-tree gates: ruff, ruff format, **bare `mypy`** (266), lint-imports 3/3, bandit, pip-audit; new code coverage 100%/97% (all new lines hit).
- [x] Story Status → review; sprint-status `8-3-qv-064-…` → review; fill Dev Agent Record.

## Dev Agent Record

### Debug Log

- RED: wrote `tests/integration/test_historical_universe.py` first → `ImportError: cannot import name 'historical_universe'` (10 tests, collection error) — confirmed the seam is genuinely missing.
- GREEN: added `historical_universe` + `last_adjusted_close_as_of` to `market_data/repositories.py`, then `universe_as_of` + `last_price_as_of` to `analytics/backtest_data.py` → 10/10 pass.
- Gate fix: 3× E501 + 1 format in the new test → `ruff format` resolved; ruff clean after.
- Coverage nuance: running only the new file showed backtest_data at 74% (QV-063's `ranked_universe`/`returns_as_of` unexercised by *this* file); across the full suite backtest_data = **100%**, repositories = 97% (the 5 misses — 177/185/495/576/595 — are pre-existing early-return guards in other functions, not QV-064 code).

### Completion Notes List

- **Survivorship-free membership** resolved from the existing `index_constituents` effective-range table — half-open `[effective_from, effective_to)`, **no `is_active`/`delisted_on` filter** (that filter is the bias). No new table/migration/API; the table was already survivorship-free (QV-019 closes drops with `effective_to`, never deletes).
- **Forced-exit primitive** `last_adjusted_close_as_of` gives QV-065 the last valid `adj_close ≤ as_of` to price a delisted holding's exit.
- Both surfaced on the QV-063 `BacktestDataAccess` seam so QV-065 reads universe + ranking + returns through the one PIT seam.
- Proven by a real-Postgres regression: the load-bearing case is a `is_active=false, delisted_on>D, effective_to>D` name that **is** in the universe at D and drops out at `as_of>=effective_to`. Dev has no live delisted names, so proven synthetically (QV-037/QV-063 pattern).
- Full suite **711 passed / 5 skipped**; all gates green.

### File List

- `backend/src/quantvista/market_data/repositories.py` (modified — `historical_universe`, `last_adjusted_close_as_of` + their SQL constants)
- `backend/src/quantvista/analytics/backtest_data.py` (modified — `universe_as_of`, `last_price_as_of` seam methods; `Decimal` import)
- `backend/tests/integration/test_historical_universe.py` (new — 10 integration tests)

### Change Log

- 2026-07-27 — QV-064 survivorship-free historical universe: as-of `historical_universe` read + `last_adjusted_close_as_of` forced-exit primitive (`market_data/repositories.py`), surfaced as `universe_as_of`/`last_price_as_of` on `BacktestDataAccess`; 10-test real-PG regression. Gates green; new-code coverage 100%/97%.
