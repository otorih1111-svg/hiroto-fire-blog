#!/usr/bin/env python3
"""
score_article.py
ブログ記事を14軸・70点満点で自動採点するスクリプト

使い方:
  python3 scripts/score_article.py --slug rakuten-point-tsushinhi-zero
  python3 scripts/score_article.py --file src/content/blog/2026-05-31-xxx.md
  python3 scripts/score_article.py --all-drafts   # draft:trueの記事を全件採点
"""

from __future__ import annotations

import sys
import os
import json
import re
import argparse
from pathlib import Path

BLOG_DIR = Path(__file__).resolve().parents[1]
CONTENT_DIR = BLOG_DIR / "src" / "content" / "blog"
SNS_DIR = BLOG_DIR.parent / "threads_affiliate_system"

PASS_SCORE = 56   # 80% = 入稿OK
TARGET_SCORE = 63  # 90% = 目標

SCORING_PROMPT = """あなたはブログ記事の品質審査員です。以下の記事を14軸・70点満点で採点し、必ずJSON形式のみで返してください。説明文は不要です。

採点基準（各軸0〜5点）:
1. 悩み解決: 読者の悩みに明確に答えているか
2. 面白さ・人間味: 体験談・クスッとする一文が入っているか
3. 役立ち度: 具体的な数字・手順・情報があるか
4. 読みやすさ: 1文が短い・段落が適切・スマホで読みやすいか
5. 独自性: ひろとにしか書けない体験・視点があるか
6. SEO: 本文にキーワードが自然に入っているか
7. タイトル・description: タイトル27文字以内・description80〜120文字か（frontmatterで確認）
8. 構成の流れ: 悩み→結論→体験→行動の流れか
9. 内部リンク: 関連記事へのリンクが入っているか（0=なし、5=2本以上）
10. 導線設計: 案件や次のアクションへの流れが自然か
11. CTA: まとめ後に次の行動が明確か
12. ルール準拠: ズボラ感・ポンコツ感・クスッとが入っているか
13. 正確性: 数字・情報に誤りがないか
14. 画像・サムネ: 本文内に![...]画像があるか・ogImageが設定されているか

返答はこのJSONのみ（```json```不要）:
{"scores":{"悩み解決":0,"面白さ・人間味":0,"役立ち度":0,"読みやすさ":0,"独自性":0,"SEO":0,"タイトル・description":0,"構成の流れ":0,"内部リンク":0,"導線設計":0,"CTA":0,"ルール準拠":0,"正確性":0,"画像・サムネ":0},"total":0,"pass":false,"low_axes":[],"feedback":{},"rewrite_instructions":""}

記事:
{article_content}"""


def _load_env_key() -> str:
    env_file = SNS_DIR / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def _get_client():
    try:
        import anthropic
    except ImportError:
        print("❌ anthropicライブラリが必要: pip install anthropic")
        sys.exit(1)
    api_key = os.environ.get("ANTHROPIC_API_KEY") or _load_env_key()
    if not api_key:
        print("❌ ANTHROPIC_API_KEYが設定されていません")
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


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

    client = _get_client()

    prompt = SCORING_PROMPT.replace("{article_content}", content)

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text

    # JSONを抽出（複数パターン対応）
    raw = raw.strip()
    json_str = None
    # パターン1: ```json ... ```
    m = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if m:
        json_str = m.group(1)
    else:
        # パターン2: ``` ... ```
        m = re.search(r"```\s*(.*?)\s*```", raw, re.DOTALL)
        if m:
            json_str = m.group(1)
        else:
            # パターン3: { ... } を直接探す
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            json_str = m.group(0) if m else "{}"

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        print(f"⚠️  JSON解析に失敗しました。生のレスポンス:\n{raw[:500]}")
        result = {}

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
    pct = round(total / 70 * 100)

    print(f"\n{'='*50}")
    print(f"  {status}  {total}/70点（{pct}%）")
    print(f"{'='*50}")

    scores = result.get("scores", {})
    for axis, score in scores.items():
        bar = "█" * score + "░" * (5 - score)
        print(f"  {axis:<18} {bar} {score}/5")

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
                print(f"  ❌ {r['title']} ({r.get('total', 0)}/70点)")

    # JSON出力
    if args.output:
        out = Path(args.output)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\n💾 結果を保存: {out}")


if __name__ == "__main__":
    main()
