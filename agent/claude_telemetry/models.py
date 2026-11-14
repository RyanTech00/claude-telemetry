"""Data models for Claude Usage Tracker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class DailyUsage:
    date: str
    project: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class EffortUsage:
    """Daily token usage per (project, model, reasoning effort level)."""
    date: str
    project: str
    model: str
    effort: str
    messages: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0


@dataclass
class SessionUsage:
    session_id: str
    project: str
    project_path: str | None = None
    models: list[str] = field(default_factory=list)
    is_subagent: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    last_activity_at: str | None = None


@dataclass
class RateLimit:
    timestamp: str
    window_5h_percent: float | None = None
    window_1w_percent: float | None = None
    session_cost_usd: float | None = None
    session_duration_seconds: int | None = None


@dataclass
class StatsExtra:
    total_sessions: int | None = None
    total_messages: int | None = None
    longest_session_messages: int | None = None
    longest_session_duration_ms: int | None = None
    first_session_date: str | None = None
    hour_counts: dict | None = None
    daily_activity: list[dict] | None = None
    model_usage: list[dict] | None = None


@dataclass
class BlockUsage:
    block_start: str
    block_end: str
    is_active: bool = False
    is_gap: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    models: list[str] = field(default_factory=list)
    duration_minutes: int = 0
    entries: int = 0


@dataclass
class SyncResult:
    source: str
    records_upserted: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
