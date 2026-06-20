#!/usr/bin/env python3
"""
公開直後に Google 向けのシグナルをまとめて送る。

やること:
  1. Search Console API で sitemap-index.xml を再送信
  2. 直近の indexing ログから更新URLを拾う
  3. 更新URLの indexability を簡易チェック
  4. 結果を logs/indexing/ に保存

注意:
  Google には一般ブログ記事向けの「request indexing API」はない。
  そのため、このスクリプトは sitemap 再送信と公開健全性チェックを自動化する。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

import check_seo


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "indexing"
DEFAULT_SERVICE_ACCOUNT = ROOT / "google-credentials.json"
LATEST_INDEXING_LOG = LOG_DIR / "latest-indexing.json"
LATEST_GOOGLE_LOG = LOG_DIR / "latest-google-publish.json"
SITE = "https://hiroto-fire.com"
DEFAULT_SITEMAP_URL = f"{SITE}/sitemap-index.xml"
SCOPES = ["https://www.googleapis.com/auth/webmasters"]


def load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def resolve_credentials_file() -> Path | None:
    configured = get_env("GOOGLE_SERVICE_ACCOUNT_FILE")
    if configured:
        # relative path is resolved from project root
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
    else:
        candidate = DEFAULT_SERVICE_ACCOUNT

    return candidate if candidate.exists() else None


def read_latest_indexing_log() -> dict[str, Any]:
    if not LATEST_INDEXING_LOG.exists():
        return {}
    try:
        return json.loads(LATEST_INDEXING_LOG.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def unique_urls(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def build_search_console_client(credentials_file: Path):
    credentials = service_account.Credentials.from_service_account_file(
        str(credentials_file),
        scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=credentials, cache_discovery=False)


def submit_sitemap(site_url: str, feedpath: str, credentials_file: Path) -> dict[str, Any]:
    service = build_search_console_client(credentials_file)
    service.sitemaps().submit(siteUrl=site_url, feedpath=feedpath).execute()
    return {
        "ok": True,
        "siteUrl": site_url,
        "feedpath": feedpath,
    }


def run_indexability_checks(urls: list[str]) -> list[dict[str, Any]]:
    if not urls:
        return []

    sitemap_urls = check_seo.fetch_sitemap_urls()
    results: list[dict[str, Any]] = []
    for url in urls:
        result = check_seo.check_url(url, sitemap_urls)
        results.append(
            {
                "url": url,
                "ok": result["ok"],
                "status": result["status"],
                "inSitemap": result["in_sitemap"],
                "canonicalOk": result["canonical_ok"],
                "errors": result["errors"],
            }
        )
    return results


def write_log(payload: dict[str, Any]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    log_path = LOG_DIR / f"{timestamp}-google-publish.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    log_path.write_text(serialized, encoding="utf-8")
    LATEST_GOOGLE_LOG.write_text(serialized, encoding="utf-8")
    return log_path


def print_summary(payload: dict[str, Any]) -> None:
    print("[google-publish] Summary")
    print(f"  updated URLs: {len(payload['updatedUrls'])}")
    print(f"  candidate URLs: {len(payload['searchConsoleCandidates'])}")

    submit = payload["searchConsoleSitemapSubmit"]
    if submit["ok"]:
        print(f"  sitemap submit: OK ({submit['feedpath']})")
    else:
        print(f"  sitemap submit: SKIPPED ({submit['reason']})")

    checks = payload["indexabilityChecks"]
    if checks:
        ok_count = sum(1 for row in checks if row["ok"])
        print(f"  indexability checks: {ok_count}/{len(checks)} OK")
    print("  note: Google has no general-purpose request-indexing API for blog posts.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Google publish signals")
    parser.add_argument("--dry-run", action="store_true", help="送信せずログだけ作る")
    parser.add_argument(
        "--feedpath",
        default=DEFAULT_SITEMAP_URL,
        help="Search Console に再送信する sitemap URL",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="indexability check をかける更新URL数の上限",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    load_env_file()
    args = parse_args(argv)

    latest_indexing = read_latest_indexing_log()
    updated_urls = unique_urls(latest_indexing.get("updatedUrls", []))
    candidate_urls = unique_urls(latest_indexing.get("searchConsoleCandidates", []))
    check_targets = updated_urls[: args.limit]

    site_url = get_env("GSC_SITE_URL")
    credentials_file = resolve_credentials_file()

    submit_result: dict[str, Any]
    if args.dry_run:
        submit_result = {
            "ok": False,
            "reason": "dry-run",
            "feedpath": args.feedpath,
        }
    elif not site_url:
        submit_result = {
            "ok": False,
            "reason": "GSC_SITE_URL が未設定",
            "feedpath": args.feedpath,
        }
    elif credentials_file is None:
        submit_result = {
            "ok": False,
            "reason": "サービスアカウントファイルが見つからない",
            "feedpath": args.feedpath,
        }
    else:
        try:
            submit_result = submit_sitemap(site_url, args.feedpath, credentials_file)
        except Exception as exc:  # pragma: no cover - external API behavior
            submit_result = {
                "ok": False,
                "reason": str(exc),
                "feedpath": args.feedpath,
            }

    indexability_checks = run_indexability_checks(check_targets)

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "site": SITE,
        "updatedUrls": updated_urls,
        "searchConsoleCandidates": candidate_urls,
        "searchConsoleSitemapSubmit": submit_result,
        "indexabilityChecks": indexability_checks,
        "requestIndexingApi": {
            "supported": False,
            "reason": "Google does not provide a general request-indexing API for normal blog posts.",
        },
        "sources": {
            "latestIndexingLog": str(LATEST_INDEXING_LOG.relative_to(ROOT)) if LATEST_INDEXING_LOG.exists() else None,
        },
    }

    log_path = write_log(payload)
    print_summary(payload)
    print(f"  log: {log_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
