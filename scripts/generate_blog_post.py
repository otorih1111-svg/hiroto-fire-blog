"""
scripts/generate_blog_post.py
SNS投稿（Threads・X）からAstroブログ記事を自動生成するスクリプト

【使い方】
  python3 scripts/generate_blog_post.py                    # 直近SNS投稿から自動生成
  python3 scripts/generate_blog_post.py --theme "AI副業の始め方"  # テーマ指定
  python3 scripts/generate_blog_post.py --category AI活用   # カテゴリ指定
  python3 scripts/generate_blog_post.py --dry-run           # 生成のみ（ファイル保存なし）
  python3 scripts/generate_blog_post.py --weekly            # 週次バッチ（1日最大2記事）

【出力】
  src/content/blog/YYYY-MM-DD-slug.md

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


CATEGORIES = ['節約・家計', '投資・FIRE', '副業・AI']
MAX_DAILY_POSTS = 2

CATEGORY_KEYWORDS = {
    '節約・家計': ['節約', '固定費', '家計', '通信費', '格安SIM', 'ポイ活', 'ハピタス', '保険', '支出'],
    '投資・FIRE': ['FIRE', '投資', 'NISA', '資産', '老後', '積立', '証券', 'FP', 'iDeCo', 'オルカン'],
    '副業・AI':   ['副業', 'AI', 'Claude', 'ChatGPT', '収益', 'アフィリ', 'ブログ', '自動化', '稼ぐ'],
}

# 生成禁止テーマクラスター（カニバリゼーション防止）
BLOCKED_THEME_CLUSTERS = [
    "AIを使い始めて副業が変わった",
    "AIを使って副業のやり方が変わった",
    "副業3ヶ月で気づいたのは稼ぎ方じゃなかった",
    "副業3ヶ月で気づいた自分のクセ",
    "副業3ヶ月 収益ゼロ 続ける理由",
    "AIに相談するようになった",
    "AIに愚痴を話した",
    "AIに今日何すればいいか聞いた",
]


def _detect_category(theme: str) -> str:
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in theme for kw in keywords):
            return cat
    return '副業・AI'


def _get_recent_blog_titles(n: int = 10) -> list[dict]:
    """直近n件のブログ記事のタイトル・カテゴリを返す"""
    articles = []
    for md in sorted(CONTENT_DIR.glob("*.md"), reverse=True)[:n]:
        text = md.read_text(encoding="utf-8")
        title_m    = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', text, re.MULTILINE)
        category_m = re.search(r'^category:\s*(.+?)\s*$',          text, re.MULTILINE)
        title    = title_m.group(1).strip('"\'')    if title_m    else ""
        category = category_m.group(1).strip('"\'') if category_m else ""
        if title:
            articles.append({"title": title, "category": category})
    return articles


def _pick_next_category(recent: list[dict]) -> str:
    """直近記事のカテゴリ偏りを見て、次に使うべきカテゴリを返す"""
    if not recent:
        return "副業・AI"
    # 直近5件のカテゴリカウント
    from collections import Counter
    counts = Counter(a["category"] for a in recent[:5])
    # 一番使われていないカテゴリを優先
    for cat in CATEGORIES:
        if counts.get(cat, 0) == 0:
            return cat
    # 全部使われていれば最少のものを返す
    return min(CATEGORIES, key=lambda c: counts.get(c, 0))


def check_daily_post_limit(max_posts: int = MAX_DAILY_POSTS) -> bool:
    """今日公開済みの記事数を確認し、上限に達していれば生成をスキップする。"""
    today = datetime.date.today().isoformat()
    existing_posts = sorted(CONTENT_DIR.glob(f"{today}-*.md"))
    if len(existing_posts) >= max_posts:
        print(f"⚠️ 本日の投稿上限（{max_posts}本）に達しています。生成をスキップします。")
        return False
    return True


def get_remaining_post_slots(max_posts: int = MAX_DAILY_POSTS) -> int:
    """当日あと何本公開できるかを返す。"""
    today = datetime.date.today().isoformat()
    existing_posts = sorted(CONTENT_DIR.glob(f"{today}-*.md"))
    return max(0, max_posts - len(existing_posts))


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
    if not dry_run and not check_daily_post_limit():
        return {
            "skipped": True,
            "reason": "daily_post_limit_reached",
        }

    # 直近記事を取得して被り防止に使う（30件に拡大）
    recent_articles = _get_recent_blog_titles(30)

    if not category:
        if theme:
            category = _detect_category(theme)
        else:
            # カテゴリ偏りを自動調整
            category = _pick_next_category(recent_articles)
    if category not in CATEGORIES:
        category = '副業・AI'

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
- 「内容はしっかり・でもクスッと笑えてツッコミたくなる」温度感にする
- 記事全体で3〜5箇所まで自然なユーモアを入れる
- 自己ツッコミを1〜2箇所まで入れてよい
- コーヒー2杯分のような日常の比喩を使ってよい
- カッコ書きのオチは使わない
- 笑いのための作り話は禁止
- 「非常に重要なポイントです！」「ぜひ活用してみてください！」のような煽りは禁止
- ！の多用は禁止
- 「〜すべきです」「〜してください」の連発は禁止

## 記事構成の必須ルール
- リード文は必ず以下の順で書く
  1. 悩み：読者が感じている状況を1〜2文
  2. 結論：この記事で何がわかるかを1文
  3. ベネフィット：読むとどうなるかを1文
  4. その後に必ず `---` を1本入れる
- 本文はH2/H3見出しを使う
- 各セクションはPREP法（結論→理由→具体例→結論）を意識する
- 記事末尾には必ず `## まとめ：...` を置く
- まとめの中には要点の箇条書き3〜5点と、最後に1文のCTAを入れる
- 記事タイトルと同じ文言のH2は作らない
- LINE誘導、LINE登録CTA、外部チャット誘導は本文に入れない
- アドセンス審査中なので、LINEに触れる文脈が必要でもCTA化しない

## YMYLジャンルの特別ルール
以下のジャンルはGoogleがE-E-A-T（経験・専門性・権威性・信頼性）を厳しく評価する。
ひろとは専門家・資格保有者ではないため、必ず「体験談ベース」で書くこと。

YMYLに該当するジャンル：
- 節約・家計（楽天経済圏・固定費・家計管理）
- 投資・FIRE（NISA・証券口座・資産形成）
- 副業収益（アフィリエイト・ASP・収益化）
- 保険・FP相談

YMYLジャンルの記事では：
1. **タイトルに体験を示す言葉を入れる**：「体験談」「実録」「やってみた」「気づいた」「正直に書く」
2. **断定を避ける**：「〜すべき」「〜が正解」「〜で稼げます」は禁止。「〜だと思います」「ぼくの場合は」に変える
3. **自分の数字のみ使う**：「一般的に〜万円」より「ぼくの場合は先月〜円でした」
4. **免責表記を入れる**：記事末尾のまとめ前後に以下を入れる
   「※この記事はぼく個人の体験談です。投資・保険・副業の判断は自己責任でお願いします。」
5. **専門家への誘導**：必要に応じて「詳しくはFP等の専門家に相談してください」を入れる

## 生成後チェック
- 読者の悩みから始まっているか
- 解決策や学びが具体的か
- カッコ書きのオチに逃げていないか
- 自己ツッコミやユーモアが入っても内容が薄くなっていないか
- YMYLジャンルなら免責表記が入っているか・断定表現を避けているか

## 出力形式
frontmatterなしで、H1タイトルから始めてください。
記事の長さ：1500〜2500文字"""

    # 直近記事リストを文字列化（カニバリゼーション防止）
    recent_titles_str = ""
    if recent_articles:
        recent_titles_str = "\n\n## ⚠️ 公開済み記事（テーマ・切り口が被らないようにしてください）\n"
        for a in recent_articles:
            recent_titles_str += f"- [{a['category']}] {a['title']}\n"

    # 生成禁止クラスターを文字列化
    blocked_str = "\n\n## 🚫 絶対に使わないテーマ（カニバリゼーション防止）\n"
    blocked_str += "以下のテーマ・切り口は記事が既に多数あるため、類似内容は絶対に生成しないこと：\n"
    for cluster in BLOCKED_THEME_CLUSTERS:
        blocked_str += f"- {cluster}\n"
    blocked_str += "- 「AIを使い始めて〇〇が変わった」系全般（同テーマが5本以上ある）\n"
    blocked_str += "- 「副業3ヶ月で気づいた〇〇」系全般（同テーマが6本以上ある）\n"
    blocked_str += "上記に近いテーマが浮かんだ場合は、全く別の切り口・テーマを選ぶこと。\n"

    user_prompt = f"""以下の条件でブログ記事を書いてください。

カテゴリ：{category}
{'テーマ：' + theme if theme else 'テーマは自由に設定してください。ひろとの最近の体験を元に。'}
{sns_context}
{recent_titles_str}
{blocked_str}

## 注意事項
- PR・アフィリエイト商品は含めない（純粋な体験談・ノウハウ記事）
- ひろとの現状：収益ほぼゼロ・フォロワー約100人・3ヶ月継続中
- 読者像：副業したいけど時間がない・何から始めていいかわからない40代
- 「稼げます」「簡単です」は絶対に書かない
- 失敗・試行錯誤・正直さがひろとの強み。隠さず書く
- 直近の公開済み記事と同じテーマ・タイトルは絶対に使わない（特に「副業3ヶ月・収益ほぼゼロ」は3記事連続で使用済み）
- LINE登録、LINEボタン、LINEプレゼント、DM誘導などの文言は本文に入れない
- リード文とまとめは必須。省略しない

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

    # H1タイトル行をbodyから除去（frontmatterにtitleが既にあるため不要）
    body = re.sub(r'^#\s+.+\n?', '', body, count=1, flags=re.MULTILINE).strip()

    body = body.rstrip()
    if "ADSENSE_REVIEW_START" not in body:
        body += "\n\n<!-- ADSENSE_REVIEW_START: LINE CTA hidden during AdSense review. ADSENSE_REVIEW_END -->"

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
draft: true
affiliate: false
ogImage: '/images/thumbnails/{slug}.png'
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

        # 記事内SVG画像を生成して本文に挿入
        result["body"] = body
        new_body = _generate_article_svg(result, client)
        if new_body:
            body = new_body
            full_content = frontmatter + body
            result["content"] = full_content

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
        '節約・家計': ['節約', '家計'], '投資・FIRE': ['FIRE', '投資'], '副業・AI': ['副業', 'AI'],
    }
    for t in cat_tags.get(category, []):
        if t not in tags:
            tags.append(t)
    return list(dict.fromkeys(tags))[:5]


def _generate_article_svg(result: dict, client) -> str | None:
    """
    記事内容を元にSVG図解を1枚生成して本文に挿入する。
    戻り値：挿入後のbody文字列（失敗時はNone）
    """
    slug = result["slug"]
    title = result["title"]
    category = result["category"]
    body = result.get("body", "")

    svg_dir = BLOG_DIR / "public" / "images" / "articles" / slug
    svg_path = svg_dir / "summary.svg"
    svg_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🖼 記事内SVG画像を生成中...")

    prompt = f"""以下のブログ記事を読んで、読者の理解を助けるSVG図解を1枚作成してください。

記事タイトル：{title}
カテゴリ：{category}

本文（先頭2000文字）：
{body[:2000]}

## 図解の種類（記事内容に合わせて1つ選ぶ）
- Before/After比較図（変化・効果を示す記事に）
- ステップ・フロー図（手順・流れを示す記事に）
- 比較表図（2〜3つのものを比べる記事に）
- ポイント整理図（3〜4つの要点をまとめる記事に）

## SVG仕様
- width="1200" height="460" viewBox="0 0 1200 460"
- 背景色：#F7FBF8（薄いグリーン）
- メインカラー：#1F4D32（深いグリーン）
- アクセント：#7CB089
- フォント：'Hiragino Sans','Noto Sans JP',sans-serif
- 日本語テキストを使用
- シンプルで読みやすいデザイン

SVGコードのみを返してください（説明不要、<svg>タグから始める）。"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )
        svg_raw = response.content[0].text.strip()

        svg_match = re.search(r'(<svg[\s\S]*?</svg>)', svg_raw)
        if not svg_match:
            print("  ⚠ SVGの抽出に失敗しました")
            return None

        svg_content = svg_match.group(1)
        svg_path.write_text(svg_content, encoding="utf-8")
        print(f"  ✅ SVG保存: {svg_path.name}")

        # 本文の中盤に挿入（2番目のH2の前）
        img_tag = f"\n\n![{title}の図解](/images/articles/{slug}/summary.svg)\n"
        h2_matches = list(re.finditer(r'^## .+$', body, re.MULTILINE))
        if len(h2_matches) >= 2:
            insert_pos = h2_matches[1].start()
            body = body[:insert_pos] + img_tag + body[insert_pos:]
        elif h2_matches:
            insert_pos = h2_matches[0].end()
            body = body[:insert_pos] + img_tag + body[insert_pos:]
        else:
            body = body + img_tag

        return body

    except Exception as e:
        print(f"  ⚠ SVG生成エラー: {e}")
        return None


def _generate_thumbnail_for_post(result: dict) -> None:
    """生成した記事のサムネイルをgenerate_thumbnail.pyで自動生成する"""
    import subprocess
    thumb_script = SNS_DIR / "scripts" / "generate_thumbnail.py"
    if not thumb_script.exists():
        print(f"  ⚠ generate_thumbnail.py が見つかりません: {thumb_script}")
        return

    out_path = BLOG_DIR / "public" / "images" / "thumbnails" / f"{result['slug']}.png"
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
        '節約・家計': "節約・家計の話",
        '投資・FIRE': "投資・FIREへの道",
        '副業・AI': "副業・AIの記録",
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

    remaining_slots = MAX_DAILY_POSTS if dry_run else get_remaining_post_slots()
    if remaining_slots <= 0:
        print(f"⚠️ 本日の投稿上限（{MAX_DAILY_POSTS}本）に達しているため、週次生成をスキップします。")
        return []

    default_themes = [
        ("副業を3ヶ月続けて気づいたこと", "副業・AI"),
        ("AIを使い始めて変わった副業のやり方", "副業・AI"),
        ("シングル父のFIRE設計：今の資産状況を正直に", "投資・FIRE"),
    ][:remaining_slots]

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
    parser.add_argument("--weekly", action="store_true", help="週次バッチ（1日最大2記事）")
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
