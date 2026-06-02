#!/usr/bin/env python3
"""
check_seo.py
push後にSEO状態を自動チェックするスクリプト

チェック項目:
  1. HTTPステータス 200
  2. x-robots-tag: noindex がないか
  3. sitemapに掲載されているか
  4. canonical が正しいか

使い方:
  python3 scripts/check_seo.py              # 重要記事リストを全チェック
  python3 scripts/check_seo.py --all        # 全公開記事をチェック
  python3 scripts/check_seo.py --url https://hiroto-fire.com/blog/xxx/  # 1記事のみ

出力:
  ✅ 問題なし
  ❌ 要確認（理由付き）
"""

from __future__ import annotations

import sys
import re
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

BLOG_BASE = "https://hiroto-fire.com"
SITEMAP_URL = f"{BLOG_BASE}/sitemap-0.xml"
BLOG_DIR = Path(__file__).resolve().parents[1]
CONTENT_DIR = BLOG_DIR / "src" / "content" / "blog"

# ── 重要記事リスト（アフィリリンクあり・主力SEO記事）──
PRIORITY_URLS = [
    # 節約・家計
    f"{BLOG_BASE}/blog/koteihi-minaoshi/",
    f"{BLOG_BASE}/blog/rakuten-keizaiken-single-father/",
    f"{BLOG_BASE}/blog/rakuten-mobile-review/",
    f"{BLOG_BASE}/blog/rakuten-point-tsushinhi-zero/",
    f"{BLOG_BASE}/blog/kakuyasu-sim-fuan/",
    f"{BLOG_BASE}/blog/rakuten-mobile-vs-ahamo/",
    f"{BLOG_BASE}/blog/mnp-rakuten-mobile-steps/",
    # 投資・FIRE
    f"{BLOG_BASE}/blog/nisa-tsumitate-40dai/",
    f"{BLOG_BASE}/blog/hottarakashi-investment-nisa-begin/",
    f"{BLOG_BASE}/blog/gakushihoken-junior-nisa-single-father/",
    f"{BLOG_BASE}/blog/2026-05-22-single-fatherfire/",
    # 副業・AI
    f"{BLOG_BASE}/blog/2026-05-21-fp-sodan-review/",
    f"{BLOG_BASE}/blog/2026-05-27-moneyforward-cloud-tax-review/",
    f"{BLOG_BASE}/blog/2026-05-21-hapitas-hajimekata-kasegikata/",
    f"{BLOG_BASE}/blog/2026-05-21-jiko-affiliate-kasegikata/",
]


def fetch(url: str, timeout: int = 10) -> tuple[int, dict, str]:
    """URLをフェッチしてステータス・ヘッダー・本文を返す"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            headers = dict(res.headers)
            body = res.read(50000).decode("utf-8", errors="ignore")
            return res.status, headers, body
    except urllib.error.HTTPError as e:
        return e.code, {}, ""
    except Exception as e:
        return 0, {}, str(e)


def check_url(url: str, sitemap_urls: set[str]) -> dict:
    """1URLのSEO状態をチェックして結果を返す"""
    result = {
        "url": url,
        "status": None,
        "noindex": False,
        "in_sitemap": False,
        "canonical_ok": True,
        "errors": [],
        "ok": True,
    }

    # 1. HTTPステータス
    status, headers, body = fetch(url)
    result["status"] = status

    if status != 200:
        result["errors"].append(f"HTTP {status}（200以外）")
        result["ok"] = False
        return result

    # 2. x-robots-tag
    robots_header = headers.get("X-Robots-Tag", headers.get("x-robots-tag", ""))
    if "noindex" in robots_header.lower():
        result["noindex"] = True
        result["errors"].append(f"x-robots-tag: {robots_header}")
        result["ok"] = False

    # 3. meta robots noindex（HTML内）
    if re.search(r'<meta[^>]+name=["\']robots["\'][^>]+content=["\'][^"\']*noindex', body, re.I):
        result["noindex"] = True
        result["errors"].append("meta robots: noindex")
        result["ok"] = False

    # 4. sitemapに掲載されているか
    canonical = url.rstrip("/") + "/"
    result["in_sitemap"] = canonical in sitemap_urls or url in sitemap_urls
    if not result["in_sitemap"]:
        result["errors"].append("sitemapに未掲載")
        result["ok"] = False

    # 5. canonical確認
    canonical_match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', body, re.I)
    if canonical_match:
        page_canonical = canonical_match.group(1).rstrip("/") + "/"
        expected = url.rstrip("/") + "/"
        if page_canonical != expected:
            result["canonical_ok"] = False
            result["errors"].append(f"canonical不一致: {page_canonical}")
            result["ok"] = False

    return result


def fetch_sitemap_urls() -> set[str]:
    """サイトマップから全URLを取得"""
    _, _, body = fetch(SITEMAP_URL)
    return set(re.findall(r'<loc>(https?://[^<]+)</loc>', body))


def get_all_published_urls() -> list[str]:
    """公開済み記事のURL一覧をローカルファイルから生成"""
    urls = []
    for md in sorted(CONTENT_DIR.glob("*.md")):
        content = md.read_text(encoding="utf-8")
        if re.search(r'^draft:\s*true', content, re.MULTILINE):
            continue
        slug_m = re.search(r'^slug:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
        if slug_m:
            slug = slug_m.group(1)
        else:
            slug = md.stem
        urls.append(f"{BLOG_BASE}/blog/{slug}/")
    return urls


def print_result(r: dict, verbose: bool = False):
    icon = "✅" if r["ok"] else "❌"
    path = r["url"].replace(BLOG_BASE, "")
    sitemap_icon = "🗺" if r["in_sitemap"] else "❌"
    print(f"{icon} {path}  HTTP:{r['status']}  Sitemap:{sitemap_icon}", end="")
    if r.get("errors"):
        print(f"  → {' / '.join(r['errors'])}", end="")
    print()


def main():
    parser = argparse.ArgumentParser(description="SEO状態チェックスクリプト")
    parser.add_argument("--all", action="store_true", help="公開済み全記事をチェック")
    parser.add_argument("--url", help="特定URLをチェック")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print(f"\n🔍 SEOチェック開始 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print("サイトマップを取得中...")
    sitemap_urls = fetch_sitemap_urls()
    print(f"  → {len(sitemap_urls)}件のURLを確認\n")

    if args.url:
        urls = [args.url]
    elif args.all:
        urls = get_all_published_urls()
        print(f"公開記事 {len(urls)}本をチェックします\n")
    else:
        urls = PRIORITY_URLS
        print(f"重要記事 {len(urls)}本をチェックします\n")

    results = []
    for url in urls:
        r = check_url(url, sitemap_urls)
        print_result(r, args.verbose)
        results.append(r)
        time.sleep(0.5)  # サーバー負荷軽減

    # サマリー
    ok = [r for r in results if r["ok"]]
    ng = [r for r in results if not r["ok"]]
    not_in_sitemap = [r for r in results if not r["in_sitemap"]]

    print(f"\n{'='*60}")
    print(f"📊 結果サマリー")
    print(f"  ✅ 問題なし: {len(ok)}本")
    print(f"  ❌ 要確認:   {len(ng)}本")
    print(f"  ❌ Sitemap未掲載: {len(not_in_sitemap)}本")

    if ng:
        print(f"\n⚠️  要確認リスト:")
        for r in ng:
            print(f"  {r['url']}")
            for e in r['errors']:
                print(f"    → {e}")

    if not_in_sitemap:
        print(f"\n📋 Sitemap未掲載（Search Consoleで手動申請推奨）:")
        for r in not_in_sitemap:
            print(f"  {r['url']}")

    print(f"\nSearch Console: https://search.google.com/search-console/\n")


if __name__ == "__main__":
    main()
