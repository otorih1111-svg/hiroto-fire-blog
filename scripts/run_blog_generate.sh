#!/bin/bash
# ブログ記事自動生成 → git push → Cloudflare自動デプロイ
set -euo pipefail

BLOG_DIR="/Users/hiroto/claud code/hiroto-fire-blog"
LOG_DIR="$BLOG_DIR/logs"
TS=$(date +%Y%m%d_%H%M%S)
PY=/usr/bin/python3

mkdir -p "$LOG_DIR"
cd "$BLOG_DIR"

echo "=============================="
echo "🚀 ブログ自動生成開始: $(date)"
echo "=============================="

# 記事生成（週次バッチ：3記事）
PYTHONUNBUFFERED=1 \
  caffeinate -disu \
  "$PY" -u scripts/generate_blog_post.py --weekly \
  2>&1 | tee -a "$LOG_DIR/blog_generate_${TS}.log"

# git push（Cloudflare Pages が自動デプロイ）
echo ""
echo "📦 GitHub にプッシュ中..."
git add src/content/blog/
git diff --cached --quiet && echo "⚠ 新規記事なし・スキップ" && exit 0

git commit -m "auto: ブログ記事自動生成 $(date +%Y-%m-%d)"
git push origin main

echo ""
echo "✅ 完了: $(date)"
echo "   Cloudflare Pages が自動デプロイします"
