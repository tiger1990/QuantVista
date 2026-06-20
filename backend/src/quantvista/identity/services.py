"""identity application service (QV-006) — register / login / refresh / me.

Access-path rules (RLS): registration and membership lookups touch RLS tables before any
tenant context exists, so they run on the **privileged** session (admin bypasses RLS).
`refresh_tokens`/`users` are global → app session. `/me` reads RLS tables with a
**tenant-bound** session.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from quantvista.core.config import get_settings
from quantvista.core.db import privileged_session_scope, session_scope
from quantvista.identity import repositories as repo
from quantvista.identity import security
from quantvista.identity.models import (
    EmailAlreadyExists,
    InvalidCredentials,
    InvalidRefreshToken,
    IssuedTokens,
    MeView,
    Principal,
)

logger = logging.getLogger(__name__)


class AuthService:
    """Concrete `IAuthService` (QV-006)."""

    def register(self, email: str, password: str, name: str | None) -> Principal:
        email = email.strip().lower()
        with privileged_session_scope() as session:
            if repo.email_exists(session, email):
                raise EmailAlreadyExists(email)
            tenant_id = repo.insert_tenant(session, name or email)
            user_id = repo.insert_user(session, email, security.hash_password(password), name)
            repo.insert_membership(session, tenant_id, user_id, "owner")
            repo.insert_free_subscription(session, tenant_id)
        # Email-verification stub: real delivery is a later story. Never log the password.
        logger.info("auth.register email=%s verification=stub-skipped", email)
        return Principal(user_id=user_id, tenant_id=tenant_id, role="owner")

    def authenticate(self, email: str, password: str) -> Principal:
        email = email.strip().lower()
        with privileged_session_scope() as session:  # reads RLS memberships pre-context
            row = repo.find_user_by_email(session, email)
            if row is None or row.password_hash is None:
                raise InvalidCredentials()
            if not security.verify_password(row.password_hash, password):
                raise InvalidCredentials()
            membership = repo.primary_membership(session, row.id)
            if membership is None:
                raise InvalidCredentials()
        return Principal(user_id=row.id, tenant_id=membership.tenant_id, role=membership.role)

    def issue_tokens(self, principal: Principal) -> IssuedTokens:
        raw, token_hash = security.new_refresh_token()
        expires_at = datetime.now(UTC) + timedelta(seconds=get_settings().refresh_token_ttl_seconds)
        with session_scope() as session:  # refresh_tokens is global
            repo.insert_refresh_token(session, principal.user_id, uuid4(), token_hash, expires_at)
        access = security.create_access_token(
            principal.user_id, principal.tenant_id, principal.role
        )
        return IssuedTokens(access_token=access, refresh_token_raw=raw)

    def rotate(self, raw_refresh: str) -> IssuedTokens:
        token_hash = security.hash_refresh_token(raw_refresh)
        raw_new, hash_new = security.new_refresh_token()
        reuse = False
        expired = False
        user_id: UUID | None = None
        # IMPORTANT: do the writes inside the transaction and only RAISE after it commits,
        # otherwise revoking the family on reuse would be rolled back by session_scope.
        with session_scope() as session:
            found = repo.find_refresh_by_hash(session, token_hash)
            if found is None:
                raise InvalidRefreshToken("unknown")  # nothing written; rollback is a no-op
            if found.revoked_at is not None:
                # Reuse: a token presented after it was already rotated/revoked.
                repo.revoke_family(session, found.family_id)
                reuse = True
            elif found.expires_at <= datetime.now(UTC):
                repo.revoke_refresh(session, found.id)
                expired = True
            else:
                expires_at = datetime.now(UTC) + timedelta(
                    seconds=get_settings().refresh_token_ttl_seconds
                )
                new_id = repo.insert_refresh_token(
                    session, found.user_id, found.family_id, hash_new, expires_at
                )
                repo.revoke_refresh(session, found.id, replaced_by=new_id)
                user_id = found.user_id
        if reuse:
            raise InvalidRefreshToken("reuse-detected")
        if expired:
            raise InvalidRefreshToken("expired")
        assert user_id is not None  # narrowed: the only remaining branch set it
        principal = self._principal_for(user_id)
        access = security.create_access_token(
            principal.user_id, principal.tenant_id, principal.role
        )
        return IssuedTokens(access_token=access, refresh_token_raw=raw_new)

    def logout(self, raw_refresh: str) -> None:
        with session_scope() as session:
            found = repo.find_refresh_by_hash(session, security.hash_refresh_token(raw_refresh))
            if found is not None:
                repo.revoke_refresh(session, found.id)

    def me(self, principal: Principal) -> MeView:
        with privileged_session_scope() as session:
            user = repo.find_user_by_id(session, principal.user_id)
        if user is None:
            raise InvalidCredentials()
        with session_scope(principal.tenant_id) as session:  # RLS: tenant-bound
            t_name = repo.tenant_name(session, principal.tenant_id) or ""
            ent = repo.entitlements_for_tenant(session, principal.tenant_id)
        return MeView(
            user_id=principal.user_id,
            email=user.email,
            name=user.name,
            tenant_id=principal.tenant_id,
            tenant_name=t_name,
            role=principal.role,
            entitlements=ent,
        )

    def _principal_for(self, user_id: UUID) -> Principal:
        with privileged_session_scope() as session:
            membership = repo.primary_membership(session, user_id)
        if membership is None:
            raise InvalidRefreshToken("no-membership")
        return Principal(user_id=user_id, tenant_id=membership.tenant_id, role=membership.role)
