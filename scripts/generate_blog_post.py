"""
scripts/generate_blog_post.py
SNS投稿（Threads・X）からAstroブログ記事を自動生成するスクリプト

【使い方】
  python3 scripts/generate_blog_post.py                    # 直近SNS投稿から自動生成
  python3 scripts/generate_blog_post.py --theme "AI副業の始め方"  # テーマ指定
  python3 scripts/generate_blog_post.py --category AI活用   # カテゴリ指定
  python3 scripts/generate_blog_post.py --dry-run           # 生成のみ（ファイル保存なし）
  python3 scripts/generate_blog_post.py --weekly            # 週次バッチ（3記事同時生成）

【出力】
  src/content/blog/YYYY-MM-DD-slug.md  （LINE誘導バナーを末尾に自動挿入）

【note連携】
  --note オプション付きで実行すると、生成した記事を
  threads_affiliate_system/generate_note_daily.py に渡すための
  note_draft.json も同時出力します。
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

# ---- パス設定 ----
SCRIPT_DIR   = Path(__file__).parent           # scripts/
BLOG_DIR     = SCRIPT_DIR.parent               # hiroto-fire-blog/
CONTENT_DIR  = BLOG_DIR / "src" / "content" / "blog"
SNS_ROOT     = BLOG_DIR.parent                 # claud code/
SNS_DIR      = SNS_ROOT / "threads_affiliate_system"
X_POSTS_FILE = SNS_ROOT / "x_posts.md"
NOTE_DRAFT   = SNS_DIR / "data" / "note_draft.json"
BLOG_BASE_URL = "https://hiroto-fire.com"

# LINE URL（.envから読む・フォールバックあり）
LINE_URL = os.environ.get("PUBLIC_LINE_URL", "https://line.me/R/ti/p/%40103khwdx")


def _load_env_key() -> str:
    """threads_affiliate_system/.envからAPIキーを読む"""
    env_file = SNS_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return ""


try:
    import anthropic
    ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY") or _load_env_key()
except ImportError:
    print("anthropicライブラリが必要: pip install anthropic")
    sys.exit(1)


def _slugify(text: str) -> str:
    mapping = {
        "副業": "fukugyo", "AI": "ai", "FIRE": "fire",
        "シングル父": "single-father", "息子": "musuko",
        "楽天": "rakuten", "投資": "toshi", "お金": "okane",
        "始め方": "hajimekata", "実録": "jitsuroku", "活用": "katsuyo",
        "自動化": "jidoka", "保険": "hoken", "節約": "setsuyaku",
        "収入": "shunyu",
    }
    result = text
    for ja, en in mapping.items():
        result = result.replace(ja, en)
    result = re.sub(r'[^\w\s-]', '', result, flags=re.ASCII)
    result = re.sub(r'\s+', '-', result.strip())
    result = re.sub(r'-+', '-', result).lower()
    return result or "post"


def _get_recent_sns_posts(days: int = 7) -> list[dict]:
    posts = []
    for subdir in ["data/posted", "data/x_posted"]:
        posted_dir = SNS_DIR / subdir
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
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in theme for kw in keywords):
            return cat
    return '副業実録'


def _make_line_banner_md() -> str:
    """記事末尾に挿入するLINE誘導バナー（Markdown）"""
    return f"""
---

## 📩 LINE登録で「副業実録レポート」無料プレゼント中

シングル父がAIと副業で這い上がった実録レポートをLINE登録者に無料配布しています。

[👉 LINEで無料登録する]({LINE_URL})

---
"""


def generate_blog_post(
    theme: str = "",
    category: str = "",
    sns_posts: list[dict] | None = None,
    dry_run: bool = False,
    with_note: bool = False,
) -> dict:
    """
    Claude APIでブログ記事を生成し、src/content/blog/ に保存する。

    Returns:
        {"slug", "path", "title", "description", "category", "content"}
    """
    if not category:
        category = _detect_category(theme) if theme else '副業実録'
    if category not in CATEGORIES:
        category = '副業実録'

    sns_context = ""
    if sns_posts:
        sns_context = "\n\n【最近のSNS投稿（参考にしてください）】\n"
        for i, p in enumerate(sns_posts[:5], 1):
            text = p.get("text", "").strip()
            if text:
                sns_context += f"\n--- 投稿{i} ---\n{text}\n"

    system_prompt = """あなたは「ひろと」という人物のブログ記事ライターです。

## ひろとのキャラクター
- 40代・千葉県在住・シングル父（10歳の息子）
- 会社員をしながら副業×AIでFIREを目指している
- 離婚経験あり・副業収益はまだほぼゼロ
- 正直・誇張なし・体験したことだけを話すスタイル
- 核心の一文：「子どもに『お金で諦めた』と言わせたくない」

## 物語構造：神話の法則（ヒーローズジャーニー）
記事全体をこの流れで構成する：
1. 日常の世界（共感できる現状・閉塞感）
2. 冒険の始まり（きっかけ・最初の一歩）
3. 試練（失敗・壁・葛藤）
4. 成長・気づき（具体的な変化・学び）
5. 読者への還元（あなたも同じはず、という問いかけ）

## PASONA構成（セクション設計に使う）
- **P**roblem：読者の痛みを言語化する
- **A**ffinity：「同じだ」と思わせる自己開示
- **S**olution：体験から得た解決策・気づき
- **O**ffer：具体的な行動・次のステップ
- **N**arrow：「あなたに向けた話」と絞り込む
- **A**ction：自然なCTA（押しつけない）

## 冒頭の型（必ずどれかを使う）
- 数字・実績型：「3ヶ月続けてわかったこと」「1日1時間で変わったこと」
- 共感・本音型：「正直に言う」「誰にも言えなかったけど」「かっこ悪いけど書く」
- 否定・反転型：「〇〇は間違いだった」「ずっと思い込んでた」
- 感情・情景型：「息子に〇〇と言われた日」「あの夜のことを書く」
- 逆説型：「失敗したのに感謝してる理由」「遠回りで正解だったと思うこと」

## 文体ルール
- ひらがな多め・やわらかい文体
- 1文は20〜30文字
- 抽象的な言葉を使わない（「努力」→「毎朝5時に起きた」）
- 細部まで描写する（五感・数字・具体的な場面）
- 説明でなく描写する
- 売り込まない・欲しがらせる書き方

## 記事構成（H2見出し3〜5個）
1. 引きのある冒頭（冒頭の型を使う・1〜3行）
2. Problem：読者の痛みを言語化（共感）
3. Affinity + Solution：ひろとの体験談（試練→気づき）
4. 具体的な変化・学び
5. Narrow + Action：読者への問いかけ・次の一歩
※LINEバナーは後で自動挿入するので書かなくてよい

## 出力形式
frontmatterなしで、H1タイトルから始めてください。
記事の長さ：1500〜2500文字"""

    user_prompt = f"""以下の条件でブログ記事を書いてください。

カテゴリ：{category}
{'テーマ：' + theme if theme else 'テーマは自由に設定してください。ひろとの最近の体験を元に。'}
{sns_context}

## 注意事項
- PR・アフィリエイト商品は含めない（純粋な体験談・ノウハウ記事）
- ひろとの現状：収益ほぼゼロ・フォロワー約100人・3ヶ月継続中
- 読者像：副業したいけど時間がない・何から始めていいかわからない40代
- 「稼げます」「簡単です」は絶対に書かない
- 失敗・試行錯誤・正直さがひろとの強み。隠さず書く

## 出力形式
1行目：記事タイトル（# で始めるMarkdown見出し）
2行目以降：本文Markdown
descriptionとして使える1〜2文のサマリーを <!-- description: ... --> として冒頭に入れてください。"""

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

    title_match = re.search(r'^#\s+(.+)$', raw_content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "無題の記事"

    desc_match = re.search(r'<!--\s*description:\s*(.+?)\s*-->', raw_content)
    description = desc_match.group(1).strip() if desc_match else f"{category}に関するひろとの体験談。"

    body = raw_content
    if desc_match:
        body = body.replace(desc_match.group(0), "").strip()

    # 末尾にLINEバナーを自動挿入
    body = body.rstrip() + "\n" + _make_line_banner_md()

    today = datetime.date.today().isoformat()
    slug_base = _slugify(theme or title)[:40]
    slug = f"{today}-{slug_base}"

    tags = _extract_tags(title + " " + body, category)
    title_escaped = title.replace('"', '\\"')
    description_escaped = description.replace('"', '\\"')
    frontmatter = f"""---
title: "{title_escaped}"
description: "{description_escaped}"
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
        "blog_url": f"{BLOG_BASE_URL}/blog/{slug}/",
    }

    if not dry_run:
        CONTENT_DIR.mkdir(parents=True, exist_ok=True)
        result["path"].write_text(full_content, encoding="utf-8")
        print(f"\n✅ 記事を保存しました：")
        print(f"   {result['path'].relative_to(BLOG_DIR)}")

        # サムネイル自動生成
        _generate_thumbnail_for_post(result)

        # note連携：note_draft.jsonを出力
        if with_note:
            NOTE_DRAFT.parent.mkdir(parents=True, exist_ok=True)
            note_draft = {
                "title": title,
                "body": body,
                "category": category,
                "blog_url": result["blog_url"],
                "generated_at": datetime.datetime.now().isoformat(),
            }
            NOTE_DRAFT.write_text(json.dumps(note_draft, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"   note下書き保存: {NOTE_DRAFT}")
    else:
        print(f"\n[DRY RUN] 記事生成完了（保存なし）")
        print(f"   タイトル：{title}")
        print(f"   スラッグ：{slug}")
        print(f"\n--- 本文プレビュー（先頭300文字）---")
        print(full_content[:300])
        print("...")

    # X紹介投稿を x_posts.md に追記
    _append_x_promo_post(result, dry_run=dry_run)

    return result


def _extract_tags(text: str, category: str) -> list[str]:
    keyword_tags = {
        "AI": ["AI"], "副業": ["副業"], "FIRE": ["FIRE"],
        "楽天": ["楽天"], "シングル父": ["シングル父"], "継続": ["継続"],
    }
    tags = []
    for keyword, tag_list in keyword_tags.items():
        if keyword in text:
            tags.extend(tag_list[:1])
    cat_tags = {
        '副業実録': ['副業'], 'AI活用': ['AI'], 'FIRE設計': ['FIRE'],
        'シングル父の日常': ['シングル父'], '買ってよかった': ['楽天'],
    }
    for t in cat_tags.get(category, []):
        if t not in tags:
            tags.append(t)
    return list(dict.fromkeys(tags))[:5]


def _generate_thumbnail_for_post(result: dict) -> None:
    """生成した記事のサムネイルをgenerate_thumbnail.pyで自動生成する"""
    import subprocess
    thumb_script = SNS_DIR / "scripts" / "generate_thumbnail.py"
    if not thumb_script.exists():
        print(f"  ⚠ generate_thumbnail.py が見つかりません: {thumb_script}")
        return

    out_path = BLOG_DIR / "public" / "thumbnails" / f"{result['slug']}.png"
    cmd = [
        sys.executable, str(thumb_script),
        "--title",    result["title"],
        "--category", result["category"],
        "--output",   str(out_path),
    ]
    print(f"\n🖼 サムネイル生成中...")
    try:
        subprocess.run(cmd, check=True, timeout=60)
        print(f"   → {out_path.name}")
    except subprocess.TimeoutExpired:
        print(f"  ⚠ サムネイル生成がタイムアウトしました（スキップ）")
    except subprocess.CalledProcessError as e:
        print(f"  ⚠ サムネイル生成エラー: {e}")


def _append_x_promo_post(result: dict, dry_run: bool = False) -> None:
    """
    ブログ記事のX紹介投稿（URLなし本文 + reply_url行）を x_posts.md に追記する。
    X通常投稿（URLなし）→ リプライでブログURL の2ステップ導線。
    """
    title = result["title"]
    category = result["category"]
    blog_url = result["blog_url"]

    category_hook = {
        '副業実録': "副業の記録",
        'AI活用': "AIを使った話",
        'FIRE設計': "FIREへの設計",
        'シングル父の日常': "シングル父の日常",
        '買ってよかった': "実際に試してみた話",
    }.get(category, "記録")

    print(f"\n🐦 X紹介投稿を生成中...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": f"""以下のブログ記事を紹介するX（Twitter）投稿を1つ書いてください。

記事タイトル：{title}
カテゴリ：{category}（{category_hook}）

## 条件
- 80〜120文字（URLは含めない）
- 自然体・押し付けがましくない
- 「詳しくはリプライ欄へ」「続きはリプライ欄に」などのCTAで終わる
- LINE誘導・宣伝感・「稼げます」・URL直貼りは絶対に書かない
- ひろとのキャラ（40代シングル父・正直発信）を維持
- 共感・体験談ベースで書く

## 出力
投稿本文のみ（説明不要）"""
        }],
    )
    post_text = message.content[0].text.strip()

    if not X_POSTS_FILE.exists():
        print(f"  ⚠ x_posts.md が見つかりません: {X_POSTS_FILE}")
        return

    current_content = X_POSTS_FILE.read_text(encoding="utf-8")
    nos = re.findall(r'^## No\.(\d+)', current_content, re.MULTILINE)
    next_no = max(int(n) for n in nos) + 1 if nos else 1

    memo_marker = "## 投稿の使い方メモ"
    entry = f"\n## No.{next_no}【ブログ更新：{title[:20]}】\n{post_text}\nreply_url: {blog_url}\n\n---\n"

    if memo_marker in current_content:
        new_content = current_content.replace(memo_marker, entry + memo_marker)
    else:
        new_content = current_content.rstrip() + "\n" + entry

    if not dry_run:
        X_POSTS_FILE.write_text(new_content, encoding="utf-8")
        print(f"  ✅ X投稿を x_posts.md に追加 (No.{next_no})")
        print(f"     {post_text[:60]}...")
    else:
        print(f"  [DRY RUN] X投稿プレビュー (No.{next_no}):")
        print(f"  {post_text}")
        print(f"  reply_url: {blog_url}")


def generate_from_weekly_posts(dry_run: bool = False, with_note: bool = False) -> list[dict]:
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
            with_note=with_note,
        )
        results.append(result)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNS投稿からAstroブログ記事を自動生成")
    parser.add_argument("--theme", type=str, default="", help="記事テーマ")
    parser.add_argument("--category", type=str, default="", help="カテゴリ")
    parser.add_argument("--dry-run", action="store_true", help="生成のみ・ファイル保存なし")
    parser.add_argument("--weekly", action="store_true", help="週次バッチ（3記事同時生成）")
    parser.add_argument("--note", action="store_true", help="note下書きも同時出力")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY") or _load_env_key()
    if not api_key:
        print("❌ ANTHROPIC_API_KEYが設定されていません。")
        print("   threads_affiliate_system/.env に ANTHROPIC_API_KEY=sk-ant-... を追加してください。")
        sys.exit(1)

    if args.weekly:
        results = generate_from_weekly_posts(dry_run=args.dry_run, with_note=args.note)
        print(f"\n{'='*50}")
        print(f"✅ {len(results)}件の記事を生成しました。")
    else:
        result = generate_blog_post(
            theme=args.theme,
            category=args.category,
            sns_posts=_get_recent_sns_posts(),
            dry_run=args.dry_run,
            with_note=args.note,
        )
        print(f"\n✅ 完了: /blog/{result['slug']}/")
