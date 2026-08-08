"""Render title cards and caption strips as PNGs.

The ffmpeg available here is built without freetype and libass, so neither the
`drawtext` nor the `subtitles` filter exists. Text is therefore rasterised with
Pillow and composited by ffmpeg's `overlay` filter, which this build does have.
That also buys real word-wrapping and rounded backing plates, which drawtext
cannot do.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

CAPTION_BG = (12, 14, 20, 214)
CAPTION_FG = (255, 255, 255, 255)
TITLE_SCRIM = (8, 10, 16, 232)
TITLE_FG = (255, 255, 255, 255)
SUBTITLE_FG = (170, 198, 255, 255)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
          max_width: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(lines)) < len(text.strip()):
        lines[-1] = lines[-1].rstrip(" .,") + "…"
    return lines or [""]


@dataclass
class Rendered:
    path: Path
    width: int
    height: int


def render_caption(text: str, out_path: Path, *, video_width: int,
                   font_size: int = 24, max_lines: int = 2,
                   pad_x: int = 22, pad_y: int = 14, radius: int = 12) -> Rendered:
    """A centred caption strip sized to its own text."""
    font = load_font(font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    max_text_w = int(video_width * 0.86) - 2 * pad_x
    lines = _wrap(probe, text.strip(), font, max_text_w, max_lines)

    line_h = font_size + 8
    text_w = max(int(probe.textlength(line, font=font)) for line in lines)
    box_w = min(video_width - 32, text_w + 2 * pad_x)
    box_h = line_h * len(lines) + 2 * pad_y

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=radius, fill=CAPTION_BG)
    for i, line in enumerate(lines):
        w = probe.textlength(line, font=font)
        draw.text(((box_w - w) / 2, pad_y + i * line_h), line, font=font, fill=CAPTION_FG)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return Rendered(out_path, box_w, box_h)


def render_title_card(title: str, subtitle: str, out_path: Path, *,
                      width: int, height: int) -> Rendered:
    """Full-frame scrim with the feature name, shown over the opening seconds."""
    img = Image.new("RGBA", (width, height), TITLE_SCRIM)
    draw = ImageDraw.Draw(img)

    title_font = load_font(max(34, int(height * 0.072)))
    sub_font = load_font(max(20, int(height * 0.040)))

    title_lines = _wrap(draw, title.strip(), title_font, int(width * 0.82), 2)
    sub_lines = _wrap(draw, subtitle.strip(), sub_font, int(width * 0.78), 2) if subtitle.strip() else []

    title_lh = title_font.size + 12
    sub_lh = sub_font.size + 8
    block_h = title_lh * len(title_lines) + (18 + sub_lh * len(sub_lines) if sub_lines else 0)
    y = (height - block_h) / 2

    for line in title_lines:
        w = draw.textlength(line, font=title_font)
        draw.text(((width - w) / 2, y), line, font=title_font, fill=TITLE_FG)
        y += title_lh
    if sub_lines:
        y += 18
        for line in sub_lines:
            w = draw.textlength(line, font=sub_font)
            draw.text(((width - w) / 2, y), line, font=sub_font, fill=SUBTITLE_FG)
            y += sub_lh

    # Thin accent rule under the block, a cheap way to make the card look
    # deliberate rather than like a debug overlay.
    rule_w = int(width * 0.12)
    draw.rounded_rectangle(
        ((width - rule_w) / 2, y + 16, (width + rule_w) / 2, y + 20),
        radius=2, fill=SUBTITLE_FG,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return Rendered(out_path, width, height)
