# Sprint 05 — Sentiment + Alerts

**Phase:** 2 · **Goal:** FinBERT sentiment feeding the score, plus the alerts engine and delivery.
**Exit gate:** sentiment contributes to composite scores; users create alerts that fire within one scoring
cycle and deliver in-app + email.

> See `../05-domain-and-quant.md` §1.4, `../04` §3.7, `../06` (evaluate_alerts).

---

### QV-044 — FinBERT sentiment service + model runtime `[QUANT]` · `8pts` · Epic: EPIC-NEWS · depends: QV-041
**Story:** As the platform, I want financial-news sentiment, so news becomes a quantified factor.
**Acceptance criteria:**
- `SentimentModel`/`FinBERTSentiment` classifies positive/negative/neutral with score+confidence; served on a
  dedicated `nlp` queue/pool (batched).
- `sentiment` table persists label/score/confidence/model_version; idempotent per news batch; emits
  `NewsScored`.
**Notes:** `05` §1.4; throughput risk R9 — batching + dedicated pool (`06` §4).

### QV-045 — Event-impact scorer `[QUANT]` · `3pts` · Epic: EPIC-NEWS · depends: QV-044
**Story:** As an analyst, I want material events weighted, so big news moves the signal appropriately.
**Acceptance criteria:**
- Map event types to impact (e.g., contract win +, ban −) combined with sentiment into an `impact_score`;
  configurable, versioned.
**Notes:** `05` §1.4.

### QV-046 — Sentiment factor wired into scoring `[QUANT]` · `3pts` · Epic: EPIC-INTEL · depends: QV-044, QV-029
**Story:** As a quant, I want sentiment in the composite, so scores reflect news.
**Acceptance criteria:**
- `SentimentFactor` aggregates decayed per-stock sentiment as-of date; included at the `05` §2 weight;
  `compute_scores` consumes it; decomposition shows its contribution.
**Notes:** PIT-safe (no future news).

### QV-047 — Alerts schema + rule engine `[BE]` · `5pts` · Epic: EPIC-ALERT · depends: QV-007
**Story:** As a user, I want configurable alert rules, so I'm notified on conditions I care about.
**Acceptance criteria:**
- `alert_rules`/`alert_events` (tenant-scoped, RLS); rule spec validated (allow-listed metric/op); per-tier
  limit enforced.
**Notes:** `04` §3.7; `03` §4.3.

### QV-048 — `evaluate_alerts` + deduplication `[BE]` · `5pts` · Epic: EPIC-ALERT · depends: QV-047, QV-030
**Story:** As a user, I want alerts to fire promptly and not spam me, so they're useful.
**Acceptance criteria:**
- Triggered on `ScoresComputed`/`NewsScored`; evaluates score/PE/RSI/drift/news conditions; fires within one
  scoring cycle (US-05); deduplicated; writes `alert_events`; emits `AlertsFired`.
**Notes:** `06` §3.

### QV-049 — Notification delivery (in-app + email) `[BE]` · `5pts` · Epic: EPIC-ALERT · depends: QV-048
**Story:** As a user, I want alerts delivered, so I act on them.
**Acceptance criteria:**
- `INotificationChannel` with in-app (`notifications` table) + email (SES/Resend); retries + delivery status;
  channel honored from the rule.
**Notes:** Webhooks/Slack deferred to Quant tier later.

### QV-050 — Frontend: Alerts management + notifications `[FE]` · `5pts` · Epic: EPIC-ALERT · depends: QV-047, QV-035
**Story:** As a user, I want to manage alerts and see notifications, so I control my signals.
**Acceptance criteria:**
- Create/edit/delete alert rules with limit-aware UI; in-app notification center; email opt-in.
**Notes:** `01` Pillar F.

**Sprint total:** ~39 pts.
