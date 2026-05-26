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

CATEGORY_RULES = {
    "副業実録": "笑いは記事全体で2〜3箇所。体験談の流れの中に自然に入れる。",
    "AI活用": "笑いは記事全体で1〜2箇所。情報や手順が主役。",
    "FIRE設計": "笑いは記事全体で1〜2箇所。数字と根拠が主役。",
    "シングル父の日常": "笑いは記事全体で3箇所程度。感情と共感が主役。",
    "買ってよかった": "笑いは記事全体で2〜3箇所。レビューの正直感を優先する。",
    "ひろとについて": "笑いは記事全体で3箇所程度。人間味を優先する。",
}


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
5. 笑いの量は記事カテゴリの指定に従う
6. ボケは文体の流れの中に自然に入れる
7. カッコ書きでオチを入れない
8. ADSENSE_REVIEWコメントはそのまま残す
9. スマホで読みやすい改行を優先する
10. 1文ごとに改行を入れる
11. 1段落は最大3〜4行までに抑える
12. リード文の最初の1行は、具体的な場面や数字で始める
13. リード文の構成「悩み→結論→ベネフィット」は変えない

使ってよい技術:
- 自己ツッコミ
- 当たり前のことをあえて説明して落とす
- 日常の具体物で比喩する
- 文体の流れの中にさらっと一言落とす

禁止:
- 「非常に重要なポイントです！」「ぜひ活用してみてください！」などの煽り
- ！の多用
- 「〜すべきです」「〜してください」の連発
- 笑いが多すぎて内容が薄く見える書き換え
- ボケのための作り話
- カッコ内でオチを入れること

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


def extract_category(frontmatter: str) -> str:
    match = re.search(r"^category:\s*(.+)$", frontmatter, re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip().strip('"').strip("'")


def rewrite_body(client: anthropic.Anthropic, path: Path, category: str, body: str) -> str:
    category_rule = CATEGORY_RULES.get(category, "笑いは記事全体で2〜3箇所まで。内容が主役。")
    user_prompt = f"""
以下はブログ記事の本文Markdownです。
この記事の本文だけを、温度感を整える目的でリライトしてください。

対象ファイル: {path.name}
カテゴリ: {category}

温度感の基準サンプル:
- 何に使ったっけ……外食？Amazonか？いや、どっちも心当たりしかない
- まあ来月がんばろ。来月も同じことを言う。
- コーヒー2杯を我慢すれば家計が丸見えになります。コーヒー代もちゃんと記録されます。
- 息子は交際相手じゃないので食費に直します。当たり前ですが。
- 副業収益、今月347円。振込手数料で消えた。

笑いの量ルール:
{category_rule}

維持するもの:
- 見出し
- リード文の「悩み→結論→ベネフィット」
- SEOキーワード
- リンク
- 箇条書き
- まとめ

読みやすさルール:
- スマホで読んだときに詰まって見えないよう、改行は多めに入れる
- 1文ごとに改行を入れる
- 1段落は最大3〜4行まで。長い段落は分ける
- 箇条書きでない通常本文も、話題が切り替わる場所で素直に段落を分ける
- 内容は変えず、段落だけ細かくしてよい

リード文ルール:
- 最初の1行は、具体的な場面・数字・状況が浮かぶ書き出しにする
- 作り話は禁止。記事内容とひろとの実体験に沿って具体化する
- その後の「悩み→結論→ベネフィット」の並びは変えない

ボケの入れ方:
- カッコ書きは使わない
- 文体の流れの中に自然な一言として入れる
- 笑いのために文章を長くしない

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
    humor_markers = [
        "当たり前ですが",
        "当然です",
        "いや、",
        "我ながら",
        "自分で言う",
        "振込手数料で消えた",
    ]
    if not any(marker in body for marker in humor_markers):
        issues.append("no_humor_marker")
    if "（" in body or "(" in body:
        issues.append("paren_present")
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
        category = extract_category(frontmatter)

        rewritten_body = rewrite_body(client, path, category, body)
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
