# AGENTS.md - hiroto-fire-blog 用運用ルール

## 基本

- このリポジトリでは、記事作成・リライト・公開後確認までを一連の作業として扱う
- `pushして終わり` にしない
- 体験談・感情はひろとの実体験を優先し、知識パートは検索意図と読者満足を優先する

## 記事作成時の必須ルール

記事を作成・更新して `push` する前に、以下を必ず完了させる。

1. サムネイル（OGP画像）を作成する
   - 保存先: `/public/images/thumbnails/[slug].png`
   - frontmatter の `ogImage` に正しいパスを入れる
2. 本文用の図解・画像を最低1枚入れる
   - 保存先: `/public/images/articles/[slug]/`
   - 比較表、手順図、判断フロー、Before/After など、記事内容に合う形式にする
3. 可能ならキャラクター画像も入れる
   - 感情が動く場面、補足説明、吹き出し用途を優先する
4. 画像なしで `push` しない

## 既存記事リライト時の必須フロー

過去記事は KW を十分に確認せず書かれているものが多い。
そのため、既存記事のリライトでは「文章を整える前に、先に KW と検索意図を確認する」ことを必須とする。

### 手順

1. 対象記事の現タイトル・現見出し・現導線を確認する
2. Search Console で表示クエリ・表示回数・CTR・掲載順位を確認する
3. その記事で狙うメイン KW を1つ決める
4. 必要に応じてサブ KW を2〜3つ決める
5. 記事の役割を整理する
   - 集客記事
   - 比較記事
   - 体験談記事
   - ハブ記事
   - 成約記事
6. その役割に合わせて、タイトル・description・リード文・見出し・CTA を調整する

### 注意

- KW 確認なしで本文から先に直し始めない
- Search Console で出ているクエリと、本来狙いたい KW がズレている場合は、そのズレを先に整理する
- 順位が高いのにクリックされていない記事は、本文より先にタイトル・description・冒頭を見直す
- 表示も順位も弱い記事は、タイトルだけでなく構成や検索意図そのものを見直す

リライトは「文章をきれいにする作業」ではなく、
「検索意図・記事の役割・導線を今の基準に合わせ直す作業」として行う。

## 体験談記事のKW運用ルール

- 体験談記事は「タイトル・description は KW に寄せる、本文の体験軸は守る」を基本とする
- ボリュームが小さい KW でも、検索意図と体験が一致しているなら採用してよい
- 集客記事・比較記事・まとめ記事ほど、ボリューム100以上を強く意識する
- 体験談・感情系・信頼構築記事は、流入数だけでなく回遊・信頼・成約補助も評価軸に入れる

## 公開後の自動フロー

- `main` に push すると GitHub Actions `Google Publish Signals After Deploy` が自動実行される
- 公開後は以下が自動で流れる前提で運用する
  - build
  - Cloudflare 反映待ち
  - IndexNow
  - Google publish signals

## GitHub Actions / Google publish signals

### 前提

- GitHub Actions secret 名は `GOOGLE_SERVICE_ACCOUNT_JSON`
- secret には **ファイルパスではなく** `google-credentials.json` の **JSON本文そのもの** を入れる
- サービスアカウント `hiroto-indexing@drm1-498112.iam.gserviceaccount.com` が Search Console 側で対象プロパティにアクセスできる状態にしておく

### 公開後の確認ルール

Claude Code / Codex は `pushして終わり` にせず、以下まで確認する。

1. GitHub Actions の最新実行 `Google Publish Signals After Deploy` が `success` か確認
2. ジョブ `publish-signals` の中に `Send Google publish signals` があり、そこまで成功しているか確認

### 失敗時の確認ポイント

- `GOOGLE_SERVICE_ACCOUNT_JSON` にパスを書いてしまっていないか
- サービスアカウント権限が不足していないか
- workflow 側の依存関係や認証処理が壊れていないか

