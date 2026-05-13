"""
generate_blog_post.py
SNS投稿（Threads・X）からAstroブログ記事を自動生成するスクリプト

【使い方】
  python3 generate_blog_post.py                    # 直近SNS投稿から自動生成
  python3 generate_blog_post.py --theme "AI副業の始め方"  # テーマ指定
  python3 generate_blog_post.py --category AI活用   # カテゴリ指定
  python3 generate_blog_post.py --dry-run           # 生成のみ（ファイル保存なし）
  python3 generate_blog_post.py --from-file post.json  # 投稿JSONから生成

【出力】
  src/content/blog/YYYY-MM-DD-slug.md
"""

from __future__ import annotations

import sys
import os
import json
import re
import argparse
import datetime
import unicodedata
from pathlib import Path

# プロジェクトルート設定
BLOG_DIR = Path(__file__).parent
CONTENT_DIR = BLOG_DIR / "src" / "content" / "blog"
SNS_SYSTEM_DIR = Path(__file__).parent.parent / "threads_affiliate_system"

# Claude API
try:
    import anthropic
    ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY") or _load_env_key()
except ImportError:
    print("anthropicライブラリが必要: pip install anthropic")
    sys.exit(1)


def _load_env_key() -> str:
    """親ディレクトリの.envからAPIキーを読む"""
    env_file = SNS_SYSTEM_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return ""


def _slugify(text: str) -> str:
    """日本語文字列をスラッグ（英数字ハイフン）に変換"""
    # よく使うキーワードの英語マッピング
    mapping = {
        "副業": "fukugyo",
        "AI": "ai",
        "FIRE": "fire",
        "シングル父": "single-father",
        "息子": "musuko",
        "楽天": "rakuten",
        "投資": "toshi",
        "お金": "okane",
        "始め方": "hajimekata",
        "実録": "jitsuroku",
        "活用": "katsuyo",
        "自動化": "jidoka",
        "保険": "hoken",
        "節約": "setsuyaku",
        "収入": "shunyu",
    }
    result = text
    for ja, en in mapping.items():
        result = result.replace(ja, en)
    # 残った非ASCII文字を除去してハイフンでつなぐ
    result = re.sub(r'[^\w\s-]', '', result, flags=re.ASCII)
    result = re.sub(r'\s+', '-', result.strip())
    result = re.sub(r'-+', '-', result).lower()
    return result or "post"


def _get_recent_sns_posts(days: int = 7) -> list[dict]:
    """直近のThreads・X投稿をposted/x_postedディレクトリから取得"""
    posts = []
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)

    for subdir in ["data/posted", "data/x_posted"]:
        posted_dir = SNS_SYSTEM_DIR / subdir
        if not posted_dir.exists():
            continue
        for json_file in sorted(posted_dir.glob("*.json"), reverse=True)[:10]:
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                posts.append({
                    "text": data.get("text", data.get("content", "")),
                    "type": data.get("type", "helpful"),
                    "source": subdir,
                })
            except Exception:
                continue

    return posts[:10]


CATEGORIES = ['副業実録', 'AI活用', 'FIRE設計', 'シングル父の日常', '買ってよかった']

CATEGORY_KEYWORDS = {
    '副業実録': ['副業', '収益', 'アフィリ', '稼ぐ', '仕組み', '継続', 'フォロワー'],
    'AI活用': ['AI', 'Claude', 'ChatGPT', '自動化', '生成', 'プロンプト'],
    'FIRE設計': ['FIRE', '投資', 'NISA', '資産', '老後', '積立', '証券', '保険', 'FP'],
    'シングル父の日常': ['息子', '子ども', '子育て', '離婚', '運動会', '宿題', '家族'],
    '買ってよかった': ['楽天', '買った', 'おすすめ', 'ふるさと', 'ポイント', '節約'],
}


def _detect_category(theme: str) -> str:
    """テーマからカテゴリを自動判定"""
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in theme for kw in keywords):
            return cat
    return '副業実録'


def generate_blog_post(
    theme: str = "",
    category: str = "",
    sns_posts: list[dict] | None = None,
    dry_run: bool = False,
    line_url: str = "https://lin.ee/XXXXXXXX",
) -> dict:
    """
    Claude APIを呼んでブログ記事を生成する

    Returns:
        {"slug": str, "path": Path, "title": str, "content": str}
    """
    # カテゴリ自動判定
    if not category:
        category = _detect_category(theme) if theme else '副業実録'
    if category not in CATEGORIES:
        category = '副業実録'

    # SNS投稿をコンテキストとして整形
    sns_context = ""
    if sns_posts:
        sns_context = "\n\n【最近のSNS投稿（参考にしてください）】\n"
        for i, p in enumerate(sns_posts[:5], 1):
            text = p.get("text", "").strip()
            if text:
                sns_context += f"\n--- 投稿{i} ---\n{text}\n"

    # プロンプト構築
    system_prompt = """あなたは「ひろと」という人物のブログ記事ライターです。

## ひろとのキャラクター
- 40代・千葉県在住・シングル父（10歳の息子）
- 会社員をしながら副業×AIでFIREを目指している
- 離婚経験あり・副業収益はまだほぼゼロ
- 正直・誇張なし・体験したことだけを話すスタイル
- 神話の法則（試練→成長→変容）を物語として発信

## 文体
- ひらがな多め・やわらかい文体
- 「正直に言う」「本当のことを書く」という語り口
- 細部まで描写（五感・数字・具体的場面）
- 抽象的な言葉を使わない
- 売り込まない・欲しがらせる書き方
- 1文は短め（20〜30文字）

## 記事構成
1. 引きのある冒頭（1〜3行）
2. 具体的な体験・エピソード（見出しH2で区切る）
3. 気づき・学び
4. 読者への問いかけまたは次のアクション
5. 締め（LINE誘導を自然に）

## 出力形式（Markdown）
frontmatterなしで、H1タイトルから始めてください。
記事の長さ：1500〜2500文字
見出し：H2を3〜5個使用
最後の段落の後に「---」で区切り、LINEへの誘導文を書いてください。"""

    user_prompt = f"""以下の条件でブログ記事を書いてください。

カテゴリ：{category}
{'テーマ：' + theme if theme else 'テーマは自由に設定してください。ひろとの最近の体験を元に。'}
{sns_context}

## 注意事項
- PR・アフィリエイト商品は含めない（純粋な体験談・ノウハウ記事）
- ひろとの「今の状況（収益ほぼゼロ・フォロワー約100人・3ヶ月継続中）」を活かす
- 読者は「副業したいけど時間がない・何から始めていいかわからない40代」
- LINEのURLは {line_url}

## 出力形式
1行目：記事タイトル（# で始めるMarkdown見出し）
2行目以降：本文Markdown

descriptionとして使える1〜2文のサマリーをコメント<!-- description: ... -->として冒頭に入れてください。"""

    print(f"\n🤖 Claude APIで記事生成中...")
    print(f"   カテゴリ：{category}")
    if theme:
        print(f"   テーマ：{theme}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
    )

    raw_content = message.content[0].text

    # タイトル抽出
    title_match = re.search(r'^#\s+(.+)$', raw_content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "無題の記事"

    # description抽出
    desc_match = re.search(r'<!--\s*description:\s*(.+?)\s*-->', raw_content)
    description = desc_match.group(1).strip() if desc_match else f"{category}に関するひろとの体験談。"

    # frontmatterなしの本文（#タイトルとdescriptionコメント除去）
    body = raw_content
    if desc_match:
        body = body.replace(desc_match.group(0), "").strip()

    # スラッグ生成
    today = datetime.date.today().isoformat()
    slug_base = _slugify(theme or title)[:40]
    slug = f"{today}-{slug_base}"

    # Markdownファイル生成（frontmatter + 本文）
    tags = _extract_tags(title + " " + body, category)
    frontmatter = f"""---
title: "{title.replace('"', '\\"')}"
description: "{description.replace('"', '\\"')}"
pubDate: {today}
category: {category}
tags: {json.dumps(tags, ensure_ascii=False)}
draft: false
affiliate: false
---

"""
    full_content = frontmatter + body

    result = {
        "slug": slug,
        "title": title,
        "description": description,
        "category": category,
        "content": full_content,
        "path": CONTENT_DIR / f"{slug}.md",
    }

    if not dry_run:
        CONTENT_DIR.mkdir(parents=True, exist_ok=True)
        result["path"].write_text(full_content, encoding="utf-8")
        print(f"\n✅ 記事を保存しました：")
        print(f"   {result['path'].relative_to(BLOG_DIR)}")
    else:
        print(f"\n[DRY RUN] 記事生成完了（保存なし）")
        print(f"   タイトル：{title}")
        print(f"   スラッグ：{slug}")
        print(f"\n--- 本文プレビュー（先頭300文字）---")
        print(full_content[:300])
        print("...")

    return result


def _extract_tags(text: str, category: str) -> list[str]:
    """テキストからタグを抽出"""
    keyword_tags = {
        "AI": ["AI", "自動化", "効率化"],
        "副業": ["副業", "在宅", "フリーランス"],
        "FIRE": ["FIRE", "投資", "資産形成"],
        "楽天": ["楽天", "楽天アフィリ"],
        "シングル父": ["シングル父", "子育て"],
        "継続": ["継続", "習慣"],
    }
    tags = []
    for keyword, tag_list in keyword_tags.items():
        if keyword in text:
            tags.extend(tag_list[:1])
    # カテゴリ由来のタグ追加
    cat_tags = {
        '副業実録': ['副業'],
        'AI活用': ['AI'],
        'FIRE設計': ['FIRE'],
        'シングル父の日常': ['シングル父'],
        '買ってよかった': ['楽天'],
    }
    for t in cat_tags.get(category, []):
        if t not in tags:
            tags.append(t)
    return list(dict.fromkeys(tags))[:5]  # 重複除去・最大5個


def generate_from_weekly_posts(dry_run: bool = False) -> list[dict]:
    """
    週次バッチ：直近1週間のSNS投稿から複数記事を生成
    テーマが重複しないように3記事を生成する
    """
    sns_posts = _get_recent_sns_posts(days=7)
    if not sns_posts:
        print("⚠️  直近SNS投稿が見つかりませんでした。デフォルトテーマで生成します。")

    default_themes = [
        ("副業を3ヶ月続けて気づいたこと", "副業実録"),
        ("AIを使い始めて変わった副業のやり方", "AI活用"),
        ("シングル父のFIRE設計：今の資産状況を正直に", "FIRE設計"),
    ]

    results = []
    for theme, category in default_themes:
        print(f"\n{'='*50}")
        result = generate_blog_post(
            theme=theme,
            category=category,
            sns_posts=sns_posts,
            dry_run=dry_run,
        )
        results.append(result)

    return results


# ============================================================
# エントリポイント
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNS投稿からAstroブログ記事を自動生成")
    parser.add_argument("--theme", type=str, default="", help="記事テーマ")
    parser.add_argument("--category", type=str, default="", help="カテゴリ（副業実録/AI活用/FIRE設計/シングル父の日常/買ってよかった）")
    parser.add_argument("--dry-run", action="store_true", help="生成のみ・ファイル保存なし")
    parser.add_argument("--weekly", action="store_true", help="週次バッチ（3記事同時生成）")
    parser.add_argument("--from-file", type=str, default="", help="投稿JSONファイルから生成")
    args = parser.parse_args()

    # APIキー確認
    api_key = os.environ.get("ANTHROPIC_API_KEY") or _load_env_key()
    if not api_key:
        print("❌ ANTHROPIC_API_KEYが設定されていません。")
        print("   .envファイルに ANTHROPIC_API_KEY=sk-ant-... を追加してください。")
        sys.exit(1)

    if args.weekly:
        results = generate_from_weekly_posts(dry_run=args.dry_run)
        print(f"\n{'='*50}")
        print(f"✅ {len(results)}件の記事を生成しました。")
    elif args.from_file:
        post_data = json.loads(Path(args.from_file).read_text(encoding="utf-8"))
        text = post_data.get("text", post_data.get("content", ""))
        result = generate_blog_post(
            theme=text[:50] if text else args.theme,
            category=args.category,
            sns_posts=[post_data],
            dry_run=args.dry_run,
        )
    else:
        result = generate_blog_post(
            theme=args.theme,
            category=args.category,
            sns_posts=_get_recent_sns_posts(),
            dry_run=args.dry_run,
        )
        print(f"\n✅ 完了: /blog/{result['slug']}/")
