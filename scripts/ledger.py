#!/usr/bin/env python
"""The feature ledger — the loop's memory.

Without this, every iteration of an autonomous run would re-do work it already
finished. The ledger records, per feature unit, how far it got and what went
wrong, so a run can be interrupted, resumed, or restarted at any point and pick
up exactly where it left off.

State machine:

    pending ──claim──▶ claimed ──▶ test_written ──▶ passing ──▶ video_done
       ▲                  │                            │
       └──── release ─────┘                            └──▶ blocked

`blocked` is terminal for that unit *only* — every other unit keeps moving. That
is the whole point: one unresolvable feature must never stall the run.

CLI (agents call this via Bash):
    python scripts/ledger.py init                  # seed from config/features.yaml
    python scripts/ledger.py stats
    python scripts/ledger.py next --limit 4 --agent a1   # claim next N units
    python scripts/ledger.py set <id> --status passing
    python scripts/ledger.py set <id> --status blocked --reason "needs SMTP creds"
    python scripts/ledger.py show <id>
    python scripts/ledger.py release --stale-minutes 45  # reclaim dead agents' units
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from config.settings import ROOT  # noqa: E402


LEDGER_PATH = ROOT / "state" / "feature_ledger.json"
FEATURES_PATH = ROOT / "config" / "features.yaml"
BLOCKERS_PATH = ROOT / "state" / "blockers.md"

STATUSES = ("pending", "claimed", "test_written", "passing", "video_done", "blocked")
MAX_ATTEMPTS = 3


def is_finished(entry: dict) -> bool:
    """Whether this unit needs no further work.

    A video unit is finished only once its video is rendered. A unit that
    records no video — every negative/access-denied unit — is finished as soon
    as its test passes, because `video_done` is a state it can never reach.
    Treating `video_done` as the only terminal status left the 31 negative units
    parked at `passing` forever: they were never counted as done, `remaining`
    could never reach zero, and `next` kept re-claiming work that was already
    complete.
    """
    status = entry.get("status")
    if status in ("video_done", "blocked"):
        return True
    return status == "passing" and not entry.get("video", True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def locked_ledger(*, create: bool = False) -> Iterator[dict]:
    """Read-modify-write under an exclusive lock.

    Parallel agents mutate this file concurrently; without the lock two agents
    can claim the same unit or clobber each other's status writes.
    """
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LEDGER_PATH.exists():
        if not create:
            raise SystemExit(
                f"No ledger at {LEDGER_PATH}. Run: python scripts/ledger.py init"
            )
        LEDGER_PATH.write_text(json.dumps({"features": {}, "created": now()}, indent=2))

    with LEDGER_PATH.open("r+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            data = json.load(fh)
            yield data
            fh.seek(0)
            fh.truncate()
            json.dump(data, fh, indent=2)
            fh.write("\n")
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def load_feature_defs() -> list[dict]:
    if not FEATURES_PATH.exists():
        raise SystemExit(
            f"No feature queue at {FEATURES_PATH}. "
            f"Run: python scripts/build_feature_queue.py"
        )
    raw = yaml.safe_load(FEATURES_PATH.read_text()) or {}
    features = raw.get("features") or []
    if not features:
        raise SystemExit(f"{FEATURES_PATH} defines no features.")
    return features


def cmd_init(args) -> int:
    defs = load_feature_defs()
    with locked_ledger(create=True) as data:
        entries = data.setdefault("features", {})
        added = 0
        for spec in defs:
            fid = spec["id"]
            if fid in entries and not args.reset:
                # Keep progress; refresh the descriptive fields in case the
                # queue definition changed.
                entries[fid].update({
                    k: spec.get(k) for k in
                    ("module", "title", "subtitle", "roles", "scenario",
                     "test_path", "video")
                })
                continue
            entries[fid] = {
                "id": fid,
                "module": spec.get("module"),
                "title": spec.get("title"),
                "subtitle": spec.get("subtitle"),
                "roles": spec.get("roles", []),
                "scenario": spec.get("scenario"),
                "test_path": spec.get("test_path"),
                "video": bool(spec.get("video", True)),
                "status": "pending",
                "attempts": 0,
                "agent": None,
                "claimed_at": None,
                "last_error": None,
                "blocked_reason": None,
                "video_path": None,
                "updated": now(),
            }
            added += 1
        data["updated"] = now()
    print(f"ledger: {len(defs)} features defined, {added} newly seeded → {LEDGER_PATH}")
    return 0


def cmd_stats(args) -> int:
    with locked_ledger() as data:
        entries = list(data["features"].values())
    counts = {s: 0 for s in STATUSES}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    total = len(entries)
    blocked = counts["blocked"]
    # Counts negative units finished at `passing` as well as rendered videos —
    # see is_finished().
    done = sum(1 for e in entries if is_finished(e) and e["status"] != "blocked")
    print(json.dumps({
        "total": total,
        "done": done,
        "blocked": blocked,
        "remaining": total - done - blocked,
        "videos_rendered": counts["video_done"],
        "by_status": counts,
        "complete": (total - done - blocked) == 0,
    }, indent=2))
    return 0


def cmd_next(args) -> int:
    """Claim up to N workable units, preferring least-attempted."""
    claimed: list[dict] = []
    with locked_ledger() as data:
        candidates = [
            e for e in data["features"].values()
            if not is_finished(e)
            and e["attempts"] < MAX_ATTEMPTS
            and (e["status"] == "pending" or e.get("agent") in (None, args.agent))
        ]
        candidates.sort(key=lambda e: (e["attempts"], e["id"]))
        for entry in candidates[: args.limit]:
            entry["status"] = "claimed" if entry["status"] == "pending" else entry["status"]
            entry["agent"] = args.agent
            entry["claimed_at"] = now()
            entry["updated"] = now()
            claimed.append(entry)
        data["updated"] = now()
    print(json.dumps(claimed, indent=2))
    return 0


def cmd_set(args) -> int:
    if args.status not in STATUSES:
        raise SystemExit(f"status must be one of {STATUSES}")
    with locked_ledger() as data:
        entry = data["features"].get(args.id)
        if entry is None:
            raise SystemExit(f"unknown feature id: {args.id}")

        if args.status in ("test_written", "passing") and entry["status"] == "claimed":
            entry["attempts"] += 1
        if args.status == "blocked":
            entry["blocked_reason"] = args.reason or "unspecified"
            _append_blocker(entry)
        if args.error is not None:
            entry["last_error"] = args.error[:2000]
        if args.video_path:
            entry["video_path"] = args.video_path
        if args.test_path:
            entry["test_path"] = args.test_path

        entry["status"] = args.status
        entry["updated"] = now()
        if is_finished(entry):
            entry["agent"] = None
        data["updated"] = now()
        print(json.dumps(entry, indent=2))
    return 0


def cmd_show(args) -> int:
    with locked_ledger() as data:
        entry = data["features"].get(args.id)
    if entry is None:
        raise SystemExit(f"unknown feature id: {args.id}")
    print(json.dumps(entry, indent=2))
    return 0


def cmd_release(args) -> int:
    """Return units held by agents that died mid-flight back to the queue."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=args.stale_minutes)
    released = []
    with locked_ledger() as data:
        for entry in data["features"].values():
            if is_finished(entry) or entry.get("claimed_at") is None:
                continue
            try:
                claimed_at = datetime.fromisoformat(entry["claimed_at"])
            except ValueError:
                continue
            if claimed_at < cutoff:
                entry["status"] = "pending"
                entry["agent"] = None
                entry["claimed_at"] = None
                entry["updated"] = now()
                released.append(entry["id"])
        data["updated"] = now()
    print(json.dumps({"released": released}, indent=2))
    return 0


def _append_blocker(entry: dict) -> None:
    """Append to the human-facing blocker log.

    This is the file to read when a run finishes with blocked units — it is the
    only thing in the loop that asks for a human.
    """
    BLOCKERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = "" if BLOCKERS_PATH.exists() else (
        "# Blockers\n\n"
        "Feature units the agents could not resolve on their own. Everything\n"
        "here needs a human decision; the run continued without them.\n\n"
    )
    with BLOCKERS_PATH.open("a") as fh:
        if header:
            fh.write(header)
        fh.write(
            f"## {entry['id']} — {now()}\n\n"
            f"- **Module:** {entry.get('module')}\n"
            f"- **Attempts:** {entry.get('attempts')}\n"
            f"- **Reason:** {entry.get('blocked_reason')}\n"
            f"- **Last error:**\n\n```\n{(entry.get('last_error') or '')[:1200]}\n```\n\n"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="seed the ledger from config/features.yaml")
    p_init.add_argument("--reset", action="store_true", help="discard existing progress")
    p_init.set_defaults(func=cmd_init)

    sub.add_parser("stats", help="progress summary as JSON").set_defaults(func=cmd_stats)

    p_next = sub.add_parser("next", help="claim the next workable units")
    p_next.add_argument("--limit", type=int, default=1)
    p_next.add_argument("--agent", default="unknown")
    p_next.set_defaults(func=cmd_next)

    p_set = sub.add_parser("set", help="update a unit's status")
    p_set.add_argument("id")
    p_set.add_argument("--status", required=True, choices=STATUSES)
    p_set.add_argument("--error", default=None)
    p_set.add_argument("--reason", default=None, help="required when status=blocked")
    p_set.add_argument("--video-path", default=None)
    p_set.add_argument("--test-path", default=None)
    p_set.set_defaults(func=cmd_set)

    p_show = sub.add_parser("show", help="print one unit")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_rel = sub.add_parser("release", help="reclaim units from dead agents")
    p_rel.add_argument("--stale-minutes", type=int, default=45)
    p_rel.set_defaults(func=cmd_release)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
