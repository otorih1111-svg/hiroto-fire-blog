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

PASS_SCORE = 67   # 実質90%相当（自動採点が約5〜10点甘い傾向のため補正）
TARGET_SCORE = 67  # 合格基準と同値

SCORING_PROMPT = """あなたはブログ記事の厳格な品質審査員です。以下の記事を14軸・70点満点で採点し、必ずJSON形式のみで返してください。説明文は不要です。

【重要な採点方針】
- 採点は厳しく行う。「まあOK」は3点、「明確に良い」は4点、「非常に優れている」のみ5点
- 5点は滅多に与えない。4点でも十分良い評価
- 迷ったら低い方の点数をつける
- 「入っている」だけでは高得点にしない。「効果的に使われている」かを見る

採点基準（各軸0〜5点）:
1. 悩み解決: 読者の具体的な悩みに明確に答えているか（一般論はマイナス）
2. 面白さ・人間味: クスッとする一文・自己ツッコミが自然に入っているか（1箇所だけでは3点止まり）
3. 役立ち度: 具体的な数字・手順・実測値があるか（「便利です」で終わる記述はマイナス）
4. 読みやすさ: 全段落が1〜3文以内か・スマホで詰まって見えないか（1箇所でも4文以上の段落があれば3点以下）
5. 独自性: ひろと（シングル父・40代・息子のため）にしか書けない体験・視点が複数あるか
6. SEO: メインキーワードが自然に本文の複数箇所に入っているか
7. タイトル・description: タイトルが27文字以内か・descriptionが80〜120文字か（どちらか1つでもNGなら2点以下）
8. 構成の流れ: 冒頭が「悩み→結論→ベネフィット」になっているか・H2の順番が読者の疑問に沿っているか
9. 内部リンク: 関連記事へのリンクが入っているか（0本=0点、1本=3点、2本以上=5点）
10. 導線設計: アフィリリンクまたは次のアクションへの流れが自然か（ADSENSE_REVIEW中は評価保留で3点固定）
11. CTA: まとめ後に読者の次の1アクションが具体的に示されているか
12. ルール準拠: ズボラ感・ポンコツ感・クスッとが各1箇所以上あるか（どれか1つ欠けていたら3点以下）
13. 正確性: 数字・制度・情報に誤りがないか（免責表記があるか）
14. 画像・サムネ: 本文内に![...]画像があるか・ogImageが設定されているか（どちらか欠けていたら3点以下）

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

    raw = response.content[0].text.strip()

    # JSONを抽出（複数パターン対応・優先順位順）
    json_str = None
    for pattern in [
        r"```json\s*([\s\S]*?)\s*```",   # ```json ... ```
        r"```\s*([\s\S]*?)\s*```",        # ``` ... ```
        r"(\{[\s\S]*\})",                  # { ... } 直接
    ]:
        m = re.search(pattern, raw)
        if m:
            candidate = m.group(1).strip()
            try:
                json.loads(candidate)  # 有効なJSONか確認
                json_str = candidate
                break
            except json.JSONDecodeError:
                continue

    try:
        result = json.loads(json_str) if json_str else {}
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
