"""Tests for the effort collector."""

import json
import os
import time
from pathlib import Path

from claude_telemetry.effort import collect_effort_usage


def _assistant(msg_id, model, effort, ts, inp=10, out=5, cc=0, cr=0, **extra):
    entry = {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "id": msg_id,
            "model": model,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_creation_input_tokens": cc,
                "cache_read_input_tokens": cr,
            },
        },
        **extra,
    }
    if effort is not None:
        entry["effort"] = effort
    return entry


def _write(path: Path, entries) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _claude_dir(tmp_path: Path, entries, project="C--Users-dev-Documents-my-app") -> Path:
    _write(tmp_path / "projects" / project / "session-1.jsonl", entries)
    return tmp_path


# Midday UTC so the local date matches on any test machine timezone (UTC-11..UTC+11).
TS = "2026-04-01T12:00:00.000Z"


class TestCollectEffortUsage:
    def test_groups_by_model_and_effort(self, tmp_path: Path) -> None:
        d = _claude_dir(tmp_path, [
            _assistant("m1", "claude-opus-4-6", "high", TS, inp=100, out=50),
            _assistant("m2", "claude-opus-4-6", "high", TS, inp=10, out=5, cr=1000),
            _assistant("m3", "claude-opus-4-6", "low", TS, inp=1, out=1),
            _assistant("m4", "claude-sonnet-4-6", "high", TS, inp=2, out=2),
        ])
        records = collect_effort_usage(d)
        by_key = {(r.model, r.effort): r for r in records}

        assert len(records) == 3
        high = by_key[("claude-opus-4-6", "high")]
        assert high.messages == 2
        assert high.input_tokens == 110
        assert high.output_tokens == 55
        assert high.cache_read_tokens == 1000
        assert high.total_tokens == 110 + 55 + 1000
        assert high.date == "2026-04-01"
        assert high.project == "my-app"

    def test_streamed_message_counted_once(self, tmp_path: Path) -> None:
        # Claude Code writes one line per content block, repeating id + usage.
        d = _claude_dir(tmp_path, [
            _assistant("m1", "claude-opus-4-6", "max", TS, out=3),
            _assistant("m1", "claude-opus-4-6", "max", TS, out=40),
        ])
        [r] = collect_effort_usage(d)
        assert r.messages == 1
        assert r.output_tokens == 40  # last line wins (final usage)

    def test_missing_effort_is_unknown(self, tmp_path: Path) -> None:
        d = _claude_dir(tmp_path, [_assistant("m1", "claude-opus-4-6", None, TS)])
        [r] = collect_effort_usage(d)
        assert r.effort == "unknown"

    def test_per_turn_effort_fallback(self, tmp_path: Path) -> None:
        d = _claude_dir(tmp_path, [
            _assistant("m1", "claude-opus-4-6", None, TS, perTurnEffort="xhigh"),
        ])
        [r] = collect_effort_usage(d)
        assert r.effort == "xhigh"

    def test_skips_non_assistant_and_synthetic(self, tmp_path: Path) -> None:
        d = _claude_dir(tmp_path, [
            {"type": "user", "timestamp": TS, "message": {"role": "user", "usage": {}}},
            _assistant("m1", "<synthetic>", "high", TS),
            _assistant("m2", "claude-opus-4-6", "high", TS),
        ])
        records = collect_effort_usage(d)
        assert [r.model for r in records] == ["claude-opus-4-6"]

    def test_ignores_malformed_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "projects" / "proj" / "s.jsonl"
        path.parent.mkdir(parents=True)
        good = json.dumps(_assistant("m1", "claude-opus-4-6", "high", TS))
        path.write_text('{"usage": broken\n' + good + "\n", encoding="utf-8")
        assert len(collect_effort_usage(tmp_path)) == 1

    def test_since_filters_older_days(self, tmp_path: Path) -> None:
        d = _claude_dir(tmp_path, [
            _assistant("m1", "claude-opus-4-6", "high", "2026-03-01T12:00:00.000Z"),
            _assistant("m2", "claude-opus-4-6", "high", TS),
        ])
        records = collect_effort_usage(d, since="2026-03-15")
        assert [r.date for r in records] == ["2026-04-01"]

    def test_since_skips_untouched_files(self, tmp_path: Path) -> None:
        d = _claude_dir(tmp_path, [_assistant("m1", "claude-opus-4-6", "high", TS)])
        old = time.time() - 30 * 86400
        f = tmp_path / "projects" / "C--Users-dev-Documents-my-app" / "session-1.jsonl"
        os.utime(f, (old, old))
        assert collect_effort_usage(d, since="2099-01-01") == []

    def test_dedupes_across_files(self, tmp_path: Path) -> None:
        # Resumed sessions can copy earlier messages into a new transcript.
        entry = _assistant("m1", "claude-opus-4-6", "high", TS)
        _write(tmp_path / "projects" / "proj" / "a.jsonl", [entry])
        _write(tmp_path / "projects" / "proj" / "b.jsonl", [entry])
        [r] = collect_effort_usage(tmp_path)
        assert r.messages == 1

    def test_missing_projects_dir(self, tmp_path: Path) -> None:
        assert collect_effort_usage(tmp_path / "nope") == []
