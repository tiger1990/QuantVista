# Sprint 12 — ML Augmentation (Post-Launch)

**Phase:** 6 · **Goal:** add an ML ranking signal that *augments* (never replaces) the transparent factor
model, with leakage-safe training, champion/challenger governance, and drift monitoring.
**Exit gate:** an ML signal is surfaced as a labeled, versioned secondary output and only promoted if it beats
the factor baseline on bias-controlled, out-of-sample backtests.

> See `../05-domain-and-quant.md` §5. Post-launch; does not gate launch.

---

### QV-087 — Feature store from PIT factor_values `[QUANT]` · `5pts` · Epic: EPIC-ML · depends: QV-029
**Story:** As an ML engineer, I want training features identical to serving features, so there's no train/serve
skew or leakage.
**Acceptance criteria:**
- Feature pipeline reads `factor_values` (already PIT); 100+ engineered features; point-in-time joins only;
  documented feature catalog.
**Notes:** `05` §5.

### QV-088 — Walk-forward / purged CV training pipeline `[QUANT]` · `8pts` · Epic: EPIC-ML · depends: QV-087
**Story:** As an ML engineer, I want time-series-correct validation, so reported performance is honest.
**Acceptance criteria:**
- XGBoost/LightGBM ranking + risk models trained with walk-forward / purged CV + embargo (no random K-fold);
  experiments/datasets/metrics tracked; artifacts versioned in object store + registry.
**Notes:** `05` §5.

### QV-089 — Champion/challenger evaluation gate `[QUANT]` · `5pts` · Epic: EPIC-ML · depends: QV-088, QV-066
**Story:** As a quant lead, I want models promoted only on merit, so we don't ship worse signals.
**Acceptance criteria:**
- A model promotes only if it beats the factor baseline on **bias-controlled** out-of-sample backtests
  (reuses Sprint 08 controls); promotion recorded with `model_version`.
**Notes:** `05` §5 governance.

### QV-090 — Batch ML scoring + serving `[BE]` `[QUANT]` · `5pts` · Epic: EPIC-ML · depends: QV-089, QV-030
**Story:** As a user, I want an ML-derived signal alongside factor scores, so I have an additional view.
**Acceptance criteria:**
- Nightly batch writes ML scores with `model_version`; exposed via API/UI as a clearly **labeled, secondary**
  signal (factor composite remains the explainable default); disclaimer present.
**Notes:** `05` §5; `07` §1.

### QV-091 — Drift monitoring `[QUANT]` `[PLAT]` · `3pts` · Epic: EPIC-ML · depends: QV-090
**Story:** As an operator, I want feature/performance drift alerts, so model decay is caught.
**Acceptance criteria:**
- Monitor feature distributions + live performance vs expectation; alert on drift; dashboard panel.
**Notes:** `05` §5; `08` §6.

**Sprint total:** ~31 pts · **Note:** future phase — TFT forecasting explicitly deferred (`05` §5).

---

## Beyond Sprint 12 (backlog seeds, not scheduled)
- Black-Litterman & HRP optimizers (`05` §3 phases 3–4; Quant tier).
- Webhook/Slack alert channels (Quant).
- US / S&P 100 expansion → `../future-us-market-expansion.md`.
- Service extraction at scale → `../future-scale-microservices.md`.
- RIA-grade advisory → `../future-ria-compliance.md`.
