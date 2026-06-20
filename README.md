# hiroto-fire-blog

Astro製のブログです。  
デプロイ時のインデックス補助として、以下を自動で回せるようにしています。

- `IndexNow` 送信（Bing系向け）
- `Search Console API` で `sitemap-index.xml` を再送信
- `sitemap.xml` の存在確認
- 今回公開したURLのログ出力
- 更新URLの indexability チェック
- `Search Console` に手動申請すべきURL一覧の出力

## 重要な前提

Google には、通常のブログ記事を対象にした一般向けの「即インデックスAPI」はありません。  
そのためこのリポジトリでは、Google向けには次の3つを自動化しています。

- sitemap の再送信
- 更新URLの公開健全性チェック
- 手動URL検査の優先候補ログ出力

## 使い方

### 通常ビルド

```bash
npm run build
```

`INDEXNOW_KEY` があれば、`prebuild` で `public/<KEY>.txt` を自動生成します。  
キー未設定ならスキップします。

### デプロイ後の通知ログ出力

```bash
npm run seo:notify
```

やること:

- `dist/sitemap-index.xml` / `dist/sitemap-0.xml` を確認
- 直近コミット差分から公開URLを抽出
- `IndexNow` へ送信
- `logs/indexing/*.json` に結果を保存
- `logs/indexing/*-search-console-candidates.txt` に申請候補URLを書き出し

### Google向けの公開シグナルも送る

```bash
npm run seo:google
```

やること:

- `Search Console API` で `https://hiroto-fire.com/sitemap-index.xml` を再送信
- `logs/indexing/latest-indexing.json` から更新URLを取得
- 更新URLの `200 / noindex / sitemap / canonical` を確認
- `logs/indexing/*-google-publish.json` に結果を保存

### Cloudflareデプロイ完了待ち込みで通知したいとき

```bash
npm run seo:notify:live
```

`https://hiroto-fire.com/<INDEXNOW_KEY>.txt` が実際に見えるようになるまで待ってから、`IndexNow` に送信します。

### 全公開記事を対象に一覧を出したいとき

```bash
npm run seo:notify:all
```

## おすすめ運用

### 1. ビルド

```bash
npm run build
```

### 2. デプロイ完了後に通知

```bash
npm run seo:notify
```

### 3. Google向けシグナルを送る

```bash
npm run seo:google
```

### 4. 申請候補を Search Console で手動送信

最新の候補一覧:

```bash
cat logs/indexing/latest-search-console-candidates.txt
```

詳細ログ:

```bash
cat logs/indexing/latest-indexing.json
cat logs/indexing/latest-google-publish.json
```

## 環境変数

### `INDEXNOW_KEY`

`IndexNow` のキー。設定すると `public/<KEY>.txt` が生成されます。

`.env` に書いておけば、`build` / `seo:notify` 実行時に自動で読み込みます。
すでに `public/<KEY>.txt` を置いている場合は、そのキーを自動で使います。

例:

```bash
cp .env.example .env
```

```bash
INDEXNOW_KEY=your-indexnow-key
```

### `INDEXING_BASE_REF`
### `INDEXING_HEAD_REF`

`seo:notify` で差分比較に使うGit ref。  
デフォルトは `HEAD~1` と `HEAD` です。

例:

```bash
INDEXING_BASE_REF=origin/main~3 INDEXING_HEAD_REF=HEAD npm run seo:notify
```

## package scripts

```bash
npm run build
npm run build:seo
npm run seo:notify
npm run seo:notify:live
npm run seo:notify:all
npm run seo:google
npm run seo:google:dry
npm run seo:publish
```

`build:seo` は `build` のあとに `seo:notify` まで続けて回します。  
ただし本当に「デプロイ完了後」に通知したい場合は、ホスティング側のデプロイ完了フックや手動実行で `seo:notify` を呼ぶ運用がいちばん確実です。

`seo:publish` は `IndexNow` 通知のあとに `Search Console API` で sitemap を再送信します。

## GitHub Actions

Cloudflare Pages の自動デプロイ後に `IndexNow` と Google向けシグナル送信を流したい場合は、同梱の workflow を使えます。

- ファイル: `.github/workflows/indexnow-after-cloudflare.yml`
- 対象: `main` への push
- 挙動:
  - ビルド
  - 本番URL上の `/<INDEXNOW_KEY>.txt` 公開を待機
  - `IndexNow` 送信
  - `Search Console API` で sitemap を再送信
  - 更新URLの indexability をチェック
  - ログを artifact 保存

`public/<KEY>.txt` を repo に置いていれば `IndexNow` 側は GitHub Secret なしで動きます。  
Google側も自動化したい場合は、GitHub Secret `GOOGLE_SERVICE_ACCOUNT_JSON` にサービスアカウントJSON全文を設定してください。未設定でも workflow 自体は失敗せず、Google送信だけスキップします。
