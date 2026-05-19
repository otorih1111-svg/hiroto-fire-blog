#!/usr/bin/env python3
"""
ブログ記事用のOGPサムネイルを生成する。

単体:
  python3 scripts/generate_thumbnail.py --title "記事タイトル" --category "AI活用" --output public/images/thumbnails/sample.png

一括:
  python3 scripts/generate_thumbnail.py --all
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BLOG_DIR = ROOT / "src" / "content" / "blog"
OUT_DIR = ROOT / "public" / "images" / "thumbnails"

WIDTH = 1200
HEIGHT = 630
BRAND = "ひろと｜hiroto-fire.com"

CATEGORY_COLORS = {
    "AI活用": ("#F7FFF2", "#2E5F0D", "#3B6D11"),
    "副業実録": ("#3B6D11", "#FFFFFF", "#EAF6DF"),
    "FIRE設計": ("#FFFFFF", "#17220F", "#3B6D11"),
    "シングル父の日常": ("#3B6D11", "#FFFFFF", "#EAF6DF"),
    "買ってよかった": ("#FFFFFF", "#17220F", "#3B6D11"),
}

FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W9.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W9.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/HelveticaNeue.ttc",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _visual_len(text: str) -> float:
    total = 0.0
    for char in text:
        if unicodedata.east_asian_width(char) in {"F", "W", "A"}:
            total += 1.0
        else:
            total += 0.55
    return total


def _wrap_text(text: str, max_units: float) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        if current and _visual_len(trial) > max_units:
            lines.append(current.rstrip())
            current = char.lstrip()
        else:
            current = trial
    if current:
        lines.append(current.rstrip())
    return lines[:4]


def _draw_centered_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], lines: list[str], font: ImageFont.FreeTypeFont, fill: str) -> None:
    x1, y1, x2, y2 = box
    line_gap = 18
    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])
    total_h = sum(line_heights) + line_gap * max(0, len(lines) - 1)
    y = y1 + ((y2 - y1) - total_h) // 2
    for line, line_w, line_h in zip(lines, line_widths, line_heights):
        x = x1 + ((x2 - x1) - line_w) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h + line_gap


def generate_thumbnail(title: str, category: str, output_path: str | Path) -> Path:
    bg, text_color, accent = CATEGORY_COLORS.get(category, CATEGORY_COLORS["副業実録"])
    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)

    # 控えめな紙面感を出す背景装飾。本文を邪魔しない薄さに留める。
    if bg != "#FFFFFF":
        draw.rectangle((0, 0, WIDTH, 630), fill=bg)
        draw.polygon([(880, 0), (1200, 0), (1200, 630), (1030, 630)], fill="#315B10")
        draw.line((72, 120, 1128, 120), fill="#FFFFFF", width=2)
        draw.line((72, 516, 1128, 516), fill="#FFFFFF", width=2)
    else:
        draw.rectangle((0, 0, WIDTH, 630), fill=bg)
        draw.rectangle((0, 0, WIDTH, 18), fill=accent)
        draw.rectangle((72, 104, 1128, 526), outline="#D9E7CF", width=3)
        draw.polygon([(930, 18), (1200, 18), (1200, 630), (1050, 630)], fill="#F1F7EC")

    label_font = _font(34)
    title_font = _font(66)
    brand_font = _font(26)

    # カテゴリラベル
    label_text = category
    label_bbox = draw.textbbox((0, 0), label_text, font=label_font)
    label_w = label_bbox[2] - label_bbox[0] + 54
    label_h = 58
    label_fill = "#FFFFFF" if bg != "#FFFFFF" else accent
    label_text_fill = accent if bg != "#FFFFFF" else "#FFFFFF"
    draw.rounded_rectangle((72, 48, 72 + label_w, 48 + label_h), radius=0, fill=label_fill)
    draw.text((99, 58), label_text, font=label_font, fill=label_text_fill)

    # タイトル
    lines = _wrap_text(title, max_units=17.5)
    if len(lines) >= 4:
        title_font = _font(56)
    _draw_centered_text(draw, (88, 142, 1112, 500), lines, title_font, text_color)

    # ブランド
    brand_fill = "#DDE8D4" if bg != "#FFFFFF" else "#516149"
    brand_bbox = draw.textbbox((0, 0), BRAND, font=brand_font)
    draw.text((WIDTH - (brand_bbox[2] - brand_bbox[0]) - 72, 558), BRAND, font=brand_font, fill=brand_fill)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return output_path


def _read_frontmatter(path: Path) -> tuple[dict[str, str], str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, "", text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, "", text
    raw = text[4:end]
    body = text[end + 4 :]
    data: dict[str, str] = {}
    for line in raw.splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        data[key] = value.strip().strip('"').strip("'")
    return data, raw, body


def _set_frontmatter_value(raw: str, key: str, value: str) -> str:
    line = f"{key}: '{value}'"
    pattern = re.compile(rf"^{re.escape(key)}:\s*.*$", re.MULTILINE)
    if pattern.search(raw):
        return pattern.sub(line, raw)
    insert_after = re.search(r"^category:\s*.*$", raw, flags=re.MULTILINE)
    if insert_after:
        pos = insert_after.end()
        return raw[:pos] + "\n" + line + raw[pos:]
    return raw.rstrip() + "\n" + line


def generate_all(update_frontmatter: bool = True) -> list[Path]:
    generated: list[Path] = []
    for md_path in sorted(BLOG_DIR.glob("*.md")):
        data, raw, body = _read_frontmatter(md_path)
        title = data.get("title")
        category = data.get("category", "副業実録")
        if not title:
            continue
        slug = md_path.stem
        og_path = f"/images/thumbnails/{slug}.png"
        out_path = OUT_DIR / f"{slug}.png"
        generate_thumbnail(title, category, out_path)
        generated.append(out_path)
        if update_frontmatter and raw:
            updated = _set_frontmatter_value(raw, "ogImage", og_path)
            md_path.write_text(f"---\n{updated}\n---{body}", encoding="utf-8")
    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description="ブログ記事サムネイル生成")
    parser.add_argument("--title")
    parser.add_argument("--category", default="副業実録")
    parser.add_argument("--output")
    parser.add_argument("--all", action="store_true", help="src/content/blog配下の全記事を生成")
    parser.add_argument("--no-frontmatter", action="store_true")
    args = parser.parse_args()

    if args.all:
        generated = generate_all(update_frontmatter=not args.no_frontmatter)
        print(f"generated={len(generated)}")
        for path in generated:
            print(path)
        return

    if not args.title or not args.output:
        parser.error("--title and --output are required unless --all is used")
    path = generate_thumbnail(args.title, args.category, args.output)
    print(path)


if __name__ == "__main__":
    main()
