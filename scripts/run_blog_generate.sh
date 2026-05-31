#!/bin/bash
# ブログ記事自動生成 → 採点 → 書き直し → 合格したら公開
set -euo pipefail

BLOG_DIR="/Users/hiroto/claud code/hiroto-fire-blog"
LOG_DIR="$BLOG_DIR/logs"
TS=$(date +%Y%m%d_%H%M%S)
PY=/usr/bin/python3

mkdir -p "$LOG_DIR"
cd "$BLOG_DIR"

echo "=============================="
echo "🚀 ブログ自動公開パイプライン開始: $(date)"
echo "=============================="

# 生成→採点→書き直し→公開をパイプラインで一括実行
PYTHONUNBUFFERED=1 \
  caffeinate -disu \
  "$PY" -u scripts/auto_publish_pipeline.py --generate \
  2>&1 | tee -a "$LOG_DIR/blog_pipeline_${TS}.log"

echo ""
echo "✅ パイプライン完了: $(date)"
