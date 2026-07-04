import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const blogDir = path.join(projectRoot, 'src/content/blog');
const redirectsBasePath = path.join(projectRoot, 'public/_redirects.base');
const redirectsOutPath = path.join(projectRoot, 'public/_redirects');

const protectedRoots = new Set([
  'about',
  'blog',
  'category',
  'contact',
  'katteyokatta',
  'privacy',
  'profile',
  'recommended',
  'recommended-books',
  'recommended-services',
  'roadmap',
  't',
  'thanks',
  'x',
  'xp',
]);

function parseFrontmatter(source) {
  const match = source.match(/^---\n([\s\S]*?)\n---/);
  const frontmatter = match?.[1] ?? '';
  const slug = frontmatter.match(/^slug:\s*"([^"]+)"/m)?.[1];
  const permalink = frontmatter.match(/^permalink:\s*"([^"]+)"/m)?.[1];
  return { slug, permalink };
}

function normalizeSource(urlPath) {
  if (!urlPath.startsWith('/')) return `/${urlPath}`;
  return urlPath;
}

async function main() {
  const base = await fs.readFile(redirectsBasePath, 'utf8');
  const files = (await fs.readdir(blogDir))
    .filter((file) => file.endsWith('.md'))
    .sort();

  const generated = new Set();

  for (const file of files) {
    const fullPath = path.join(blogDir, file);
    const source = await fs.readFile(fullPath, 'utf8');
    const { slug } = parseFrontmatter(source);
    const id = path.basename(file, '.md');
    const canonicalSlug = slug ?? id;
    const target = `/blog/${canonicalSlug}/`;

    const candidates = new Set([id]);
    if (slug && slug !== id) candidates.add(slug);

    for (const candidate of candidates) {
      if (protectedRoots.has(candidate)) continue;
      for (const sourcePath of [`/${candidate}`, `/${candidate}/`]) {
        if (normalizeSource(target) === sourcePath) continue;
        generated.add(`${sourcePath} ${target} 301`);
      }
    }
  }

  const output = [
    base.trimEnd(),
    '',
    '# Generated legacy blog redirects.',
    ...Array.from(generated).sort(),
    '',
  ].join('\n');

  await fs.writeFile(redirectsOutPath, output, 'utf8');
  console.log(`[redirects] Wrote ${generated.size} generated redirects to public/_redirects`);
}

main().catch((error) => {
  console.error('[redirects] Failed to generate redirects');
  console.error(error);
  process.exit(1);
});
