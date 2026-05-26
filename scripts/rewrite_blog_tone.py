"""
ブログ記事本文を「内容はしっかり・でもクスッと笑えてツッコミたくなる」温度感へ
リライトする一括スクリプト。

方針:
- frontmatterは完全に保持
- 本文のみリライト
- 記事の構成・見出し・リンク・SEOキーワードは維持
- ADSENSE_REVIEWコメントは維持
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
BLOG_DIR = SCRIPT_DIR.parent
CONTENT_DIR = BLOG_DIR / "src" / "content" / "blog"
SNS_DIR = BLOG_DIR.parent / "threads_affiliate_system"


def _load_env_key() -> str:
    env_file = SNS_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return ""


try:
    import anthropic
except ImportError:
    print("anthropicライブラリが必要です: pip install anthropic")
    sys.exit(1)


ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY") or _load_env_key()
MODEL = "claude-sonnet-4-6"

PROHIBITED_PATTERNS = [
    "非常に重要なポイントです！",
    "ぜひ活用してみてください！",
]


SYSTEM_PROMPT = """
あなたは日本語ブログのリライト編集者です。

目的:
- ブログ本文を「内容はしっかり・でもクスッと笑えてツッコミたくなる」文体へ変える
- ただし記事の意味・構成・見出し・リンク・SEOキーワードは変えない

絶対条件:
1. frontmatterは出力しない。本文Markdownだけを返す
2. 見出し構成、箇条書き、番号リスト、リンクURL、内部リンク、コメントは維持
3. 内容の主張・結論・情報量・検索意図を変えない
4. 体験していないことを足さない
5. 笑いは記事全体で3〜5箇所までの温度感
6. カッコ内オチまたは自己ツッコミを最低1箇所は入れる
7. 笑いは点在させる。まとめてボケない
8. ADSENSE_REVIEWコメントはそのまま残す
9. スマホで読みやすい改行を優先する
10. 1段落は原則1〜3文までに抑える
11. 話題が切り替わる箇所、感情が動く一文、結論の一文の後は改行する

使ってよい技術:
- カッコ内で短いオチ
- 自己ツッコミ
- 当たり前のことをあえて説明して落とす
- 日常の具体物で比喩する

禁止:
- 「非常に重要なポイントです！」「ぜひ活用してみてください！」などの煽り
- ！の多用
- 「〜すべきです」「〜してください」の連発
- 笑いが多すぎて内容が薄く見える書き換え
- ボケのための作り話

出力:
- リライト後の本文Markdownのみ
- 説明、注釈、前置き、コードブロックは不要
"""


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    end += len("\n---\n")
    return text[:end], text[end:]


def rewrite_body(client: anthropic.Anthropic, path: Path, body: str) -> str:
    user_prompt = f"""
以下はブログ記事の本文Markdownです。
この記事の本文だけを、温度感を整える目的でリライトしてください。

対象ファイル: {path.name}

温度感の基準サンプル:
- 何に使ったっけ……外食？Amazonか？いや、どっちも心当たりしかない
- まあ来月がんばろ（来月も同じことを言う）
- コーヒー2杯を我慢すれば家計が丸見えになります。（コーヒー代も家計簿に記録されます）
- 息子は交際相手じゃないので食費に直します。当たり前ですが。

維持するもの:
- 見出し
- リード文の「悩み→結論→ベネフィット」
- SEOキーワード
- リンク
- 箇条書き
- まとめ

読みやすさルール:
- スマホで読んだときに詰まって見えないよう、改行は多めに入れる
- 1段落は原則1〜3文まで。4文以上の長い段落は分ける
- 箇条書きでない通常本文も、話題が切り替わる場所で素直に段落を分ける
- 内容は変えず、段落だけ細かくしてよい

本文:
{body}
"""
    message = client.messages.create(
        model=MODEL,
        max_tokens=5000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text.strip() + "\n"


def verify_article(path: Path, frontmatter: str, original_body: str, body: str) -> list[str]:
    issues: list[str] = []
    if not frontmatter.startswith("---\n"):
        issues.append("frontmatter_missing")
    if "ADSENSE_REVIEW_START" in frontmatter:
        issues.append("adsense_in_frontmatter")
    if "ADSENSE_REVIEW_START" in original_body and "ADSENSE_REVIEW_START" not in body:
        issues.append("adsense_comment_missing")
    if "（" not in body and "(" not in body and "当たり前ですが" not in body and "当然です" not in body:
        issues.append("no_humor_marker")
    for pattern in PROHIBITED_PATTERNS:
        if pattern in body:
            issues.append(f"prohibited:{pattern}")
    if body.count("！") > 3:
        issues.append("too_many_exclamations")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="ブログ全記事の温度感リライト")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("files", nargs="*", help="対象ファイル名。未指定なら全記事")
    args = parser.parse_args()

    if not ANTHROPIC_KEY:
        print("ANTHROPIC_API_KEY が見つかりません")
        return 1

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    if args.files:
        files = [CONTENT_DIR / name for name in args.files]
    else:
        files = sorted(CONTENT_DIR.glob("*.md"))
    if args.limit > 0:
        files = files[: args.limit]

    print(f"対象記事: {len(files)}本")
    failures = []

    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name}")
        original = path.read_text(encoding="utf-8")
        frontmatter, body = split_frontmatter(original)
        if not frontmatter:
            failures.append((path.name, ["frontmatter_parse_failed"]))
            continue

        rewritten_body = rewrite_body(client, path, body)
        issues = verify_article(path, frontmatter, body, rewritten_body)
        if issues:
            failures.append((path.name, issues))
            print(f"  WARN: {', '.join(issues)}")

        if not args.dry_run:
            path.write_text(frontmatter + rewritten_body, encoding="utf-8")

        time.sleep(0.4)

    print("\n完了")
    if failures:
        print("要確認:")
        for name, issues in failures:
            print(f"- {name}: {', '.join(issues)}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
