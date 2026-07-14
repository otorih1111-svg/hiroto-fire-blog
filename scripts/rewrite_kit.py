#!/usr/bin/env python3
"""
ブログリライトツール（2026-07-12追加）
======================================
KWツールの姉妹品。GSCの実データから「直せば伸びる記事」を検出して、
リライト指示をコピーできるHTMLを出力する。

検出する3タイプ:
  A. クイックウィン   : 4〜20位で表示が出ているクエリ → その問いに答える章を足す
  B. タイトル改善     : 10位以内なのにCTRが低い → タイトル・description・冒頭を直す
  C. 沈没記事         : 公開30日以上で表示がほぼない → 構成見直し・統合・様子見を判断

ルール準拠:
  - 公開/大幅リライトから14日以内の記事は提案しない（公開後チェックルール）
  - 同じ記事は14日間再提案しない（logs/rewrite_kit_log.json）

出力: ~/ReplyKit/ブログリライトツール.html
実行: /usr/bin/python3 scripts/rewrite_kit.py [--dry-run]
launchd: com.hiroto.rewrite-kit（毎週月曜07:00）
"""

from __future__ import annotations

import datetime
import html
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_kw_proposals import load_env, load_existing_articles  # noqa: E402
from kw_kit import _google_session, _gsc_query, enrich_pubdates  # noqa: E402

BLOG_DIR = SCRIPT_DIR.parent
KIT_PATH = Path.home() / "ReplyKit" / "ブログリライトツール.html"
LOG_FILE = BLOG_DIR / "logs" / "rewrite_kit_log.json"

PICKS = 5
RECENT_GUARD_DAYS = 14   # 公開・提案からこの日数は触らない
SUNK_MIN_AGE_DAYS = 30   # 沈没判定は公開30日以上のみ


def gsc_by_page_query(session, days: int) -> list[dict]:
    end = datetime.date.today() - datetime.timedelta(days=2)
    start = end - datetime.timedelta(days=days)
    rows = _gsc_query(session, {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["page", "query"],
        "rowLimit": 1000,
    })
    return rows


def gsc_by_page(session, days: int) -> dict[str, dict]:
    end = datetime.date.today() - datetime.timedelta(days=2)
    start = end - datetime.timedelta(days=days)
    rows = _gsc_query(session, {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["page"],
        "rowLimit": 500,
    })
    out = {}
    for r in rows:
        out[r["keys"][0]] = {
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr": r.get("ctr", 0.0),
            "position": r.get("position", 0.0),
        }
    return out


def slug_of(url: str) -> str:
    m = re.search(r"/blog/([^/]+)/?$", url)
    return m.group(1) if m else ""


def detect_opportunities(articles: list[dict], page_stats: dict, pq_rows: list[dict]) -> list[dict]:
    today = datetime.date.today()
    art_by_slug = {a["slug"]: a for a in articles}
    opportunities: list[dict] = []

    def age_days(a: dict) -> int:
        # 「最後に触った日」からの経過日数。リライト済み記事はupdatedDateが新しいので
        # pubDateが古くてもガード対象になる（2026-07-14: リライト直後の記事が再提案された事故対応）。
        dates = []
        for key in ("pubDate", "updatedDate"):
            val = a.get(key, "")
            if val:
                try:
                    dates.append(datetime.date.fromisoformat(val))
                except ValueError:
                    pass
        if not dates:
            return 999
        return (today - max(dates)).days

    # A: クイックウィン（クエリ単位）
    for r in pq_rows:
        page, query = r["keys"][0], r["keys"][1]
        pos, imp = r.get("position", 99), r.get("impressions", 0)
        slug = slug_of(page)
        a = art_by_slug.get(slug)
        if not a or not (4 <= pos <= 20 and imp >= 3):
            continue
        if age_days(a) < RECENT_GUARD_DAYS:
            continue
        opportunities.append({
            "type": "A_クイックウィン",
            "slug": slug,
            "title": a["title"],
            "category": a.get("category", ""),
            "evidence": f"クエリ「{query}」が{pos:.0f}位・表示{imp}回（過去28日）",
            "query": query,
            "score": imp * (21 - pos),
        })

    # B: タイトル改善（10位以内・CTR2%未満・表示10回以上）
    for page, s in page_stats.items():
        slug = slug_of(page)
        a = art_by_slug.get(slug)
        if not a or age_days(a) < RECENT_GUARD_DAYS:
            continue
        if s["position"] <= 10 and s["impressions"] >= 10 and s["ctr"] < 0.02:
            opportunities.append({
                "type": "B_タイトル改善",
                "slug": slug,
                "title": a["title"],
                "category": a.get("category", ""),
                "evidence": f"平均{s['position']:.0f}位・表示{s['impressions']}回なのにクリック{s['clicks']}回（CTR {s['ctr']*100:.1f}%）",
                "query": "",
                "score": s["impressions"],
            })

    # C: 沈没記事（公開30日以上・90日表示3回未満）
    for a in articles:
        if a.get("category") == "副業・AI":
            continue  # 副業はリライト優先度を落とす方針
        if age_days(a) < SUNK_MIN_AGE_DAYS:
            continue
        page_url = f"https://hiroto-fire.com/blog/{a['slug']}/"
        s = page_stats.get(page_url)
        imp = s["impressions"] if s else 0
        if imp < 3:
            opportunities.append({
                "type": "C_沈没",
                "slug": a["slug"],
                "title": a["title"],
                "category": a.get("category", ""),
                "evidence": f"公開{age_days(a)}日で表示{imp}回（過去28日）。検索意図とのズレか、KW未整理の可能性",
                "query": "",
                "score": 1,
            })

    return opportunities


def build_instruction(o: dict) -> str:
    base = (
        f"既存記事のリライトをお願いします。\n"
        f"・対象記事：{o['title']}（slug: {o['slug']}）\n"
        f"・根拠データ：{o['evidence']}\n"
    )
    if o["type"] == "A_クイックウィン":
        base += (
            f"・やること：クエリ「{o['query']}」の検索意図に正面から答えるH2（または既存H2の強化）を追加。"
            f"リライトルール（KW確認→役割整理→タイトル/desc/リード調整）に従い、"
            f"本文とタイトル・descriptionの整合、内部リンク（FP相談/NISA/ロードマップの該当するもの）も見直してください\n"
        )
    elif o["type"] == "B_タイトル改善":
        base += (
            "・やること：順位はあるのにクリックされていないので、本文より先にタイトル・description・冒頭を見直す（公開後チェックルール準拠）。"
            "GSCの表示クエリを確認し、検索者のベネフィットが先頭に来るタイトル（32字以内）に。descriptionは70〜120字\n"
        )
    else:
        base += (
            "・やること：まずGSCで表示クエリを確認し、狙うKWと記事の役割（集客/体験談/成約）を再整理。"
            "勝ち目がないKWなら記事の角度替えか、近い記事への統合を提案してください（勝手に統合はせず提案まで）\n"
        )
    base += (
        "・リライト時はfrontmatterの updatedDate を今日の日付に設定してください"
        "（リライトツールが「最近触った記事」を再提案しないための目印。pubDateは変えない）\n"
    )
    base += "・リライト後は自己採点85点以上を確認して公開、デプロイ確認までお願いします"
    return base


def pick_with_claude(env, opportunities: list[dict]):
    import anthropic

    client = anthropic.Anthropic(api_key=env.get("ANTHROPIC_API_KEY", ""))
    lines = [
        f"- slug:{o['slug']} [{o['type']}] {o['title']}（{o['category']}）｜{o['evidence']}"
        for o in opportunities[:40]
    ]
    prompt = f"""あなたは「hiroto-fire.com」のSEO編集者です。以下はGSC実データから検出したリライト候補です。

{chr(10).join(lines)}

【選定ルール】
- 効果が出そうな順に{PICKS}件選ぶ
- A（クイックウィン）を最優先、次にB（タイトル改善）。Cは本当に価値がありそうなものだけ
- 収益導線（FP相談・保険・楽天証券）に近い記事は加点
- 各件に「何をどう直すか」の具体案を1-2文で

【出力形式（JSONのみ。slugは候補リストのものをそのまま使う）】
{{"comment": "今週のリライト方針を1文", "picks": [{{"slug": "記事のslug", "type": "A_クイックウィン|B_タイトル改善|C_沈没", "plan": "具体的な直し方1-2文", "priority": 1}}]}}"""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    m = re.search(r"\{.*\}", resp.content[0].text.strip(), re.DOTALL)
    return json.loads(m.group(0))


def render_kit(comment: str, picks: list[dict]) -> None:
    now_str = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")
    gen_iso = datetime.date.today().isoformat()  # ブラウザ側で「何日前のページか」を計算する基準
    type_label = {"A_クイックウィン": "🎯 クイックウィン", "B_タイトル改善": "✏️ タイトル改善", "C_沈没": "🛟 救助検討"}
    cards = []
    for i, p in enumerate(sorted(picks, key=lambda x: x.get("priority", 9)), start=1):
        o = p["_op"]
        instruction = html.escape(build_instruction(o) + f"\n・編集者の具体案：{p.get('plan','')}")
        badge = "🥇 いちおし" if i == 1 else f"{i}"
        cards.append(f"""
<div class="card">
  <p class="who">{badge}　<strong>{html.escape(o['title'])}</strong>　<span class="cat">{type_label.get(o['type'], o['type'])}</span></p>
  <p class="sig">根拠: {html.escape(o['evidence'])}</p>
  <p class="src"><strong>直し方:</strong> {html.escape(p.get('plan', ''))}</p>
  <textarea id="rw{i}" readonly style="display:none;">{instruction}</textarea>
  <p><button class="btn copy" onclick="cp('rw{i}', this)">このリライト指示をコピー</button></p>
</div>""")

    page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>ブログリライトツール</title>
<style>
body {{ font-family: "Hiragino Kaku Gothic ProN", sans-serif; max-width: 760px; margin: 32px auto; padding: 0 20px; line-height: 1.8; color: #333; }}
h1 {{ color: #1F4D32; font-size: 1.4rem; }}
.btn {{ display: inline-block; border: none; cursor: pointer; padding: 8px 16px; border-radius: 20px; font-size: 0.92rem; background: #ef7f1a; color: #fff; }}
.card {{ border: 1px solid #CDE6D6; border-radius: 10px; padding: 14px 16px; margin: 14px 0; }}
.who {{ color: #1F4D32; margin: 0 0 6px; font-size: 1.0rem; }}
.cat {{ font-size: 0.78rem; background: #EAF4ED; color: #1F4D32; border-radius: 999px; padding: 2px 10px; }}
.sig {{ color: #b35c05; font-size: 0.84rem; margin: 0 0 4px; }}
.src {{ background: #f6f6f4; border-radius: 8px; padding: 10px 12px; font-size: 0.9rem; color: #555; margin: 0 0 8px; }}
.box {{ background: #F3FAF6; border-left: 3px solid #2d7a4f; padding: 10px 16px; margin: 10px 0; font-size: 0.9rem; }}
small {{ color: #888; }}
.freshbar {{ font-size: 0.9rem; border-radius: 8px; padding: 8px 14px; margin: 8px 0 14px; background: #EAF4ED; color: #1F4D32; }}
.freshbar.stale {{ background: #fdeaea; color: #b12020; border: 1px solid #e7a3a3; font-weight: bold; }}
</style>
<script>
function cp(id, btn) {{
  navigator.clipboard.writeText(document.getElementById(id).value);
  const o = btn.textContent;
  btn.textContent = 'コピーしました！Claude Codeに貼ってください';
  setTimeout(() => btn.textContent = o, 2500);
}}
// 古いページを開いたときに「何日前のデータか」を警告する（stale snapshot対策）
function checkFresh() {{
  const gen = new Date('{gen_iso}T00:00:00');
  const days = Math.floor((Date.now() - gen.getTime()) / 86400000);
  const bar = document.getElementById('freshbar');
  if (!bar) return;
  if (days <= 1) {{
    bar.textContent = '🟢 このページは' + gen.toLocaleDateString('ja-JP') + '生成（最新）。';
  }} else {{
    bar.className = 'freshbar stale';
    bar.textContent = '⚠️ このページは' + days + '日前（' + gen.toLocaleDateString('ja-JP')
      + '）の候補です。表示回数などのデータも古い可能性があります。'
      + 'リライトツールを再実行して最新化してください。';
  }}
}}
</script>
</head>
<body onload="checkFresh()">
<h1>ブログリライトツール</h1>
<div id="freshbar" class="freshbar">生成日を確認中…</div>
<p><small>生成: {now_str}｜GSC実データから「直せば伸びる記事」を検出（週1・月曜更新）</small></p>
<div class="box"><strong>今週の方針:</strong> {html.escape(comment)}</div>
<p>使い方: 「リライト指示をコピー」→ Claude Codeに貼るだけ。公開・大幅リライトから14日以内の記事、およびupdatedDateが新しい記事は自動で除外しています。</p>
{''.join(cards) if cards else '<p>今週はリライト候補がありません。新規記事とリプ回りに時間を使いましょう。</p>'}
</body>
</html>"""
    KIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    KIT_PATH.write_text(page, encoding="utf-8")


def main() -> None:
    dry = "--dry-run" in sys.argv
    env = load_env()
    articles = enrich_pubdates(load_existing_articles())
    session = _google_session()

    page_stats = gsc_by_page(session, days=28)
    pq_rows = gsc_by_page_query(session, days=28)
    opportunities = detect_opportunities(articles, page_stats, pq_rows)

    # 直近提案済みslugを除外
    log = []
    if LOG_FILE.exists():
        try:
            log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log = []
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=RECENT_GUARD_DAYS)).isoformat()
    recent_slugs = {e["slug"] for e in log if cutoff <= e.get("date", "") < today.isoformat()}
    opportunities = [o for o in opportunities if o["slug"] not in recent_slugs]
    opportunities.sort(key=lambda o: -o["score"])

    if not opportunities:
        render_kit("今週はリライトより新規とリプ回りを優先でOKです。", [])
        print(f"written (empty): {KIT_PATH}")
        return

    result = pick_with_claude(env, opportunities)
    picks = result.get("picks", [])[:PICKS]

    # Claudeの選定をopportunityに紐付け（slugで突き合わせ）
    by_slug = {}
    for o in opportunities:
        by_slug.setdefault(o["slug"], o)
    final = []
    for p in picks:
        o = by_slug.get(p.get("slug"))
        if o:
            p["_op"] = o
            final.append(p)

    if dry:
        print(json.dumps({"comment": result.get("comment"), "picks": [
            {k: v for k, v in p.items() if k != "_op"} | {"evidence": p["_op"]["evidence"], "slug": p["_op"]["slug"]}
            for p in final
        ]}, ensure_ascii=False, indent=1))
        return

    render_kit(result.get("comment", ""), final)
    log.extend({"date": today.isoformat(), "slug": p["_op"]["slug"]} for p in final)
    LOG_FILE.write_text(json.dumps(log[-300:], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {KIT_PATH}")


if __name__ == "__main__":
    main()
