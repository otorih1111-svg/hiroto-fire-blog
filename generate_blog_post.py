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
import subprocess
from pathlib import Path

# プロジェクトルート設定
BLOG_DIR = Path(__file__).parent
CONTENT_DIR = BLOG_DIR / "src" / "content" / "blog"
SNS_SYSTEM_DIR = Path(__file__).parent.parent / "threads_affiliate_system"
THUMBNAIL_SCRIPT = SNS_SYSTEM_DIR / "scripts" / "generate_thumbnail.py"
THUMBNAIL_DIR = BLOG_DIR / "public" / "images" / "thumbnails"
X_POSTS_FILE = Path(__file__).parent.parent / "x_posts.md"  # X投稿ストックファイル
BLOG_BASE_URL = "https://hiroto-fire.com"

ARTICLE_PRESETS = {
    "ハピタスの始め方と稼ぎ方【シングル父が月1万円稼いだ手順】": {
        "slug": "hapitas-hajimekata-kasegikata",
        "keyword": "ハピタス 始め方",
        "affiliate_urls": ["https://hapitas.jp/appinvite?i=25519472&route=pcText"],
        "invite_code": "QSEKKE",
        "outline": [
            "ハピタスとは（結論：自己アフィリで稼げるポイントサイト）",
            "登録手順（スクショ風に説明）",
            "稼ぎ方3つ（自己アフィリ・ショッピング・友達紹介）",
            "ひろとの実績（体験談）",
            "注意点",
            "まとめ＋招待リンク",
        ],
    },
    "自己アフィリエイトで稼ぐ方法【初心者が1発目に稼ぐべき理由】": {
        "slug": "jiko-affiliate-kasegikata",
        "keyword": "自己アフィリエイト 稼ぎ方",
        "affiliate_urls": ["https://px.a8.net/svt/ejp?a8mat=35AXS6+691W7U+0K+10FXXU"],
        "outline": [
            "自己アフィリとは（結論：自分でサービスに申し込んで報酬をもらう仕組み）",
            "なぜ初心者に最適か（理由3つ）",
            "稼ぎ方の手順",
            "おすすめASP一覧（A8・afb・もしも・バリューコマース）",
            "注意点（同一人物の複数申込はNG）",
            "まとめ",
        ],
    },
    "FP無料相談は怪しい？実際に使ってみた正直レビュー": {
        "slug": "fp-sodan-review",
        "keyword": "FP無料相談 怪しい",
        "affiliate_urls": ["https://px.a8.net/svt/ejp?a8mat=4B3MEP+DK7HLM+5MAS+5YJRM"],
        "outline": [
            "FP無料相談は怪しくない（結論から）",
            "無料の理由（成果報酬型の仕組みを説明）",
            "こんな人におすすめ（お金の悩みがある人・FIRE目指す人）",
            "ひろとが相談した体験談",
            "注意点（保険・投資を勧められることがある）",
            "まとめ＋申込リンク",
        ],
        "ymyl_note": "金融・保険の個別判断を断定せず、一般論と体験談に留めること。",
    },
    "副業初心者が最初の1万円を稼ぐロードマップ【順番が大事】": {
        "slug": "fukugyo-first-10000-roadmap",
        "keyword": "副業 初心者 稼ぎ方",
        "affiliate_urls": [
            "https://hapitas.jp/appinvite?i=25519472&route=pcText",
            "https://px.a8.net/svt/ejp?a8mat=35AXS6+691W7U+0K+10FXXU",
        ],
        "invite_code": "QSEKKE",
        "outline": [
            "結論：最初は自己アフィリ一択",
            "ステップ1：ハピタスに登録",
            "ステップ2：A8・afbで自己アフィリ案件を探す",
            "ステップ3：稼いだお金をブログ運営費に回す",
            "ステップ4：ブログでアフィリ収益を狙う",
            "まとめ",
        ],
    },
}


def _load_env_key() -> str:
    """親ディレクトリの.envからAPIキーを読む"""
    env_file = SNS_SYSTEM_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return ""


# Claude API
try:
    import anthropic
    ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY") or _load_env_key()
except ImportError:
    print("anthropicライブラリが必要: pip install anthropic")
    sys.exit(1)


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

ARTICLE_TYPES = {
    "solution": "解決系記事（SEO流入・悩み解決）",
    "record": "実録系記事（共感・信頼構築）",
    "fun": "楽しい・面白い記事（ファン化・シェア）",
}

MAX_DAILY_POSTS = 2

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


def _detect_article_type(theme: str, category: str) -> str:
    """テーマとカテゴリから記事タイプを推定する"""
    solution_keywords = [
        "方法", "やり方", "始め方", "選び方", "手順", "ガイド",
        "否認", "ハピタス", "自己アフィリエイト", "NISA", "計算",
        "最初の1週間", "やること", "ポイント", "完全ガイド",
    ]
    fun_keywords = ["失敗談", "困った", "全部実話", "聞かれて", "やってみた", "1週間の記録"]
    if any(keyword in theme for keyword in solution_keywords):
        return "solution"
    if any(keyword in theme for keyword in fun_keywords):
        return "fun"
    if category in ("AI活用", "FIRE設計") and any(keyword in theme for keyword in ("方法", "仕組み", "設計")):
        return "solution"
    return "record"


def check_daily_post_limit(max_posts: int = MAX_DAILY_POSTS) -> bool:
    """今日公開済みの記事数を確認し、上限に達していれば生成をスキップする。"""
    today = datetime.date.today().isoformat()
    existing_posts = sorted(CONTENT_DIR.glob(f"{today}-*.md"))
    if len(existing_posts) >= max_posts:
        print(f"⚠️ 本日の投稿上限（{max_posts}本）に達しています。生成をスキップします。")
        return False
    return True


def _article_type_instructions(article_type: str) -> str:
    """記事タイプごとの生成ルール"""
    if article_type == "solution":
        return """
## 記事タイプ：解決系記事（SEO流入メイン）
- 検索されるキーワードで書く
- 読者の具体的な悩みを解決する
- リード文は必ず「悩み → 結論 → ベネフィット」の順で書き、その後に `---` を入れる
- 構成は「悩み → 原因 → 解決手順 → よくある失敗 → 今日できる一歩」
- H2「なぜこの悩みが起きるか」を入れる
- H2「解決策・手順」を核心にして800〜1200文字で具体的に書く
- H2「よくある失敗・注意点」を入れる
- H2「まとめ・今日できる一歩」で行動を1つに絞る
- 記事末尾に必ず `## まとめ：...` を置き、要点3〜5個とCTA1文で締める
"""
    if article_type == "fun":
        return """
## 記事タイプ：楽しい・面白い記事（エンタメ系）
- 読んで楽しかった、面白かったと思わせる
- リード文は必ず「悩み → 結論 → ベネフィット」の順で書き、その後に `---` を入れる
- 短い段落と会話を多めにする
- 自虐・笑える失敗談・意外なオチを入れる
- 役に立つ話だけで終わらせず、ひろとの人間味を出す
- 締めは `## まとめ：...` で要点整理とCTAを入れる
"""
    return """
## 記事タイプ：実録系記事（共感・信頼構築メイン）
- ひろとの体験・失敗・途中経過を正直に書く
- リード文は必ず「悩み → 結論 → ベネフィット」の順で書き、その後に `---` を入れる
- 時系列、または「問題 → 気づき → 変化」の流れで書く
- 数字を入れる（○日目・○円・○人など）
- 恥ずかしい話や失敗も入れてリアリティを出す
- 記事末尾に必ず `## まとめ：...` を置き、要点整理とCTAで締める
"""


def generate_blog_post(
    theme: str = "",
    title: str = "",
    keyword: str = "",
    category: str = "",
    article_type: str = "",
    sns_posts: list[dict] | None = None,
    dry_run: bool = False,
    line_url: str = "https://line.me/R/ti/p/%40103khwdx",
    affiliate_urls: list[str] | None = None,
) -> dict:
    """
    Claude APIを呼んでブログ記事を生成する

    Returns:
        {"slug": str, "path": Path, "title": str, "content": str}
    """
    if not dry_run and not check_daily_post_limit():
        return {
            "skipped": True,
            "reason": "daily_post_limit_reached",
        }

    affiliate_urls = [url for url in (affiliate_urls or []) if url]
    preset = ARTICLE_PRESETS.get(title, {})
    if not keyword:
        keyword = preset.get("keyword", "")
    if not affiliate_urls:
        affiliate_urls = preset.get("affiliate_urls", [])

    effective_theme = title or theme

    # カテゴリ自動判定
    if not category:
        category = _detect_category(effective_theme) if effective_theme else '副業実録'
    if category not in CATEGORIES:
        category = '副業実録'
    if article_type not in ARTICLE_TYPES:
        article_type = _detect_article_type(effective_theme, category)

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
- スマホで読みやすいよう、改行は多めに入れる
- 1段落は原則1〜3文まで。長い段落を作らない
- 話題が切り替わる場所、感情が動く一文の後は改行する
- 「内容はしっかり・でもクスッと笑えてツッコミたくなる」温度感にする
- 記事全体で3〜5箇所まで自然なユーモアを入れる
- カッコ内オチを最低1箇所は入れる
- 自己ツッコミを1〜2箇所まで入れてよい
- コーヒー2杯分のような日常の比喩を使ってよい
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

## 生成後チェック
- 読者の悩みから始まっているか
- 解決策や学びが具体的か
- カッコ内オチが1箇所以上あるか
- 自己ツッコミやユーモアが入っても内容が薄くなっていないか

## 記事生成時の共通ルール
- 1記事1テーマに絞る
- 読者の悩み → 解決策 → 行動指示の流れを守る
- 自分の体験・数字・エピソードで補強する
- #PRが必要な案件紹介には必ず#PRを入れる
- 解決策を「頑張る」など抽象論で終わらせない

## 出力形式（Markdown）
frontmatterなしで出力してください。
本文の冒頭にタイトルのH1見出しを入れないこと。
タイトルはフロントマターに含めるため、本文内の「# タイトル」は不要です。
タイトルはコメント `<!-- title: ... -->` として冒頭に入れてください。
記事の長さ：2000〜4000文字
見出し：H2を3〜5個使用
最後の段落の後に、必要なら「---」で区切って補足導線を書いてください。"""

    article_type_instruction = _article_type_instructions(article_type)
    preset_outline = (
        "この記事の想定構成：\n- " + "\n- ".join(preset.get("outline", []))
        if preset.get("outline")
        else "必要なら自然な構成を提案してください。"
    )
    invite_code_note = f"招待コード：{preset.get('invite_code')}" if preset.get("invite_code") else ""
    ymyl_note = f"補足：{preset.get('ymyl_note')}" if preset.get("ymyl_note") else ""
    affiliate_url_note = (
        "使えるアフィリエイトURL：\n- " + "\n- ".join(affiliate_urls)
        if affiliate_urls
        else "アフィリエイトURLは指定なしです。"
    )

    user_prompt = f"""以下の条件でブログ記事を書いてください。

カテゴリ：{category}
記事タイプ：{ARTICLE_TYPES[article_type]}
{'タイトル：' + title if title else ''}
{'テーマ：' + theme if theme else ''}
{'主キーワード：' + keyword if keyword else ''}
{sns_context}

{article_type_instruction}

## 記事の狙い
- 読者の悩みから逆算して書く
- 1記事1キーワードで書く
- 結論を先に書く（PREP法）
- 検索意図に100%答える
- ひろとの体験談で補強する
- 文字数は2000〜4000文字

## 個別要件
{preset_outline}
{invite_code_note}
{ymyl_note}
{affiliate_url_note}

## 注意事項
- ひろとの「今の状況（収益ほぼゼロ・フォロワー約100人・3ヶ月継続中）」を活かす
- 読者は「副業したいけど時間がない・何から始めていいかわからない40代」
- 「誰でも簡単に稼げる」とは書かない
- 金融・保険は一般論と体験談ベースで、断定や個別助言をしない
- アフィリエイトリンクは自然な流れで紹介する
- アフィリエイトリンクを入れる場合は本文末尾に「## 登録リンク」または「## 申込リンク」を作り、各リンクに（PR）を明記する
- LINE登録、LINEボタン、LINEプレゼント、DM誘導などの文言は本文に入れない

## 出力形式
1行目：<!-- title: 記事タイトル -->
2行目：<!-- description: 1〜2文のサマリー -->
3行目以降：本文Markdown
本文の冒頭にタイトルのH1見出しを入れないこと。
本文はリード文またはH2見出しから始めること。

descriptionとして使える1〜2文のサマリーをコメント<!-- description: ... -->として冒頭に入れてください。"""

    print(f"\n🤖 Claude APIで記事生成中...")
    print(f"   カテゴリ：{category}")
    print(f"   記事タイプ：{ARTICLE_TYPES[article_type]}")
    if effective_theme:
        print(f"   テーマ：{effective_theme}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
    )

    raw_content = message.content[0].text

    # タイトル抽出。本文にH1を残さないため、コメント形式を優先する。
    title_comment_match = re.search(r'<!--\s*title:\s*(.+?)\s*-->', raw_content)
    title_h1_match = re.search(r'^#\s+(.+)$', raw_content, re.MULTILINE)
    if title_comment_match:
        title = title_comment_match.group(1).strip()
    elif title_h1_match:
        title = title_h1_match.group(1).strip()
    else:
        title = title.strip() or effective_theme.strip() or "無題の記事"

    # description抽出
    desc_match = re.search(r'<!--\s*description:\s*(.+?)\s*-->', raw_content)
    description = desc_match.group(1).strip() if desc_match else f"{category}に関するひろとの体験談。"

    # frontmatterなしの本文（title/descriptionコメントと先頭H1を除去）
    body = raw_content
    if title_comment_match:
        body = body.replace(title_comment_match.group(0), "").strip()
    if desc_match:
        body = body.replace(desc_match.group(0), "").strip()
    body = re.sub(r'^\s*#[^#].*\n+', '', body, count=1).strip()

    # スラッグ生成
    today = datetime.date.today().isoformat()
    slug_base = preset.get("slug", _slugify(title or effective_theme)[:40])
    slug = f"{today}-{slug_base}"

    # Markdownファイル生成（frontmatter + 本文）
    tags = _extract_tags(title + " " + body, category)
    title_escaped = title.replace('"', '\\"')
    description_escaped = description.replace('"', '\\"')
    frontmatter = f"""---
title: "{title_escaped}"
description: "{description_escaped}"
pubDate: {today}
category: {category}
ogImage: '/images/thumbnails/{slug}.png'
tags: {json.dumps(tags, ensure_ascii=False)}
draft: false
affiliate: {"true" if affiliate_urls else "false"}
---

"""
    body = _ensure_affiliate_links(
        body=body,
        title=title,
        affiliate_urls=affiliate_urls,
        preset=preset,
        line_url=line_url,
    )
    full_content = frontmatter + body

    result = {
        "slug": slug,
        "title": title,
        "description": description,
        "category": category,
        "article_type": article_type,
        "content": full_content,
        "path": CONTENT_DIR / f"{slug}.md",
    }

    if not dry_run:
        CONTENT_DIR.mkdir(parents=True, exist_ok=True)
        result["path"].write_text(full_content, encoding="utf-8")
        print(f"\n✅ 記事を保存しました：")
        print(f"   {result['path'].relative_to(BLOG_DIR)}")
        generate_thumbnail_for_post(slug, title, category)
    else:
        print(f"\n[DRY RUN] 記事生成完了（保存なし）")
        print(f"   タイトル：{title}")
        print(f"   スラッグ：{slug}")
        print(f"\n--- 本文プレビュー（先頭300文字）---")
        print(full_content[:300])
        print("...")

    # X紹介投稿を生成して x_posts.md に追記（X→ブログ→LINE導線）
    _append_x_promo_post(result, dry_run=dry_run)

    return result


def generate_thumbnail_for_post(slug: str, title: str, category: str) -> Path | None:
    """記事生成後にthreads_affiliate_system側のサムネイル生成を呼び出す。"""
    if not THUMBNAIL_SCRIPT.exists():
        print(f"サムネイル生成失敗：スクリプトが見つかりません: {THUMBNAIL_SCRIPT}")
        return None

    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    output_path = THUMBNAIL_DIR / f"{slug}.png"
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
        print(f"サムネイル生成成功：{output_path}")
        if result.stdout.strip():
            print(result.stdout.strip())
        return output_path

    print(f"サムネイル生成失敗：{result.stderr.strip() or result.stdout.strip()}")
    return None


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


def _ensure_affiliate_links(
    body: str,
    title: str,
    affiliate_urls: list[str],
    preset: dict,
    line_url: str,
) -> str:
    """指定がある記事では、最低限の登録リンク導線を末尾に補完する。"""
    if not affiliate_urls:
        return body

    lines: list[str] = []
    joined = "\n".join(affiliate_urls)

    if "ハピタス" in title:
        lines.append("- [ハピタスに登録する（PR）](https://hapitas.jp/appinvite?i=25519472&route=pcText)")
        if preset.get("invite_code"):
            lines.append(f"- 招待コード：`{preset['invite_code']}`")

    if "自己アフィリエイト" in title:
        lines.append("- [A8.netを見てみる（PR）](https://px.a8.net/svt/ejp?a8mat=35AXS6+691W7U+0K+10FXXU)")
        lines.append("- [afb公式サイトを見る](https://www.afi-b.com/)")
        lines.append("- [もしもアフィリエイト公式サイトを見る](https://af.moshimo.com/)")
        lines.append("- [バリューコマース公式サイトを見る](https://www.valuecommerce.ne.jp/)")

    if "FP無料相談" in title:
        lines.append("- [FP無料相談を見てみる（PR）](https://px.a8.net/svt/ejp?a8mat=4B3MEP+DK7HLM+5MAS+5YJRM)")

    if "最初の1万円" in title:
        lines.append("- [ハピタスに登録する（PR）](https://hapitas.jp/appinvite?i=25519472&route=pcText)")
        lines.append("- [A8.netを見てみる（PR）](https://px.a8.net/svt/ejp?a8mat=35AXS6+691W7U+0K+10FXXU)")
        if preset.get("invite_code"):
            lines.append(f"- 招待コード：`{preset['invite_code']}`")

    for url in affiliate_urls:
        if url not in joined:
            continue
        if url not in "\n".join(lines):
            lines.append(f"- [登録リンクを見る（PR）]({url})")

    if not lines:
        return body
    if "## 登録リンク" in body or "## 申込リンク" in body:
        return body

    section_title = "## 申込リンク" if "FP無料相談" in title else "## 登録リンク"
    suffix = f"\n\n---\n\n{section_title}\n\n" + "\n".join(lines)
    return body.rstrip() + suffix


def _append_x_promo_post(result: dict, dry_run: bool = False) -> None:
    """
    ブログ記事のX紹介投稿を生成して x_posts.md に追記する。
    X → ブログ → LINE の導線を作る。
    """
    title = result["title"]
    slug = result["slug"]
    category = result["category"]
    blog_url = f"{BLOG_BASE_URL}/blog/{slug}/"

    # カテゴリ別の文脈ワード
    category_hook = {
        '副業実録': "副業の記録",
        'AI活用': "AIを使った話",
        'FIRE設計': "FIREへの設計",
        'シングル父の日常': "シングル父の日常",
        '買ってよかった': "実際に試してみた話",
    }.get(category, "記録")

    # Claude APIで自然なX紹介投稿を生成（URLなし本文）
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
- 「詳しくはリプライへ」「続きはリプライ欄に」などのCTAで終わる
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

    # 現在の最大No.を調べる
    current_content = X_POSTS_FILE.read_text(encoding="utf-8")
    nos = re.findall(r'^## No\.(\d+)', current_content, re.MULTILINE)
    next_no = max(int(n) for n in nos) + 1 if nos else 1

    # 「投稿の使い方メモ」の直前に挿入するため、そのセクションを探す
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


def generate_from_weekly_posts(dry_run: bool = False) -> list[dict]:
    """
    週次バッチ：直近1週間のSNS投稿から複数記事を生成
    1日最大2記事までに制限して、テーマ重複を避ける
    """
    sns_posts = _get_recent_sns_posts(days=7)
    if not sns_posts:
        print("⚠️  直近SNS投稿が見つかりませんでした。デフォルトテーマで生成します。")

    remaining_slots = MAX_DAILY_POSTS if dry_run else max(0, MAX_DAILY_POSTS - len(sorted(CONTENT_DIR.glob(f"{datetime.date.today().isoformat()}-*.md"))))
    if remaining_slots <= 0:
        print(f"⚠️ 本日の投稿上限（{MAX_DAILY_POSTS}本）に達しているため、週次生成をスキップします。")
        return []

    default_themes = [
        ("副業を3ヶ月続けて気づいたこと", "副業実録"),
        ("AIを使い始めて変わった副業のやり方", "AI活用"),
        ("シングル父のFIRE設計：今の資産状況を正直に", "FIRE設計"),
    ][:remaining_slots]

    results = []
    for theme, category in default_themes:
        print(f"\n{'='*50}")
        result = generate_blog_post(
            theme=theme,
            category=category,
            sns_posts=sns_posts,
            dry_run=dry_run,
        )
        if result.get("skipped"):
            break
        results.append(result)

    return results


# ============================================================
# エントリポイント
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNS投稿からAstroブログ記事を自動生成")
    parser.add_argument("--title", type=str, default="", help="記事タイトル")
    parser.add_argument("--theme", type=str, default="", help="記事テーマ")
    parser.add_argument("--keyword", type=str, default="", help="主キーワード")
    parser.add_argument("--category", type=str, default="", help="カテゴリ（副業実録/AI活用/FIRE設計/シングル父の日常/買ってよかった）")
    parser.add_argument("--type", choices=ARTICLE_TYPES.keys(), default="", help="記事タイプ（solution/record/fun）")
    parser.add_argument("--affiliate-url", action="append", default=[], help="記事内で使うアフィリエイトURL。複数指定可")
    parser.add_argument("--dry-run", action="store_true", help="生成のみ・ファイル保存なし")
    parser.add_argument("--weekly", action="store_true", help="週次バッチ（1日最大2記事）")
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
            title=args.title,
            keyword=args.keyword,
            category=args.category,
            article_type=args.type,
            sns_posts=[post_data],
            dry_run=args.dry_run,
            affiliate_urls=args.affiliate_url,
        )
    else:
        result = generate_blog_post(
            theme=args.theme,
            title=args.title,
            keyword=args.keyword,
            category=args.category,
            article_type=args.type,
            sns_posts=_get_recent_sns_posts(),
            dry_run=args.dry_run,
            affiliate_urls=args.affiliate_url,
        )
        if result.get("skipped"):
            print("\n⏭️ 記事生成をスキップしました。")
        else:
            print(f"\n✅ 完了: /blog/{result['slug']}/")
