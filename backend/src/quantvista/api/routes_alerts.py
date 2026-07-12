"""Alert-rule endpoints (QV-047) — POST/GET/DELETE /alerts (04 §3.7).

Tenant-isolated via the RLS session; the ``alerts`` tier limit is enforced on create (US-05). The
condition is validated against the QV-047 allow-list before persisting, so the evaluator (QV-048)
only ever sees runnable rules.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from quantvista.alerts.repositories import (
    count_active_alert_rules,
    create_alert_rule,
    delete_alert_rule,
    list_alert_rules,
)
from quantvista.alerts.rules import validate_channel, validate_condition, validate_scope
from quantvista.api.deps import get_entitlement_service, get_tenant_context, get_tenant_session
from quantvista.identity.entitlements import EntitlementService
from quantvista.identity.models import EntitlementExceeded, TenantContext
from quantvista.schemas.alerts import AlertRule, CreateAlertRequest
from quantvista.schemas.envelope import Envelope

router = APIRouter(prefix="/api/v1", tags=["alerts"])

_LIMIT_KEY = "alerts"


class AlertNotFound(Exception):
    def __init__(self, rule_id: UUID) -> None:
        self.rule_id = rule_id


@router.post("/alerts", response_model=Envelope[AlertRule], status_code=201)
def create_alert_endpoint(
    body: CreateAlertRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
    entitlements: EntitlementService = Depends(get_entitlement_service),
) -> Envelope[dict[str, Any]]:
    """Create an alert rule, tier-limited by the ``alerts`` entitlement."""
    # Domain allow-list re-check (beyond the pydantic Literals) → AlertRuleError → 422.
    validate_scope(body.scope)
    validate_channel(body.channel)
    validate_condition(body.condition.model_dump())

    limit = entitlements.limit(ctx.tenant_id, _LIMIT_KEY)  # None = unlimited
    if limit is not None and count_active_alert_rules(session) >= limit:
        raise EntitlementExceeded(_LIMIT_KEY)

    row = create_alert_rule(
        session,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        scope=body.scope,
        target_id=body.target_id,
        condition=body.condition.model_dump(),
        channel=body.channel,
    )
    return Envelope.ok(AlertRule.model_validate(row).model_dump())


@router.get("/alerts", response_model=Envelope[list[AlertRule]])
def list_alerts_endpoint(
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Envelope[list[dict[str, Any]]]:
    items = [AlertRule.model_validate(r).model_dump() for r in list_alert_rules(session)]
    return Envelope.ok(items)


@router.delete("/alerts/{rule_id}", status_code=204)
def delete_alert_endpoint(
    rule_id: UUID,
    _ctx: TenantContext = Depends(get_tenant_context),
    session: Session = Depends(get_tenant_session),
) -> Response:
    if not delete_alert_rule(session, rule_id):
        raise AlertNotFound(rule_id)
    return Response(status_code=204)


__all__ = ["AlertNotFound", "router"]
