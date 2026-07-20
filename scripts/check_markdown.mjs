/**
 * 記事が「書いたとおりに描画されない」書き方をしていないか、ビルド前に検出する。
 *
 * 主目的は太字（**）の閉じ忘れ。日本語だと
 *   〜です。**強調したい文。**続きの文
 * のように閉じ ** の直後が日本語文字だと、CommonMarkのright-flanking条件を
 * 満たさず強調にならず、** がそのまま本文に表示されてしまう。
 * 英語は単語間に空白があるため起きにくく、日本語特有で気づきにくい。
 *
 * 判定は自前のルールではなく、Astroが実際に使うmarkdownレンダラーに通して
 * 「出力HTMLに ** が残るか」で行う。本番の描画と必ず一致する。
 *
 * 使い方:
 *   node scripts/check_markdown.mjs          # 問題があればexit 1でビルドを止める
 *   node scripts/check_markdown.mjs --warn   # 検出しても落とさない（棚卸し用）
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createMarkdownProcessor } from '@astrojs/markdown-remark';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const blogDir = path.join(projectRoot, 'src/content/blog');

const warnOnly = process.argv.includes('--warn');

/** frontmatterを外し、本文の開始行番号も返す */
function splitFrontmatter(src) {
  if (!src.startsWith('---')) return { body: src, offsetLines: 0 };
  const end = src.indexOf('\n---', 3);
  if (end === -1) return { body: src, offsetLines: 0 };
  const head = src.slice(0, end + 4);
  return { body: src.slice(end + 4), offsetLines: head.split('\n').length - 1 };
}

/**
 * 壊れている行だけを特定する。
 * 行ごとにレンダリングし直し、その行単体で ** が残るものだけを返す。
 * （正常な太字を含む行を巻き込んで報告しないため）
 */
async function locateInSource(processor, body, offsetLines) {
  const lines = body.split('\n');
  const found = [];
  let inCode = false;
  for (let idx = 0; idx < lines.length; idx++) {
    const line = lines[idx];
    if (/^\s*```/.test(line)) inCode = !inCode;
    if (inCode || !line.includes('**')) continue;

    const { code } = await processor.render(line);
    const html = code.replace(/<pre[\s\S]*?<\/pre>/g, '').replace(/<code[\s\S]*?<\/code>/g, '');
    if (!html.includes('**')) continue;

    found.push({ line: idx + 1 + offsetLines, text: line.trim().slice(0, 78) });
  }
  return found;
}

const processor = await createMarkdownProcessor({});
const files = (await fs.readdir(blogDir)).filter((f) => f.endsWith('.md')).sort();

let total = 0;
const report = [];

for (const file of files) {
  const src = await fs.readFile(path.join(blogDir, file), 'utf8');
  const { body, offsetLines } = splitFrontmatter(src);

  const { code } = await processor.render(body);
  // コードブロック内の ** は正常なので除外して数える
  const html = code.replace(/<pre[\s\S]*?<\/pre>/g, '').replace(/<code[\s\S]*?<\/code>/g, '');
  const leftover = (html.match(/\*\*/g) || []).length;
  if (leftover === 0) continue;

  total += leftover;
  const spots = await locateInSource(processor, body, offsetLines);
  report.push(`  ${file}  （描画に ** が ${leftover}個 残ります）`);
  for (const s of spots) report.push(`      ${file}:${s.line}\n        ${s.text}`);
}

if (total === 0) {
  console.log(`[check-markdown] OK: ${files.length}記事すべて、太字は正しく描画されます`);
  process.exit(0);
}

console.error(`\n[check-markdown] 太字が描画されない箇所があります（${total}個の ** が本文に露出）\n`);
console.error(report.join('\n'));
console.error(`
  閉じ ** の直後が日本語文字だと強調になりません。どちらかで直せます。
    1) 段落を分ける          〜です。**強調する文。**␣␣←ここで改行を2つ
    2) 太字を文末まで伸ばす   **〜です。続きの文も含めて閉じる。**
`);

process.exit(warnOnly ? 0 : 1);
