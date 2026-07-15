#!/usr/bin/env python3
"""
KW提案ファイル 毎日自動生成スクリプト
====================================
1. Google Ads API (KeywordPlanIdeaService) でキーワード候補・月間検索Vol・競合性を取得
2. hiroto-fire-blog/src/content/blog の既存記事と重複しないものに絞る
3. Claude APIでタイトル案・内部リンク候補・一言コメントを生成
4. ~/Desktop/kw-proposals/YYYY-MM-DD.md に出力

実行: python3 scripts/generate_kw_proposals.py
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BLOG_DIR = SCRIPT_DIR.parent
CONTENT_DIR = BLOG_DIR / "src" / "content" / "blog"
SNS_DIR = BLOG_DIR.parent / "threads_affiliate_system"
OUTPUT_DIR = Path.home() / "Desktop" / "kw-proposals"
LOG_DIR = BLOG_DIR / "logs"

# ============================================================
# シードキーワード（4つの軸）
# ============================================================
SEED_KEYWORDS = [
    # 楽天経済圏・楽天サービス系
    "楽天カード", "楽天モバイル", "楽天証券", "楽天ふるさと納税", "楽天銀行", "楽天SPU",
    # シングルファーザー×節約・投資・副業
    "シングルファーザー 節約", "シングルファーザー 投資", "シングルファーザー 副業", "離婚 お金",
    # NISA・資産運用・家計管理
    "新NISA", "つみたてNISA", "家計管理 アプリ", "固定費見直し", "iDeCo",
    # ブログ・アフィリエイト・AI副業
    "ブログ 始め方", "アフィリエイト 初心者", "AI副業", "Claude Code 使い方", "ASP 比較",
]

MIN_MONTHLY_SEARCHES = 100
ALLOWED_COMPETITION = {"LOW", "MEDIUM"}


# ============================================================
# .env 読み込み
# ============================================================
def load_env():
    env = dict(os.environ)
    for env_file in (BLOG_DIR / ".env", SNS_DIR / ".env"):
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"\''))
    return env


# ============================================================
# 既存記事スキャン（重複チェック・内部リンク候補用）
# ============================================================
def load_existing_articles():
    articles = []
    for f in CONTENT_DIR.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        title_m = re.search(r'^title:\s*"?(.+?)"?\s*$', text, re.MULTILINE)
        desc_m = re.search(r'^description:\s*"?(.+?)"?\s*$', text, re.MULTILINE)
        tags_m = re.search(r'^tags:\s*\[(.*?)\]', text, re.MULTILINE)
        cat_m = re.search(r'^category:\s*"?(.+?)"?\s*$', text, re.MULTILINE)
        draft_m = re.search(r'^draft:\s*(true|false)', text, re.MULTILINE)

        if draft_m and draft_m.group(1) == "true":
            continue

        title = title_m.group(1).strip() if title_m else ""
        desc = desc_m.group(1).strip() if desc_m else ""
        tags = []
        if tags_m:
            tags = [t.strip().strip('"\'') for t in tags_m.group(1).split(",") if t.strip()]
        category = cat_m.group(1).strip() if cat_m else ""

        articles.append({
            "slug": f.stem,
            "title": title,
            "description": desc,
            "tags": tags,
            "category": category,
        })
    return articles


def is_duplicate(keyword: str, articles: list) -> bool:
    """既存記事のタイトル・タグとキーワードのトークンが大きく重なるなら重複とみなす"""
    kw_tokens = set(re.findall(r"[ぁ-んァ-ヶ一-龠a-zA-Z0-9]+", keyword.lower()))
    if not kw_tokens:
        return False
    for a in articles:
        hay_tokens = set(re.findall(r"[ぁ-んァ-ヶ一-龠a-zA-Z0-9]+", (a["title"] + " " + " ".join(a["tags"])).lower()))
        if not hay_tokens:
            continue
        overlap = kw_tokens & hay_tokens
        if len(overlap) >= max(1, len(kw_tokens) - 1) and len(kw_tokens) <= 3:
            return True
        if hay_tokens and len(overlap) / len(kw_tokens) >= 0.8:
            return True
    return False


# ============================================================
# Google Ads API でキーワード候補取得
# ============================================================
def fetch_keyword_ideas(env):
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException

    required = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
    ]
    missing = [k for k in required if not env.get(k)]
    if missing:
        raise RuntimeError(f"Google Ads API認証情報が不足しています: {', '.join(missing)}")

    config = {
        "developer_token": env["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": env["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": env["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": env["GOOGLE_ADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    if env.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID"):
        config["login_customer_id"] = env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]

    client = GoogleAdsClient.load_from_dict(config)
    customer_id = env["GOOGLE_ADS_CUSTOMER_ID"].replace("-", "")

    idea_service = client.get_service("KeywordPlanIdeaService")
    keyword_plan_network = (
        client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    )

    request = client.get_type("GenerateKeywordIdeasRequest")
    request.customer_id = customer_id
    request.language = "languageConstants/1005"  # 日本語
    request.geo_target_constants.append("geoTargetConstants/2392")  # 日本
    request.include_adult_keywords = False
    request.keyword_plan_network = keyword_plan_network
    request.keyword_seed.keywords.extend(SEED_KEYWORDS)

    try:
        response = idea_service.generate_keyword_ideas(request=request)
    except GoogleAdsException as ex:
        raise RuntimeError(f"Google Ads APIエラー: {ex}") from ex

    competition_names = {
        0: "UNSPECIFIED", 1: "UNKNOWN", 2: "LOW", 3: "MEDIUM", 4: "HIGH",
    }

    ideas = []
    for result in response:
        metrics = result.keyword_idea_metrics
        avg_searches = metrics.avg_monthly_searches or 0
        competition = competition_names.get(int(metrics.competition), "UNKNOWN")
        ideas.append({
            "keyword": result.text,
            "avg_monthly_searches": avg_searches,
            "competition": competition,
        })
    return ideas


# ============================================================
# Claude APIでタイトル案・内部リンク候補・コメント生成
# ============================================================
def generate_proposals_with_claude(env, candidates, articles):
    import anthropic

    api_key = env.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEYが設定されていません")

    client = anthropic.Anthropic(api_key=api_key)

    article_list = "\n".join(
        f"- [{a['category']}] {a['title']} (slug: {a['slug']}, tags: {', '.join(a['tags'])})"
        for a in articles
    )
    candidate_list = "\n".join(
        f"- {c['keyword']} (月間Vol: {c['avg_monthly_searches']}, 競合: {c['competition']})"
        for c in candidates
    )

    prompt = f"""あなたはブログ「ひろとの家計改善とFIREブログ」(hiroto-fire.com)のSEO担当です。
40代シングルファーザーが節約・投資・副業の体験を発信するブログで、今後の新規記事のキーワード候補を選定します。

# 既存記事一覧
{article_list}

# キーワード候補（月間検索Vol・競合性はGoogle広告のデータ）
{candidate_list}

# 依頼
上記の候補から、既存記事と内容が被らず、ブログのテーマ（節約・家計／投資・FIRE／副業・AI）に合う候補を3つ選んでください。
できれば4つのテーマ軸（楽天経済圏／シングルファーザー×節約・投資・副業／NISA・資産運用・家計管理／ブログ・アフィリエイト・AI副業）からバラけるように選んでください。

各候補について以下を出力してください。
- keyword: 候補のキーワード（候補一覧からそのまま使う）
- avg_monthly_searches: 候補一覧の月間Volをそのまま転記
- competition: 候補一覧の競合性をそのまま転記
- title: 記事タイトル案（32文字以内・数字や対象読者を意識・「シングルファーザー」は使う場合タイトル内1回まで）
- internal_link: 既存記事一覧から最も関連する記事のタイトルとslugを1つ（"なし"でも可）
- comment: ひろとへの一言コメント（なぜこの候補がいいか、40字程度）

JSON配列のみを出力してください。説明文は不要です。
[
  {{"keyword": "...", "avg_monthly_searches": 0, "competition": "...", "title": "...", "internal_link": "...", "comment": "..."}},
  ...
]
"""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2000,
        thinking={"type": "disabled"},  # Sonnet 5は思考がデフォルトON。JSON出力がmax_tokensで切れないよう従来通り無効化
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()

    # JSON部分のみ抽出
    json_match = re.search(r"\[.*\]", text, re.DOTALL)
    if not json_match:
        raise RuntimeError(f"Claudeの出力からJSONを抽出できませんでした: {text[:200]}")

    return json.loads(json_match.group(0))


# ============================================================
# 出力ファイル作成
# ============================================================
def write_output(proposals):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()
    out_file = OUTPUT_DIR / f"{today.strftime('%Y-%m-%d')}.md"

    lines = [f"# KW提案 {today.year}年{today.month}月{today.day}日", ""]
    for i, p in enumerate(proposals[:3], start=1):
        lines += [
            f"## 候補{i}",
            f"KW：{p.get('keyword', '')}",
            f"月間Vol：{p.get('avg_monthly_searches', '')}",
            f"競合：{p.get('competition', '')}",
            f"タイトル案：{p.get('title', '')}",
            f"既存記事との内部リンク候補：{p.get('internal_link', '')}",
            f"一言コメント：{p.get('comment', '')}",
            "",
        ]

    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


# ============================================================
# メイン
# ============================================================
def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = load_env()

    articles = load_existing_articles()
    ideas = fetch_keyword_ideas(env)

    filtered = [
        idea for idea in ideas
        if idea["avg_monthly_searches"] >= MIN_MONTHLY_SEARCHES
        and idea["competition"] in ALLOWED_COMPETITION
        and not is_duplicate(idea["keyword"], articles)
    ]

    if not filtered:
        raise RuntimeError("条件に合うキーワード候補が見つかりませんでした")

    # Volが高い順に上位20件をClaudeに渡す
    filtered.sort(key=lambda x: x["avg_monthly_searches"], reverse=True)
    top_candidates = filtered[:20]

    proposals = generate_proposals_with_claude(env, top_candidates, articles)
    out_file = write_output(proposals)
    print(f"出力完了: {out_file}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "kw_proposals_error.log", "a", encoding="utf-8") as f:
            f.write(f"[{date.today().isoformat()}] {e}\n")
        sys.exit(1)
