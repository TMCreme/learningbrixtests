#!/usr/bin/env python
"""Turn raw Playwright recordings into short, captioned feature videos.

Input  (written by the `demo` fixture):  artifacts/videos/raw/<slug>.webm
                                         artifacts/videos/raw/<slug>.json
Output:                                  artifacts/videos/out/<slug>.mp4
                                         artifacts/videos/out/index.html

Pipeline per video:
  1. Skip anything whose manifest says the test failed — a demo must only ever
     show a feature that actually works.
  2. Rasterise a title card and one caption strip per step (scripts/captions.py).
  3. Composite them onto the footage with ffmpeg `overlay`, time-gated by each
     step's recorded window, capped at VIDEO_MAX_SECONDS.

A .srt is written alongside as a reusable sidecar, but the burn-in does not use
it: this ffmpeg build has no freetype and no libass, so `drawtext` and
`subtitles` are both unavailable. `overlay` is, hence the PNG approach.

Usage:
    python scripts/render_video.py                 # render everything pending
    python scripts/render_video.py <slug> [<slug>] # render specific features
    python scripts/render_video.py --force         # re-render even if current
    python scripts/render_video.py --index-only    # just rebuild the gallery
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ROOT, get_settings  # noqa: E402
from scripts.captions import render_caption, render_title_card  # noqa: E402


TITLE_SECONDS = 2.4
CAPTION_MARGIN_BOTTOM = 42


def srt_timestamp(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def step_windows(manifest: dict, *, cap_s: float,
                 floor_s: float = 0.0) -> list[tuple[str, float, float]]:
    """Resolve each step to a (caption, start, end) window with no blank gaps."""
    steps = manifest.get("steps", [])
    windows: list[tuple[str, float, float]] = []
    for i, step in enumerate(steps):
        start = max(float(step["start_s"]), floor_s)
        end = float(step.get("end_s") or start + 2.0)
        if i + 1 < len(steps):
            end = max(end, float(steps[i + 1]["start_s"]) - 0.05)
        end = min(end, cap_s)
        if end <= start:
            continue
        windows.append((str(step["caption"]).strip(), start, end))
    return windows


def build_srt(manifest: dict, *, cap_s: float) -> str:
    blocks = [
        f"{i}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{caption}\n"
        for i, (caption, start, end) in
        enumerate(step_windows(manifest, cap_s=cap_s), start=1)
    ]
    return "\n".join(blocks)


def ffprobe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except (TypeError, ValueError):
        return 0.0


@dataclass
class RenderResult:
    slug: str
    status: str          # rendered | skipped_failed | skipped_current | error
    output: Path | None = None
    detail: str = ""


def render_one(slug: str, raw_dir: Path, out_dir: Path, *,
               max_seconds: int, width: int, height: int,
               force: bool) -> RenderResult:
    manifest_path = raw_dir / f"{slug}.json"
    video_path = raw_dir / f"{slug}.webm"

    if not manifest_path.exists():
        return RenderResult(slug, "error", detail="no manifest")
    manifest = json.loads(manifest_path.read_text())

    if manifest.get("failed"):
        return RenderResult(slug, "skipped_failed",
                            detail="test failed — not publishing footage")
    if not video_path.exists():
        return RenderResult(slug, "error", detail=f"missing {video_path.name}")

    out_path = out_dir / f"{slug}.mp4"
    if out_path.exists() and not force and \
            out_path.stat().st_mtime >= video_path.stat().st_mtime:
        return RenderResult(slug, "skipped_current", output=out_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_duration = ffprobe_duration(video_path)
    cap_s = max(1.0, min(raw_duration, float(max_seconds)))

    (raw_dir / f"{slug}.srt").write_text(build_srt(manifest, cap_s=cap_s))

    assets = raw_dir / f".{slug}_assets"
    shutil.rmtree(assets, ignore_errors=True)
    assets.mkdir(parents=True, exist_ok=True)

    # The title card is just another overlay pinned to the opening seconds,
    # which avoids a separate concat pass and keeps all timing on one clock.
    layers: list[tuple[Path, str, str, float, float]] = []
    title = render_title_card(
        str(manifest.get("title") or slug),
        str(manifest.get("subtitle") or ""),
        assets / "title.png", width=width, height=height,
    )
    layers.append((title.path, "0", "0", 0.0, TITLE_SECONDS))

    for i, (caption, start, end) in enumerate(
            step_windows(manifest, cap_s=cap_s, floor_s=TITLE_SECONDS)):
        png = render_caption(caption, assets / f"cap{i:03d}.png", video_width=width)
        layers.append((png.path, "(W-w)/2", f"H-h-{CAPTION_MARGIN_BOTTOM}", start, end))

    cmd: list[str] = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path)]
    for png, *_ in layers:
        cmd += ["-loop", "1", "-i", str(png)]

    chain = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[base0]"
    ]
    for idx, (_, x, y, start, end) in enumerate(layers):
        chain.append(
            f"[base{idx}][{idx + 1}:v]overlay=x={x}:y={y}:"
            f"enable='between(t,{start:.2f},{end:.2f})'[base{idx + 1}]"
        )
    chain.append(f"[base{len(layers)}]format=yuv420p[out]")

    cmd += [
        "-filter_complex", ";".join(chain),
        "-map", "[out]",
        "-t", f"{cap_s:.2f}",
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    shutil.rmtree(assets, ignore_errors=True)
    if proc.returncode != 0:
        return RenderResult(slug, "error", detail=proc.stderr.strip()[-500:])
    return RenderResult(slug, "rendered", output=out_path)


def build_index(out_dir: Path, raw_dir: Path) -> Path:
    """Static gallery of every rendered feature video."""
    cards: list[str] = []
    for mp4 in sorted(out_dir.glob("*.mp4")):
        manifest_path = raw_dir / f"{mp4.stem}.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        steps = manifest.get("steps", [])
        cards.append(f"""
    <article class="card">
      <video controls preload="metadata" src="{escape(mp4.name)}"></video>
      <div class="meta">
        <h2>{escape(str(manifest.get('title') or mp4.stem))}</h2>
        <p class="sub">{escape(str(manifest.get('subtitle') or ''))}</p>
        <p class="fid">{escape(str(manifest.get('feature_id') or mp4.stem))}</p>
        <ol>{''.join(f"<li>{escape(str(s['caption']))}</li>" for s in steps)}</ol>
      </div>
    </article>""")

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LearningBrix — Feature Demos</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.5 -apple-system, system-ui, sans-serif; margin: 0;
         padding: 2rem clamp(1rem, 4vw, 3rem); background: Canvas; color: CanvasText; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 .25rem; }}
  .lede {{ opacity: .7; margin: 0 0 2rem; }}
  .grid {{ display: grid; gap: 1.5rem;
           grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }}
  .card {{ border: 1px solid color-mix(in srgb, CanvasText 15%, transparent);
           border-radius: 12px; overflow: hidden; }}
  video {{ width: 100%; display: block; background: #000; }}
  .meta {{ padding: .9rem 1rem 1.1rem; }}
  .meta h2 {{ font-size: 1rem; margin: 0 0 .2rem; }}
  .sub {{ margin: 0 0 .4rem; opacity: .75; font-size: .9rem; }}
  .fid {{ margin: 0 0 .6rem; font-family: ui-monospace, monospace;
          font-size: .75rem; opacity: .55; }}
  ol {{ margin: 0; padding-left: 1.2rem; font-size: .82rem; opacity: .8; }}
</style></head>
<body>
  <h1>LearningBrix — Feature Demos</h1>
  <p class="lede">{len(cards)} feature{'' if len(cards) == 1 else 's'}, each recorded from a passing integration test.</p>
  <div class="grid">{''.join(cards)}</div>
</body></html>
"""
    index = out_dir / "index.html"
    index.write_text(html)
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="*", help="specific feature slugs to render")
    parser.add_argument("--force", action="store_true", help="re-render up-to-date videos")
    parser.add_argument("--index-only", action="store_true", help="only rebuild the gallery")
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found on PATH. Install it (brew install ffmpeg).", file=sys.stderr)
        return 2

    settings = get_settings()
    raw_dir = Path(settings.video_raw_dir)
    out_dir = Path(settings.video_out_dir)
    raw_dir = raw_dir if raw_dir.is_absolute() else ROOT / raw_dir
    out_dir = out_dir if out_dir.is_absolute() else ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.index_only:
        print(f"index: {build_index(out_dir, raw_dir)}")
        return 0

    slugs = args.slugs or sorted(p.stem for p in raw_dir.glob("*.json"))
    if not slugs:
        print(f"Nothing to render — no manifests in {raw_dir}")
        return 0

    failures = 0
    for slug in slugs:
        result = render_one(
            slug, raw_dir, out_dir,
            max_seconds=settings.video_max_seconds,
            width=settings.video_width,
            height=settings.video_height,
            force=args.force,
        )
        marker = {"rendered": "✓", "skipped_current": "·",
                  "skipped_failed": "⊘", "error": "✗"}[result.status]
        detail = f" — {result.detail}" if result.detail else ""
        print(f"{marker} {result.slug}: {result.status}{detail}")
        if result.status == "error":
            failures += 1

    print(f"index: {build_index(out_dir, raw_dir)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
