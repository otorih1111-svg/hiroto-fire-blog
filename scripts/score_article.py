#!/usr/bin/env python3
"""
score_article.py
ブログ記事を20軸・100点満点で自動採点するスクリプト

使い方:
  python3 scripts/score_article.py --slug rakuten-point-tsushinhi-zero
  python3 scripts/score_article.py --file src/content/blog/2026-05-31-xxx.md
  python3 scripts/score_article.py --all-drafts   # draft:trueの記事を全件採点
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

BLOG_DIR = Path(__file__).resolve().parents[1]
CONTENT_DIR = BLOG_DIR / "src" / "content" / "blog"
SNS_DIR = BLOG_DIR.parent / "threads_affiliate_system"
sys.path.append(str(SNS_DIR))

from scoring import BLOG_RUBRIC, score_text

PASS_SCORE = BLOG_RUBRIC.pass_score
TARGET_SCORE = BLOG_RUBRIC.pass_score


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """frontmatterとbodyを分離"""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    fm_raw = parts[1]
    body = parts[2].strip()
    fm = {}
    for line in fm_raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"\'')
    return fm, body


def score_article(file_path: Path, verbose: bool = True) -> dict:
    """記事を採点してスコアを返す"""
    content = file_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    title = fm.get("title", "不明")
    slug = fm.get("slug", file_path.stem)

    if verbose:
        print(f"\n📝 採点中: {title}")
        print(f"   ファイル: {file_path.name}")

    result = score_text("blog", content)

    result["slug"] = slug
    result["title"] = title
    result["file"] = str(file_path)
    result["draft"] = fm.get("draft", "false")

    if verbose:
        _print_result(result)

    return result


def _print_result(result: dict):
    total = result.get("total", 0)
    passed = result.get("pass", False)
    status = "✅ 入稿OK" if passed else "❌ 要修正"
    total_points = result.get("total_points", BLOG_RUBRIC.total_points)
    pct = round(total / total_points * 100)

    print(f"\n{'='*50}")
    print(f"  {status}  {total}/{total_points}点（{pct}%）")
    print(f"{'='*50}")

    scores = result.get("scores", {})
    axis_max = result.get("axis_max", BLOG_RUBRIC.axis_max)
    for axis, score in scores.items():
        filled = max(0, min(axis_max, int(score)))
        bar = "█" * filled + "░" * (axis_max - filled)
        print(f"  {axis:<18} {bar} {score}/{axis_max}")

    low = result.get("low_axes", [])
    if low:
        print(f"\n⚠️  低スコア軸: {', '.join(low)}")

    feedback = result.get("feedback", {})
    if feedback:
        print("\n📋 改善ポイント:")
        for axis, msg in feedback.items():
            print(f"  [{axis}] {msg}")


def find_draft_articles() -> list[Path]:
    """draft: true の記事を全件返す"""
    drafts = []
    for md in sorted(CONTENT_DIR.glob("*.md")):
        content = md.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(content)
        if fm.get("draft", "false").lower() == "true":
            drafts.append(md)
    return drafts


def main():
    parser = argparse.ArgumentParser(description="ブログ記事自動採点")
    parser.add_argument("--slug", help="slugで記事を指定")
    parser.add_argument("--file", help="ファイルパスで記事を指定")
    parser.add_argument("--all-drafts", action="store_true", help="draft:trueの記事を全件採点")
    parser.add_argument("--output", help="結果をJSONで保存するファイルパス")
    args = parser.parse_args()

    results = []

    if args.all_drafts:
        drafts = find_draft_articles()
        if not drafts:
            print("✅ draft:trueの記事はありません")
            return
        print(f"📋 下書き記事 {len(drafts)}本を採点します")
        for path in drafts:
            result = score_article(path)
            results.append(result)

    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"❌ ファイルが見つかりません: {path}")
            sys.exit(1)
        results.append(score_article(path))

    elif args.slug:
        # slugかファイル名で検索
        matches = list(CONTENT_DIR.glob(f"*{args.slug}*.md"))
        if not matches:
            print(f"❌ 記事が見つかりません: {args.slug}")
            sys.exit(1)
        results.append(score_article(matches[0]))

    else:
        parser.print_help()
        return

    # サマリー
    if len(results) > 1:
        passed = [r for r in results if r.get("pass")]
        failed = [r for r in results if not r.get("pass")]
        print(f"\n{'='*50}")
        print(f"📊 採点サマリー: {len(passed)}本合格 / {len(failed)}本要修正")
        if failed:
            print("要修正:")
            for r in failed:
                print(f"  ❌ {r['title']} ({r.get('total', 0)}/{BLOG_RUBRIC.total_points}点)")

    # JSON出力
    if args.output:
        out = Path(args.output)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\n💾 結果を保存: {out}")


if __name__ == "__main__":
    main()
