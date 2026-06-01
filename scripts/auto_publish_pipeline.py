#!/usr/bin/env python3
"""
auto_publish_pipeline.py
ブログ記事の自動生成→採点→書き直し→公開パイプライン

フロー:
  1. generate_blog_post.py で記事生成（draft: true）
  2. score_article.py で採点
  3. 67点以上 → draft: false → git push → 公開
  4. 67点未満 → rewrite_article.py で書き直し → 再採点（最大2回）
  5. 2回試してもNGなら draft: true のまま停止（手動確認）

使い方:
  python3 scripts/auto_publish_pipeline.py
  python3 scripts/auto_publish_pipeline.py --dry-run   # 生成・採点のみ（pushなし）
  python3 scripts/auto_publish_pipeline.py --score-only # 既存draft記事を採点→公開判定のみ
"""

from __future__ import annotations

import sys
import os
import json
import re
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

BLOG_DIR = Path(__file__).resolve().parents[1]
CONTENT_DIR = BLOG_DIR / "src" / "content" / "blog"
SNS_DIR = BLOG_DIR.parent / "threads_affiliate_system"

PASS_SCORE = 67   # 自動採点が5〜10点甘い傾向のため補正（実質90%相当）
MAX_RETRIES = 2
AUTO_PUBLISH = False  # Trueにすると自動公開。アドセンス通過後に検討
LOG_DIR = BLOG_DIR / "logs"


def _load_env_key() -> str:
    env_file = SNS_DIR / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def _get_client():
    try:
        import anthropic
    except ImportError:
        print("❌ anthropicライブラリが必要: pip install anthropic")
        sys.exit(1)
    api_key = os.environ.get("ANTHROPIC_API_KEY") or _load_env_key()
    if not api_key:
        print("❌ ANTHROPIC_API_KEYが設定されていません")
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def find_new_drafts() -> list[Path]:
    """draft: true の記事を全件返す"""
    drafts = []
    for md in sorted(CONTENT_DIR.glob("*.md")):
        content = md.read_text(encoding="utf-8")
        if re.search(r"^draft:\s*true", content, re.MULTILINE):
            drafts.append(md)
    return drafts


def score_article(file_path: Path) -> dict:
    """score_article.py を呼び出して採点結果を返す"""
    result = subprocess.run(
        [sys.executable, str(BLOG_DIR / "scripts" / "score_article.py"),
         "--file", str(file_path), "--output", "/tmp/score_result.json"],
        capture_output=True, text=True, cwd=str(BLOG_DIR)
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        return {}
    try:
        data = json.loads(Path("/tmp/score_result.json").read_text())
        return data[0] if isinstance(data, list) else data
    except Exception:
        return {}


def rewrite_article(file_path: Path, score_result: dict) -> bool:
    """採点フィードバックをもとに記事を書き直す"""
    log(f"✍️  書き直し中: {file_path.name}")

    client = _get_client()
    content = file_path.read_text(encoding="utf-8")

    instructions = score_result.get("rewrite_instructions", "")
    feedback = score_result.get("feedback", {})
    low_axes = score_result.get("low_axes", [])
    total = score_result.get("total", 0)

    if not instructions and feedback:
        instructions = "\n".join([f"・[{k}] {v}" for k, v in feedback.items()])

    prompt = f"""以下のブログ記事を改善してください。

## 現在の採点結果
合計: {total}/70点（入稿基準: 67点）
低スコア軸: {', '.join(low_axes)}

## 改善指示
{instructions}

## 改善ルール
- frontmatter（---で囲まれた部分）のtitle・description・slug・pubDate・category・draft・affiliate・ogImageはそのまま維持する
- draft: true は変更しない（パイプラインが変更する）
- 記事の大筋・ストーリーは変えない。低スコア軸の部分だけを改善する
- ズボラ感・ポンコツ感・クスッとするツッコミが弱い場合は自然に追加する
- 段落が長い場合は改行を増やす
- 内部リンクが不足している場合は適切な既存記事へのリンクを追加する

## 元の記事
{content}

## 改善後の記事（frontmatterから全文を返してください）
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    new_content = "\n".join(
        block.text for block in response.content if hasattr(block, "text")
    ).strip()

    # ```markdown ... ``` や ```md ... ``` で返ってきても本文を抽出
    fence_match = re.search(r"```(?:markdown|md)?\s*([\s\S]*?)\s*```", new_content)
    if fence_match:
        new_content = fence_match.group(1).strip()

    # frontmatterが含まれているか確認
    if not new_content.startswith("---"):
        log("⚠️  書き直し結果にfrontmatterがありません。元の記事を維持します。")
        return False

    # draft: true を維持
    new_content = re.sub(r"^draft:\s*false", "draft: true", new_content, flags=re.MULTILINE)

    file_path.write_text(new_content, encoding="utf-8")
    log(f"✅ 書き直し完了: {file_path.name}")
    return True


def generate_thumbnail(file_path: Path) -> Path | None:
    """記事のサムネイルを生成して保存パスを返す"""
    content = file_path.read_text(encoding="utf-8")

    # frontmatterからtitle・categoryを取得
    title_m = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    cat_m = re.search(r'^category:\s*(.+?)\s*$', content, re.MULTILINE)
    og_m = re.search(r"^ogImage:\s*['\"](.+?)['\"]", content, re.MULTILINE)

    if not title_m:
        log("⚠️  タイトルが取得できず、サムネ生成をスキップします")
        return None

    title = title_m.group(1)
    category = cat_m.group(1) if cat_m else "副業・AI"

    # ogImageのファイル名からサムネパスを決定
    if og_m:
        thumb_rel = og_m.group(1)  # 例: /images/thumbnails/2026-05-31-xxx.png
        thumb_path = BLOG_DIR / "public" / thumb_rel.lstrip("/")
    else:
        thumb_path = BLOG_DIR / "public" / "images" / "thumbnails" / f"{file_path.stem}.png"

    # すでに存在する場合はスキップ
    if thumb_path.exists():
        log(f"   サムネイル既存: {thumb_path.name}")
        return thumb_path

    log(f"🖼️  サムネイル生成中: {thumb_path.name}")
    result = subprocess.run(
        [sys.executable, str(BLOG_DIR / "scripts" / "generate_thumbnail.py"),
         "--title", title, "--category", category, "--output", str(thumb_path)],
        capture_output=True, text=True, cwd=str(BLOG_DIR)
    )
    if result.returncode == 0:
        log(f"   ✅ サムネイル生成完了: {thumb_path.name}")
        return thumb_path
    else:
        log(f"   ⚠️  サムネイル生成失敗: {result.stderr[:200]}")
        return None


def set_draft_false(file_path: Path):
    """draft: true → draft: false に変更"""
    content = file_path.read_text(encoding="utf-8")
    content = re.sub(r"^draft:\s*true", "draft: false", content, flags=re.MULTILINE)
    file_path.write_text(content, encoding="utf-8")


def git_push(file_paths: list[Path], message: str):
    """指定ファイルをgit add → commit → push"""
    for p in file_paths:
        subprocess.run(["git", "add", str(p)], cwd=str(BLOG_DIR))

    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(BLOG_DIR)
    )
    result = subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=str(BLOG_DIR), capture_output=True, text=True
    )
    if result.returncode == 0:
        log("✅ git push 完了")
    else:
        log(f"❌ git push 失敗: {result.stderr}")


def process_article(file_path: Path, dry_run: bool = False) -> str:
    """
    1記事をスコアチェック→必要なら書き直し→公開
    戻り値: "published" / "rewritten_published" / "failed" / "dry_run_pass" / "dry_run_fail"
    """
    log(f"\n{'='*60}")
    log(f"📄 処理中: {file_path.name}")

    for attempt in range(1, MAX_RETRIES + 2):
        log(f"📊 採点（{attempt}回目）...")
        score_result = score_article(file_path)

        total = score_result.get("total", 0)
        passed = score_result.get("pass", False) or total >= PASS_SCORE

        log(f"   スコア: {total}/70点 → {'✅ 合格' if passed else '❌ 不合格'}")

        if passed:
            # サムネイル生成（合格時に必ず実行）
            thumb_path = generate_thumbnail(file_path)

            if dry_run or not AUTO_PUBLISH:
                log(f"   ✅ {total}点で合格。draft: true のまま保持します（手動公開待ち）。")
                log(f"   💬 公開するには Claude Code で「公開して」と伝えてください。")
                return "ready"

            # 自動公開（AUTO_PUBLISH=Trueの場合のみ）
            set_draft_false(file_path)
            slug = score_result.get("slug", file_path.stem)
            push_files = [file_path]
            if thumb_path and thumb_path.exists():
                push_files.append(thumb_path)
            msg = f"publish: {score_result.get('title', slug)}（自動採点{total}点）\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
            git_push(push_files, msg)
            log(f"🎉 公開完了: {slug}")
            return "published" if attempt == 1 else "rewritten_published"

        # 不合格 → 書き直しへ
        if attempt <= MAX_RETRIES:
            log(f"📝 書き直し（{attempt}回目）...")
            success = rewrite_article(file_path, score_result)
            if not success:
                log("⚠️  書き直し失敗。次の試行をスキップします。")
                break
        else:
            log(f"⚠️  {MAX_RETRIES}回書き直しても合格せず。draft: trueのまま停止します。")
            log(f"   手動で確認してください: {file_path.name}")
            return "failed"

    return "failed"


def main():
    parser = argparse.ArgumentParser(description="ブログ記事自動公開パイプライン")
    parser.add_argument("--dry-run", action="store_true", help="生成・採点のみ（pushなし）")
    parser.add_argument("--score-only", action="store_true", help="既存draft記事を採点→公開判定のみ（生成しない）")
    parser.add_argument("--generate", action="store_true", help="記事生成も実行する")
    args = parser.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    log("🚀 自動公開パイプライン開始")

    # 記事生成（--generateオプション時のみ）
    if args.generate and not args.score_only:
        log("📝 記事生成中...")
        result = subprocess.run(
            [sys.executable, str(BLOG_DIR / "scripts" / "generate_blog_post.py"), "--weekly"],
            cwd=str(BLOG_DIR), capture_output=True, text=True
        )
        print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
        if result.returncode != 0:
            log(f"❌ 記事生成失敗: {result.stderr[-500:]}")

    # draft記事を取得
    drafts = find_new_drafts()
    if not drafts:
        log("✅ 処理対象のdraft記事はありません")
        return

    log(f"📋 draft記事 {len(drafts)}本を処理します")

    results = {"published": [], "rewritten_published": [], "ready": [], "failed": []}

    for file_path in drafts:
        status = process_article(file_path, dry_run=args.dry_run)
        results.get(status, results["failed"]).append(file_path.name)

    # サマリー
    log(f"\n{'='*60}")
    log("📊 パイプライン完了サマリー")
    log(f"   ✅ 合格・公開待ち（draft:true）: {len(results['ready'])}本")
    log(f"   🔄 書き直し後・合格・公開待ち: {len(results['rewritten_published'])}本")
    log(f"   ❌ 要手動確認（67点未達）: {len(results['failed'])}本")
    if results["ready"]:
        log("   📋 公開待ち記事（「公開して」で公開できます）:")
        for f in results["ready"]:
            log(f"      → {f}")
    if results["failed"]:
        log("   ⚠️  要確認記事:")
        for f in results["failed"]:
            log(f"      → {f}")


if __name__ == "__main__":
    main()
