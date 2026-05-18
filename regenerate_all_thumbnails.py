#!/usr/bin/env python3
"""既存ブログ記事のサムネイルを一括再生成し、ogImageを補完する。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

BLOG_ROOT = Path(__file__).resolve().parent
BLOG_DIR = BLOG_ROOT / "src" / "content" / "blog"
THUMBNAIL_DIR = BLOG_ROOT / "public" / "images" / "thumbnails"
THUMBNAIL_SCRIPT = BLOG_ROOT.parent / "threads_affiliate_system" / "scripts" / "generate_thumbnail.py"


def _extract_frontmatter(content: str) -> tuple[str, str] | None:
    if not content.startswith("---\n"):
        return None
    end = content.find("\n---", 4)
    if end == -1:
        return None
    return content[4:end], content[end + 4 :]


def _read_value(frontmatter: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}:\s*[\"']?(.+?)[\"']?\s*$", frontmatter, re.MULTILINE)
    return match.group(1).strip().strip('"').strip("'") if match else None


def _add_og_image_if_missing(path: Path, slug: str, content: str) -> bool:
    parts = _extract_frontmatter(content)
    if not parts:
        return False
    frontmatter, body = parts
    if re.search(r"^ogImage:\s*.+$", frontmatter, re.MULTILINE):
        return False

    og_line = f"ogImage: '/images/thumbnails/{slug}.png'"
    category_match = re.search(r"^category:\s*.*$", frontmatter, re.MULTILINE)
    if category_match:
        insert_at = category_match.end()
        frontmatter = frontmatter[:insert_at] + "\n" + og_line + frontmatter[insert_at:]
    else:
        frontmatter = frontmatter.rstrip() + "\n" + og_line

    path.write_text(f"---\n{frontmatter}\n---{body}", encoding="utf-8")
    return True


def main() -> int:
    if not THUMBNAIL_SCRIPT.exists():
        print(f"サムネイル生成スクリプトが見つかりません: {THUMBNAIL_SCRIPT}")
        return 1

    os.makedirs(THUMBNAIL_DIR, exist_ok=True)
    md_files = sorted(path for path in BLOG_DIR.iterdir() if path.suffix == ".md")
    success_count = 0
    og_added_count = 0

    for filepath in md_files:
        slug = filepath.stem
        content = filepath.read_text(encoding="utf-8")
        parts = _extract_frontmatter(content)
        frontmatter = parts[0] if parts else ""
        title = _read_value(frontmatter, "title") or slug
        category = _read_value(frontmatter, "category") or "副業実録"
        output_path = THUMBNAIL_DIR / f"{slug}.png"

        print(f"生成中：{slug}")
        result = subprocess.run(
            [
                sys.executable,
                str(THUMBNAIL_SCRIPT),
                "--title", title,
                "--category", category,
                "--output", str(output_path),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            success_count += 1
            print(f"  → 成功：{output_path}")
        else:
            print(f"  → 失敗：{result.stderr.strip() or result.stdout.strip()}")
            continue

        if _add_og_image_if_missing(filepath, slug, content):
            og_added_count += 1
            print("  → ogImageを追加")
        else:
            print("  → ogImageは既存のためスキップ")

    print(f"\n完了：サムネイル {success_count}/{len(md_files)} 件、ogImage追加 {og_added_count} 件")
    return 0 if success_count == len(md_files) else 1


if __name__ == "__main__":
    raise SystemExit(main())
