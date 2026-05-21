#!/usr/bin/env python3
"""
ブログ記事サムネイル生成の互換ラッパー。

現在の正規デザインは threads_affiliate_system 側の
イラストベース生成スクリプトを使う。

単体:
  python3 scripts/generate_thumbnail.py --title "記事タイトル" --category "AI活用" --output public/images/thumbnails/sample.png

一括:
  python3 scripts/generate_thumbnail.py --all
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELEGATE_SCRIPT = ROOT.parent / "threads_affiliate_system" / "scripts" / "generate_thumbnail.py"
BLOG_DIR = ROOT / "src" / "content" / "blog"


def _run_delegate(args: list[str]) -> int:
    if not DELEGATE_SCRIPT.exists():
        print(f"サムネイル生成スクリプトが見つかりません: {DELEGATE_SCRIPT}", file=sys.stderr)
        return 1
    result = subprocess.run([sys.executable, str(DELEGATE_SCRIPT), *args])
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="ブログ記事サムネイル生成")
    parser.add_argument("--title")
    parser.add_argument("--category", default="副業実録")
    parser.add_argument("--output")
    parser.add_argument("--all", action="store_true", help="src/content/blog配下の全記事を生成")
    parser.add_argument("--no-frontmatter", action="store_true")
    args = parser.parse_args()

    if args.all:
        delegate_args = ["--all-blog"]
        return _run_delegate(delegate_args)

    if not args.title or not args.output:
        parser.error("--title and --output are required unless --all is used")

    return _run_delegate(
        [
            "--title",
            args.title,
            "--category",
            args.category,
            "--output",
            args.output,
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
