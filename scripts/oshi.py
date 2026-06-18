#!/usr/bin/env python3
"""
Oshi（オシ）- 惜しい記事を押し上げる自動改善スクリプト
────────────────────────────────────────────────────────
1. GSCデータを取得
2. 「順位4〜15位・0クリック・表示5回以上」の記事を自動抽出
3. Claude APIにタイトル・description・リード文の改善案を依頼
4. 改善案をターミナルに表示 → 人が番号を選んで確認
5. 自動でファイル修正 → git push

使い方:
  python3 scripts/oshi.py           # 通常実行（確認あり）
  python3 scripts/oshi.py --dry-run # 改善案だけ出してpushしない
  python3 scripts/oshi.py --limit 5 # 対象記事数を変える
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
BLOG_DIR = ROOT / "src" / "content" / "blog"
KEY_FILE = ROOT / "google-credentials.json"
SITE = "https://hiroto-fire.com/"
GA4_PROPERTY = "537739366"
LOG_FILE = ROOT / "logs" / "auto_improve_log.json"


# ── 1. GSCデータ取得 ──────────────────────────────────────────────────────────

def fetch_gsc_candidates(days: int = 28) -> list[dict]:
    """順位4〜15位・0クリック・表示5回以上の記事を返す"""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        str(KEY_FILE),
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    gsc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

    end = date.today()
    start = end - timedelta(days=days)

    resp = gsc.searchanalytics().query(
        siteUrl=SITE,
        body={
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["page"],
            "rowLimit": 100,
            "dimensionFilterGroups": [{
                "filters": [{
                    "dimension": "page",
                    "operator": "contains",
                    "expression": "/blog/",
                }]
            }],
        },
    ).execute()

    candidates = []
    for r in resp.get("rows", []):
        clicks = r["clicks"]
        impressions = r["impressions"]
        position = r["position"]
        url = r["keys"][0]
        slug = url.rstrip("/").split("/blog/")[-1]

        if clicks == 0 and impressions >= 5 and 3.0 <= position <= 20.0:
            candidates.append({
                "slug": slug,
                "url": url,
                "clicks": clicks,
                "impressions": impressions,
                "position": round(position, 1),
                "ctr": 0.0,
            })

    # 順位が良い順（低い数値が上位）
    candidates.sort(key=lambda x: x["position"])
    return candidates


# ── 2. 記事ファイル読み込み ────────────────────────────────────────────────────

def read_article(slug: str) -> dict | None:
    """slugからfrontmatterと本文を返す"""
    path = BLOG_DIR / f"{slug}.md"
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
    if not fm_match:
        return None

    fm_raw = fm_match.group(1)
    body = fm_match.group(2)

    title = re.search(r'^title:\s*"?(.*?)"?\s*$', fm_raw, re.MULTILINE)
    desc = re.search(r'^description:\s*"?(.*?)"?\s*$', fm_raw, re.MULTILINE)

    return {
        "slug": slug,
        "path": path,
        "title": title.group(1).strip().strip('"') if title else "",
        "description": desc.group(1).strip().strip('"') if desc else "",
        "body_preview": body[:800],  # リード文あたりだけ渡す
        "content": content,
    }


# ── 3. Claude APIで改善案生成 ──────────────────────────────────────────────────

def generate_improvements(article: dict, gsc: dict) -> dict:
    """Claude APIにタイトル・description・リード文の改善案を依頼"""
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""あなたはSEOとブログ改善の専門家です。以下の記事データを見て改善案を出してください。

## 記事情報
- slug: {article['slug']}
- 現在のタイトル: {article['title']}
- 現在のdescription: {article['description']}

## GSCデータ（過去28日）
- 表示回数: {gsc['impressions']}回
- 平均順位: {gsc['position']}位
- クリック数: {gsc['clicks']}（0クリック）

## 記事冒頭（800文字）
{article['body_preview']}

## ブログのペルソナ
- 40代シングルファーザーが家計・投資・副業でFIREを目指すブログ
- 読者: 40代会社員・家計や投資に不安がある初心者
- 文体: 「ぼく」「相棒（息子）」・クスッとする自己ツッコミあり・体験談ベース

## 出力形式（必ずJSON形式で）
{{
  "title_candidates": ["タイトル案1（27文字以内）", "タイトル案2", "タイトル案3"],
  "description_candidates": ["description案1（80〜120文字）", "description案2"],
  "lead_rewrite": "改善後のリード文（200〜400文字）",
  "why": "なぜこの改善でCTRが上がるか（1〜2文）"
}}

注意:
- タイトルは27文字以内厳守
- descriptionは80〜120文字
- ひろとの体験談・感情は残す
- 「意味ある？」「怖い人へ」など検索語に近い言葉を使う
- JSON以外の文字は出力しない"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # JSONブロックがある場合は抽出
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        raw = json_match.group(0)

    return json.loads(raw)


# ── 4. ファイル修正 ────────────────────────────────────────────────────────────

def apply_improvement(article: dict, chosen_title: str, chosen_desc: str, lead_rewrite: str) -> bool:
    """タイトル・description・リード文をファイルに書き込む"""
    content = article["content"]

    # タイトル置換
    content = re.sub(
        r'^title:.*$',
        f'title: "{chosen_title}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    # description置換
    content = re.sub(
        r'^description:.*$',
        f'description: "{chosen_desc}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )

    # リード文置換（---直後〜最初のH2の前）
    fm_end = content.index("---\n", 4) + 4  # 2つ目の---の後
    h2_pos = content.find("\n## ", fm_end)
    if h2_pos > fm_end:
        old_lead = content[fm_end:h2_pos]
        content = content[:fm_end] + "\n" + lead_rewrite.strip() + "\n\n" + content[h2_pos + 1:]

    article["path"].write_text(content, encoding="utf-8")
    return True


# ── 5. Git push ────────────────────────────────────────────────────────────────

def git_push(slug: str) -> bool:
    try:
        subprocess.run(["git", "add", f"src/content/blog/{slug}.md"], cwd=ROOT, check=True)
        msg = f"SEO自動改善: {slug} のタイトル・description・リード文を修正"
        subprocess.run(["git", "commit", "-m", msg], cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] git操作失敗: {e}")
        return False


# ── 6. ログ記録 ────────────────────────────────────────────────────────────────

def save_log(entries: list[dict]):
    LOG_FILE.parent.mkdir(exist_ok=True)
    existing = []
    if LOG_FILE.exists():
        existing = json.loads(LOG_FILE.read_text())
    existing.extend(entries)
    LOG_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2))


# ── メイン ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="改善案だけ出してpushしない")
    parser.add_argument("--days", type=int, default=28, help="GSCデータの集計日数")
    parser.add_argument("--limit", type=int, default=3, help="処理する記事の上限")
    args = parser.parse_args()

    print("=" * 60)
    print("Oshi（オシ）- 惜しい記事を押し上げる")
    print("=" * 60)

    # Step 1: GSC候補取得
    print("\n[1] GSCデータを取得中...")
    candidates = fetch_gsc_candidates(days=args.days)
    if not candidates:
        print("改善候補の記事が見つかりませんでした。")
        return

    print(f"  → 改善候補: {len(candidates)}記事")
    for c in candidates:
        print(f"     {c['position']:>5.1f}位 / {c['impressions']:>3}表示 / {c['slug']}")

    log_entries = []

    for i, candidate in enumerate(candidates[:args.limit]):
        slug = candidate["slug"]
        print(f"\n{'─'*60}")
        print(f"[{i+1}/{min(len(candidates), args.limit)}] {slug}")
        print(f"  順位:{candidate['position']}位 / 表示:{candidate['impressions']}回 / クリック:0")

        # Step 2: 記事読み込み
        article = read_article(slug)
        if not article:
            print(f"  ファイルが見つかりません: {slug}.md")
            continue

        print(f"  現タイトル: {article['title']}")

        # Step 3: Claude APIで改善案生成
        print("  Claude APIで改善案を生成中...")
        try:
            result = generate_improvements(article, candidate)
        except Exception as e:
            print(f"  [ERROR] 改善案の生成に失敗: {e}")
            continue

        # 結果表示
        print("\n  ── タイトル案 ──")
        for j, t in enumerate(result.get("title_candidates", []), 1):
            chars = len(t)
            flag = "✓" if chars <= 27 else "!"
            print(f"  {j}. [{chars}字{flag}] {t}")

        print("\n  ── description案 ──")
        for j, d in enumerate(result.get("description_candidates", []), 1):
            print(f"  {j}. [{len(d)}字] {d}")

        print("\n  ── リード文案 ──")
        print(f"  {result.get('lead_rewrite', '')[:200]}...")

        print(f"\n  理由: {result.get('why', '')}")

        if args.dry_run:
            print("\n  [dry-run] ここで止めます（pushしません）")
            log_entries.append({"date": str(date.today()), "slug": slug, "action": "dry-run", "result": result})
            continue

        # Step 4: 採用案を選択
        print("\n  タイトル番号を選んでください（1/2/3 or s=スキップ）: ", end="")
        t_choice = input().strip()
        if t_choice == "s":
            print("  スキップ")
            continue

        try:
            chosen_title = result["title_candidates"][int(t_choice) - 1]
        except (ValueError, IndexError):
            print("  無効な選択。スキップします。")
            continue

        print("  description番号を選んでください（1/2 or s=スキップ）: ", end="")
        d_choice = input().strip()
        if d_choice == "s":
            continue

        try:
            chosen_desc = result["description_candidates"][int(d_choice) - 1]
        except (ValueError, IndexError):
            print("  無効な選択。スキップします。")
            continue

        print("  リード文も更新しますか？（y/n）: ", end="")
        use_lead = input().strip().lower() == "y"
        lead = result.get("lead_rewrite", "") if use_lead else ""

        # Step 5: ファイル修正
        apply_improvement(article, chosen_title, chosen_desc, lead)
        print(f"  ✓ ファイルを更新しました")

        # Step 6: Git push確認
        print("  git pushしますか？（y/n）: ", end="")
        do_push = input().strip().lower() == "y"
        if do_push:
            if git_push(slug):
                print("  ✓ pushしました → Cloudflareデプロイ開始")
            else:
                print("  pushに失敗しました")

        log_entries.append({
            "date": str(date.today()),
            "slug": slug,
            "old_title": article["title"],
            "new_title": chosen_title,
            "action": "applied",
        })

    save_log(log_entries)
    print(f"\n{'='*60}")
    print("完了。ログ: logs/auto_improve_log.json")


if __name__ == "__main__":
    main()
