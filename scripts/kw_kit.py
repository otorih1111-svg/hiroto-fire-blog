#!/usr/bin/env python3
"""
ブログKWキット 毎日自動生成（2026-07-12追加）
==============================================
リプ回りキットのブログ版。毎朝、
1. 既存記事のカテゴリバランスから「今日書くならこのカテゴリ」を判定
2. Googleサジェスト（無料・審査不要）でロングテールKW候補を発掘
3. GSCの実クエリデータで「すでに表示が出ている需要」を突き合わせ
4. Claudeが角度・タイトル案・内部リンクを付けて7本に絞る
5. ~/ReplyKit/ブログKWキット.html に出力 → ひろとさんが選んで
   「書く指示をコピー」→ Claude Codeに貼ると執筆が始まる

Google Ads API（キーワードプランナー）が承認されたら、検索ボリューム数値を
このキットに追加する（generate_kw_proposals.py と統合予定）。

実行: /usr/bin/python3 scripts/kw_kit.py [--dry-run]
launchd: com.hiroto.kw-kit（毎朝06:50）
"""

from __future__ import annotations

import datetime
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_kw_proposals import load_env, load_existing_articles, is_duplicate  # noqa: E402

BLOG_DIR = SCRIPT_DIR.parent
CONTENT_DIR = BLOG_DIR / "src" / "content" / "blog"
KIT_PATH = Path.home() / "ReplyKit" / "ブログKWキット.html"
LOG_FILE = BLOG_DIR / "logs" / "kw_kit_log.json"
SITE_URL = "https://hiroto-fire.com/"

# 戦略: 副業・AIは新規停止（CLAUDE.md）。節約・家計を主軸、投資・FIREを準主軸。
CATEGORY_TARGET_RATIO = {"節約・家計": 0.6, "投資・FIRE": 0.4}

CATEGORY_SEEDS = {
    "節約・家計": [
        "固定費 見直し",
        "教育費",
        "家計簿 続かない",
        "保険 見直し",
        "食費 節約",
        "先取り貯金",
        "児童手当",
        "シングルファーザー 家計",
        "光回線 乗り換え",
    ],
    "投資・FIRE": [
        "新NISA 40代",
        "新NISA 初心者",
        "楽天証券 積立",
        "生活防衛資金",
        "投資 いくらから",
        "iDeCo 40代",
    ],
}

SUGGEST_MODIFIERS = ["", " 40代", " 子供"]
MAX_CANDIDATES_FOR_CLAUDE = 40
PICKS = 7


def fetch_suggest(query: str) -> list[str]:
    q = urllib.parse.quote(query)
    url = f"https://suggestqueries.google.com/complete/search?client=firefox&hl=ja&q={q}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
        for enc in ("utf-8", "shift_jis", "euc-jp"):
            try:
                return json.loads(raw.decode(enc))[1]
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return []


def collect_candidates(category: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for seed in CATEGORY_SEEDS[category]:
        for mod in SUGGEST_MODIFIERS:
            for s in fetch_suggest(seed + mod + " "):
                s = re.sub(r"\s+", " ", s).strip()
                # 2語以上のロングテールのみ・シード自身は除外
                if s and s not in seen and len(s.split(" ")) >= 2 and s != seed:
                    seen.add(s)
                    out.append(s)
            time.sleep(0.4)
    return out


def fetch_gsc_queries(days: int = 90) -> list[dict]:
    """GSCの実クエリ（表示回数・順位）。サービスアカウント認証。失敗したら空でよい。"""
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            str(BLOG_DIR / "google-credentials.json"),
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
        )
        session = AuthorizedSession(creds)
        end = datetime.date.today() - datetime.timedelta(days=2)
        start = end - datetime.timedelta(days=days)
        endpoint = (
            "https://searchconsole.googleapis.com/webmasters/v3/sites/"
            + urllib.parse.quote(SITE_URL, safe="")
            + "/searchAnalytics/query"
        )
        resp = session.post(endpoint, json={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["query"],
            "rowLimit": 500,
        }, timeout=30)
        resp.raise_for_status()
        return [
            {"query": row["keys"][0], "impressions": row.get("impressions", 0), "position": row.get("position", 0)}
            for row in resp.json().get("rows", [])
        ]
    except Exception as exc:  # noqa: BLE001
        print(f"GSC取得スキップ: {exc}", file=sys.stderr)
        return []


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[ぁ-んァ-ヶ一-龠a-zA-Z0-9]+", text.lower()))


def match_gsc_signal(candidate: str, gsc_rows: list[dict]) -> dict | None:
    cand_tokens = tokenize(candidate)
    if not cand_tokens:
        return None
    best = None
    for row in gsc_rows:
        q_tokens = tokenize(row["query"])
        if not q_tokens:
            continue
        overlap = len(cand_tokens & q_tokens) / len(cand_tokens)
        if overlap >= 0.6:
            if best is None or row["impressions"] > best["impressions"]:
                best = row
    return best


def enrich_pubdates(articles: list[dict]) -> list[dict]:
    for a in articles:
        f = CONTENT_DIR / f"{a['slug']}.md"
        a["pubDate"] = ""
        if f.exists():
            m = re.search(r"^pubDate:\s*(\S+)", f.read_text(encoding="utf-8"), re.MULTILINE)
            if m:
                a["pubDate"] = m.group(1).strip()
    return articles


def category_balance(articles: list[dict]) -> tuple[str, dict]:
    """直近28日の公開実績と目標比率から、今日のおすすめカテゴリを決める。"""
    recent_cut = (datetime.date.today() - datetime.timedelta(days=28)).isoformat()
    counts = {"節約・家計": 0, "投資・FIRE": 0, "副業・AI": 0}
    recent = {"節約・家計": 0, "投資・FIRE": 0, "副業・AI": 0}
    for a in articles:
        cat = a.get("category", "")
        if cat in counts:
            counts[cat] += 1
            if a.get("pubDate", "") >= recent_cut:
                recent[cat] += 1
    recent_total = max(1, recent["節約・家計"] + recent["投資・FIRE"])
    # 目標比率に対して直近の不足が大きい方をすすめる
    gaps = {
        cat: CATEGORY_TARGET_RATIO[cat] - (recent[cat] / recent_total)
        for cat in CATEGORY_TARGET_RATIO
    }
    recommended = max(gaps, key=gaps.get)
    stats = {"total": counts, "recent28": recent, "recommended": recommended}
    return recommended, stats


def load_proposed_log() -> list[dict]:
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []
    return []


def pick_with_claude(env, category, stats, candidates, articles):
    import anthropic

    client = anthropic.Anthropic(api_key=env.get("ANTHROPIC_API_KEY", ""))
    article_titles = "\n".join(f"- {a['title']}（{a.get('category','')}）" for a in articles if a.get("title"))
    cand_lines = []
    for c in candidates:
        sig = c.get("gsc")
        sig_txt = f"｜GSC: 表示{sig['impressions']}回・順位{sig['position']:.0f}位（{sig['query']}）" if sig else ""
        cand_lines.append(f"- {c['kw']}{sig_txt}")

    prompt = f"""あなたは「hiroto-fire.com」（40代シングルファーザーの家計改善×FIREブログ）のSEO編集者です。

【今日のおすすめカテゴリ】{category}
【記事数の現状】全体: {stats['total']}／直近28日: {stats['recent28']}

【KW候補（Googleサジェスト由来＝実際に検索されている語。GSC印付きはすでにこのサイトに表示が出ている需要）】
{chr(10).join(cand_lines)}

【既存記事タイトル（重複・カニバリ禁止。内部リンク先の候補でもある）】
{article_titles}

【選定ルール】
- {PICKS}本選ぶ。おすすめカテゴリ優先だが、明らかに強い候補が他カテゴリ（節約・家計/投資・FIRE内）にあれば混ぜてよい
- 副業・AI系は選ばない（新規停止中）
- 1記事1KW。既存記事と検索意図が重なるものは除外
- 悩みが具体的で、40代・子持ち・ひとり親の属性を絡めやすいDO/KNOWクエリを優先
- FP相談・保険相談・楽天証券への内部導線につながる悩みは加点
- GSC印付きは「すでに戦えている証拠」なので加点

【出力形式（JSONのみ。他の文字は出さない）】
{{"comment": "今日のカテゴリ推薦理由を1-2文", "picks": [{{"kw": "...", "category": "節約・家計|投資・FIRE", "angle": "ひろと属性での切り口を1文", "title": "タイトル案（32字以内）", "reason": "選定理由を1文", "links": ["内部リンク先の既存記事タイトル", "..."], "priority": 1}}]}}
priorityは1(最推奨)〜{PICKS}。"""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(m.group(0))


def build_instruction(pick: dict) -> str:
    links = "、".join(pick.get("links", [])[:3])
    return (
        f"ブログの新規記事を書いてください。\n"
        f"・メインKW：{pick['kw']}（1記事1KW厳守）\n"
        f"・カテゴリ：{pick['category']}\n"
        f"・狙う角度：{pick['angle']}\n"
        f"・タイトル案：{pick['title']}（改善してよい）\n"
        f"・内部リンク候補：{links}\n"
        f"・hiroto-fire-blogのCLAUDE.mdルール完全遵守（実話のみ・数字は実績のみ・サムネ＋本文画像・免責・FAQ判断）\n"
        f"・リサーチ→執筆→画像→自己採点85点以上→公開・デプロイ確認まで一気にやってください"
    )


def render_kit(comment: str, picks: list[dict], stats: dict, category: str) -> None:
    now_str = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")
    cards = []
    for i, p in enumerate(sorted(picks, key=lambda x: x.get("priority", 9)), start=1):
        instruction = html.escape(build_instruction(p))
        badge = "🥇 いちおし" if i == 1 else f"{i}"
        sig = html.escape(p.get("signal", ""))
        sig_html = f'<p class="sig">{sig}</p>' if sig else ""
        cards.append(f"""
<div class="card">
  <p class="who">{badge}　<strong>{html.escape(p['kw'])}</strong>　<span class="cat">{html.escape(p['category'])}</span></p>
  {sig_html}
  <p class="src">角度: {html.escape(p['angle'])}<br>タイトル案: {html.escape(p['title'])}<br>理由: {html.escape(p['reason'])}</p>
  <textarea id="kw{i}" readonly style="display:none;">{instruction}</textarea>
  <p><button class="btn copy" onclick="cp('kw{i}', this)">この記事を書く指示をコピー</button></p>
</div>""")

    total = stats["total"]
    recent = stats["recent28"]
    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>ブログKWキット</title>
<style>
body {{ font-family: "Hiragino Kaku Gothic ProN", sans-serif; max-width: 760px; margin: 32px auto; padding: 0 20px; line-height: 1.8; color: #333; }}
h1 {{ color: #1F4D32; font-size: 1.4rem; }}
h2 {{ color: #2d7a4f; font-size: 1.1rem; border-left: 4px solid #2d7a4f; padding-left: 10px; margin-top: 26px; }}
.btn {{ display: inline-block; border: none; cursor: pointer; padding: 8px 16px; border-radius: 20px; font-size: 0.92rem; background: #ef7f1a; color: #fff; }}
.card {{ border: 1px solid #CDE6D6; border-radius: 10px; padding: 14px 16px; margin: 14px 0; }}
.who {{ color: #1F4D32; margin: 0 0 6px; font-size: 1.02rem; }}
.cat {{ font-size: 0.78rem; background: #EAF4ED; color: #1F4D32; border-radius: 999px; padding: 2px 10px; }}
.sig {{ color: #b35c05; font-size: 0.84rem; margin: 0 0 4px; }}
.src {{ background: #f6f6f4; border-radius: 8px; padding: 10px 12px; font-size: 0.9rem; color: #555; margin: 0 0 8px; }}
.box {{ background: #F3FAF6; border-left: 3px solid #2d7a4f; padding: 10px 16px; margin: 10px 0; font-size: 0.9rem; }}
small {{ color: #888; }}
</style>
<script>
function cp(id, btn) {{
  const t = document.getElementById(id);
  navigator.clipboard.writeText(t.value);
  const o = btn.textContent;
  btn.textContent = 'コピーしました！Claude Codeに貼ってください';
  setTimeout(() => btn.textContent = o, 2500);
}}
</script>
</head>
<body>
<h1>ブログKWキット</h1>
<p><small>更新: {now_str}｜KW候補はGoogleサジェスト（実際に検索されている語）＋GSC実データから選定</small></p>
<div class="box">
<strong>今日のおすすめ: {html.escape(category)}</strong><br>
{html.escape(comment)}<br>
<small>記事数 全体: 節約{total['節約・家計']}/投資{total['投資・FIRE']}/副業{total['副業・AI']}　直近28日: 節約{recent['節約・家計']}/投資{recent['投資・FIRE']}（週3本上限・副業は新規停止中）</small>
</div>
<p>使い方: 気に入ったKWの「指示をコピー」→ Claude Codeに貼るだけ。執筆〜採点〜公開まで自動で進みます。どれもピンと来なければ書かない日でOK（週3本まで）。</p>
{''.join(cards)}
<h2>メモ</h2>
<div class="box">
<ul>
<li>検索ボリュームの数値はGoogle Ads API承認後に追加予定（現在は「サジェストに出る=検索されている」を需要の証拠にしています）</li>
<li>同じKWは30日間は再提案しません</li>
</ul>
</div>
</body>
</html>"""
    KIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    KIT_PATH.write_text(page, encoding="utf-8")


def main() -> None:
    dry = "--dry-run" in sys.argv
    env = load_env()
    articles = enrich_pubdates(load_existing_articles())
    category, stats = category_balance(articles)

    # 直近30日に提案済みのKWは除外
    log = load_proposed_log()
    cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    recently_proposed = {e["kw"] for e in log if e.get("date", "") >= cutoff}

    raw = collect_candidates(category)
    gsc_rows = fetch_gsc_queries()

    candidates = []
    for kw in raw:
        if kw in recently_proposed:
            continue
        if is_duplicate(kw, articles):
            continue
        candidates.append({"kw": kw, "gsc": match_gsc_signal(kw, gsc_rows)})
    # GSC印付きを先頭に寄せて上位だけClaudeへ
    candidates.sort(key=lambda c: (c["gsc"] is None, ))
    candidates = candidates[:MAX_CANDIDATES_FOR_CLAUDE]

    if not candidates:
        print("候補が集まりませんでした", file=sys.stderr)
        sys.exit(1)

    result = pick_with_claude(env, category, stats, candidates, articles)
    picks = result.get("picks", [])[:PICKS]

    # GSCシグナルの表示文字列を付与
    sig_map = {c["kw"]: c["gsc"] for c in candidates}
    for p in picks:
        sig = sig_map.get(p["kw"])
        if sig:
            p["signal"] = f"GSC: このサイトが既に表示されています（{sig['query']}・表示{sig['impressions']}回・順位{sig['position']:.0f}位）"

    if dry:
        print(json.dumps({"category": category, "comment": result.get("comment"), "picks": picks}, ensure_ascii=False, indent=1))
        return

    render_kit(result.get("comment", ""), picks, stats, category)
    today = datetime.date.today().isoformat()
    log.extend({"date": today, "kw": p["kw"]} for p in picks)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(json.dumps(log[-500:], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {KIT_PATH}")


if __name__ == "__main__":
    main()
