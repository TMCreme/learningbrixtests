"""Step recording for feature demo videos.

A demo test narrates itself. Every meaningful UI action is wrapped in
``demo.step(...)``, which records the elapsed time at which that action began.
After the video is flushed, ``scripts/render_video.py`` turns those timestamps
into burned-in captions.

    def test_school_admin_creates_class(demo, school):
        with demo.step("Log in as SchoolAdmin"):
            login_as(demo.page, ..., school.school_admin)
        with demo.step("Open Classes & Timetables"):
            classes = ClassesPage(demo.page, ...).open()
        with demo.step('Create class "Grade 6"'):
            classes.create_class(name="Grade 6")

Timings are measured against the same clock the video starts on, so a caption
lands on the frames that show the action. ``dwell_ms`` holds the caption on
screen a little past the action so a viewer can read it.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# A caption shorter than this is padded out so it does not flash past.
MIN_CAPTION_SECONDS = 1.8


@dataclass
class Step:
    caption: str
    start_s: float
    end_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "caption": self.caption,
            "start_s": round(self.start_s, 3),
            "end_s": round(max(self.end_s, self.start_s + MIN_CAPTION_SECONDS), 3),
        }


@dataclass
class DemoRecorder:
    """Collects timed captions for one feature video."""

    feature_id: str
    title: str
    subtitle: str = ""
    steps: list[Step] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic)
    failed: bool = False

    def reset_clock(self) -> None:
        """Re-zero the clock at the moment recording actually begins."""
        self._t0 = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    @contextmanager
    def step(self, caption: str, *, dwell_ms: int = 600) -> Iterator[Step]:
        """Record one narrated action.

        The dwell pause is deliberate: it is what makes the footage readable,
        and it applies only to video runs, never to the assertion suite.
        """
        entry = Step(caption=caption, start_s=self.elapsed)
        self.steps.append(entry)
        try:
            yield entry
        finally:
            if dwell_ms > 0:
                time.sleep(dwell_ms / 1000)
            entry.end_s = self.elapsed

    def note(self, caption: str) -> None:
        """Record an instantaneous caption (no wrapped action)."""
        self.steps.append(Step(caption=caption, start_s=self.elapsed))

    def to_manifest(self, *, video_path: Path, duration_s: float) -> dict:
        return {
            "feature_id": self.feature_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "video": str(video_path),
            "duration_s": round(duration_s, 3),
            "failed": self.failed,
            "steps": [s.as_dict() for s in self.steps],
        }

    def write_manifest(self, path: Path, *, video_path: Path, duration_s: float) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            self.to_manifest(video_path=video_path, duration_s=duration_s),
            indent=2,
        ))
        return path


def slugify(value: str) -> str:
    keep = [c.lower() if c.isalnum() else "_" for c in value]
    slug = "".join(keep)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "unnamed"
