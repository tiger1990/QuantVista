"""Notification wire DTOs (QV-050). ``04`` §3.7 — the in-app notification center feed."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Notification(BaseModel):
    id: str
    type: str
    payload: dict[str, Any]
    read_at: str | None
    created_at: str
