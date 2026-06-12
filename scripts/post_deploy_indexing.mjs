#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile, access } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { findExistingIndexNowKey, loadEnvFile } from './load_env.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BLOG_DIR = path.resolve(__dirname, '..');
const CONTENT_DIR = path.join(BLOG_DIR, 'src', 'content', 'blog');
const DIST_DIR = path.join(BLOG_DIR, 'dist');
const LOG_DIR = path.join(BLOG_DIR, 'logs', 'indexing');
const PUBLIC_DIR = path.join(BLOG_DIR, 'public');
const SITE = 'https://hiroto-fire.com';

const STATIC_ROUTE_MAP = new Map([
  ['src/pages/index.astro', '/'],
  ['src/pages/recommended-services.astro', '/recommended-services/'],
  ['src/pages/recommended-books.astro', '/recommended-books/'],
  ['src/pages/katteyokatta.astro', '/katteyokatta/'],
  ['src/pages/contact.astro', '/contact/'],
  ['src/pages/profile.astro', '/profile/'],
]);

const EXCLUDED_ROUTE_PREFIXES = [
  '/privacy/',
  '/blog/',
  '/category/',
  '/about/',
];

await loadEnvFile();

function parseArgs(argv) {
  const options = {
    all: false,
    base: process.env.INDEXING_BASE_REF || 'HEAD~1',
    head: process.env.INDEXING_HEAD_REF || 'HEAD',
    waitLive: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--all') {
      options.all = true;
    } else if (arg === '--wait-live') {
      options.waitLive = true;
    } else if (arg === '--base' && argv[i + 1]) {
      options.base = argv[i + 1];
      i += 1;
    } else if (arg === '--head' && argv[i + 1]) {
      options.head = argv[i + 1];
      i += 1;
    }
  }

  return options;
}

function log(message) {
  console.log(`[indexing] ${message}`);
}

function ensureTrailingSlash(urlPath) {
  if (urlPath === '/') return urlPath;
  return urlPath.endsWith('/') ? urlPath : `${urlPath}/`;
}

function toSiteUrl(urlPath) {
  return new URL(ensureTrailingSlash(urlPath), SITE).toString();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseFrontmatter(content) {
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return {};

  const data = {};
  for (const line of match[1].split('\n')) {
    const idx = line.indexOf(':');
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    const rawValue = line.slice(idx + 1).trim();
    const unquoted = rawValue.replace(/^['"]|['"]$/g, '');
    data[key] = unquoted;
  }
  return data;
}

async function fileExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function getPublishedBlogUrlFromSource(filePath) {
  const content = await readFile(filePath, 'utf8');
  const frontmatter = parseFrontmatter(content);
  const draft = String(frontmatter.draft || 'false').toLowerCase() === 'true';
  if (draft) return null;

  const slug = frontmatter.slug || path.basename(filePath, '.md');
  return toSiteUrl(`/blog/${slug}/`);
}

function getChangedFiles(baseRef, headRef) {
  try {
    const output = execFileSync(
      'git',
      ['diff', '--name-only', '--diff-filter=ACMRTUXB', baseRef, headRef],
      { cwd: BLOG_DIR, encoding: 'utf8' }
    );
    return output
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
  } catch (error) {
    log(`Could not diff ${baseRef}..${headRef}. Falling back to all published blog posts.`);
    return [];
  }
}

async function collectChangedPublicUrls(options) {
  const changedFiles = options.all ? [] : getChangedFiles(options.base, options.head);
  const updatedUrls = new Set();
  const candidateUrls = new Set();

  if (options.all || changedFiles.length === 0) {
    const blogEntries = execFileSync('find', [CONTENT_DIR, '-maxdepth', '1', '-type', 'f', '-name', '*.md'], {
      cwd: BLOG_DIR,
      encoding: 'utf8',
    })
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);

    for (const filePath of blogEntries) {
      const url = await getPublishedBlogUrlFromSource(filePath);
      if (!url) continue;
      updatedUrls.add(url);
      candidateUrls.add(url);
    }

    return { changedFiles, updatedUrls: [...updatedUrls], candidateUrls: [...candidateUrls] };
  }

  for (const changedFile of changedFiles) {
    const absolutePath = path.join(BLOG_DIR, changedFile);

    if (changedFile.startsWith('src/content/blog/') && changedFile.endsWith('.md')) {
      if (!(await fileExists(absolutePath))) continue;
      const url = await getPublishedBlogUrlFromSource(absolutePath);
      if (!url) continue;
      updatedUrls.add(url);
      candidateUrls.add(url);
      continue;
    }

    const mappedRoute = STATIC_ROUTE_MAP.get(changedFile);
    if (mappedRoute) {
      const routeUrl = toSiteUrl(mappedRoute);
      updatedUrls.add(routeUrl);
      if (!EXCLUDED_ROUTE_PREFIXES.some((prefix) => mappedRoute.startsWith(prefix))) {
        candidateUrls.add(routeUrl);
      }
    }
  }

  return { changedFiles, updatedUrls: [...updatedUrls], candidateUrls: [...candidateUrls] };
}

async function verifySitemaps() {
  const sitemapIndex = path.join(DIST_DIR, 'sitemap-index.xml');
  const sitemapZero = path.join(DIST_DIR, 'sitemap-0.xml');
  const found = [];

  if (await fileExists(sitemapIndex)) found.push(sitemapIndex);
  if (await fileExists(sitemapZero)) found.push(sitemapZero);

  if (found.length === 0) {
    throw new Error('No sitemap files found in dist/. Run `npm run build` first.');
  }

  return found.map((entry) => path.relative(BLOG_DIR, entry));
}

async function verifyIndexNowKeyFile(key) {
  const keyFileName = `${key}.txt`;
  const distKeyFile = path.join(DIST_DIR, keyFileName);
  if (!(await fileExists(distKeyFile))) {
    return {
      ok: false,
      reason: `Missing dist/${keyFileName}. Run \`npm run build\` with INDEXNOW_KEY set.`,
    };
  }

  const content = (await readFile(distKeyFile, 'utf8')).trim();
  if (content !== key) {
    return {
      ok: false,
      reason: `dist/${keyFileName} does not contain INDEXNOW_KEY.`,
    };
  }

  return {
    ok: true,
    keyLocation: `${SITE}/${keyFileName}`,
  };
}

async function waitForLiveKeyFile(keyLocation, key) {
  const timeoutMs = Number(process.env.INDEXNOW_LIVE_TIMEOUT_MS || 600000);
  const intervalMs = Number(process.env.INDEXNOW_LIVE_INTERVAL_MS || 15000);
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(keyLocation, {
        headers: { 'cache-control': 'no-cache' },
      });
      const body = (await response.text()).trim();

      if (response.ok && body === key) {
        return {
          ok: true,
          waitedMs: timeoutMs - Math.max(deadline - Date.now(), 0),
        };
      }

      log(`Waiting for live key file. status=${response.status}`);
    } catch (error) {
      log(`Waiting for live key file. ${error.message}`);
    }

    await sleep(intervalMs);
  }

  return {
    ok: false,
    reason: `Timed out waiting for ${keyLocation} to become available.`,
  };
}

async function submitIndexNow(urls, options) {
  const key =
    process.env.INDEXNOW_KEY?.trim() ||
    (await findExistingIndexNowKey(PUBLIC_DIR)) ||
    (await findExistingIndexNowKey(DIST_DIR));
  if (!key) {
    return { enabled: false, submitted: 0, reason: 'INDEXNOW_KEY is not set and no public key file was found.' };
  }

  if (urls.length === 0) {
    return { enabled: true, submitted: 0, reason: 'No updated public URLs to submit.' };
  }

  const keyFile = await verifyIndexNowKeyFile(key);
  if (!keyFile.ok) {
    return { enabled: true, submitted: 0, reason: keyFile.reason };
  }

  if (options.waitLive) {
    const liveKeyFile = await waitForLiveKeyFile(keyFile.keyLocation, key);
    if (!liveKeyFile.ok) {
      return { enabled: true, submitted: 0, reason: liveKeyFile.reason };
    }
  }

  const endpoint = process.env.INDEXNOW_ENDPOINT || 'https://api.indexnow.org/indexnow';
  const payload = {
    host: new URL(SITE).host,
    key,
    keyLocation: keyFile.keyLocation,
    urlList: urls,
  };

  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'content-type': 'application/json; charset=utf-8' },
    body: JSON.stringify(payload),
  });

  const body = await response.text();
  return {
    enabled: true,
    submitted: urls.length,
    status: response.status,
    ok: response.ok,
    endpoint,
    keyLocation: keyFile.keyLocation,
    waitedForLiveDeploy: options.waitLive,
    body: body.slice(0, 500),
  };
}

async function writeLogs(payload) {
  await mkdir(LOG_DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const jsonPath = path.join(LOG_DIR, `${stamp}-indexing.json`);
  const txtPath = path.join(LOG_DIR, `${stamp}-search-console-candidates.txt`);

  await writeFile(jsonPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  await writeFile(txtPath, `${payload.searchConsoleCandidates.join('\n')}\n`, 'utf8');

  return {
    json: path.relative(BLOG_DIR, jsonPath),
    txt: path.relative(BLOG_DIR, txtPath),
  };
}

const options = parseArgs(process.argv.slice(2));

try {
  const sitemapFiles = await verifySitemaps();
  const { changedFiles, updatedUrls, candidateUrls } = await collectChangedPublicUrls(options);

  const payload = {
    generatedAt: new Date().toISOString(),
    site: SITE,
    mode: options.all ? 'all' : 'diff',
    comparedRefs: options.all ? null : { base: options.base, head: options.head },
    sitemapFiles,
    changedFiles,
    updatedUrls,
    searchConsoleCandidates: candidateUrls,
  };

  payload.indexNow = await submitIndexNow(updatedUrls, options);

  const logs = await writeLogs(payload);
  payload.logFiles = logs;

  await writeFile(path.join(LOG_DIR, 'latest-indexing.json'), `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  await writeFile(
    path.join(LOG_DIR, 'latest-search-console-candidates.txt'),
    `${candidateUrls.join('\n')}\n`,
    'utf8'
  );

  log(`Verified sitemap files: ${sitemapFiles.join(', ')}`);
  log(`Updated public URLs: ${updatedUrls.length}`);
  log(`Search Console candidates: ${candidateUrls.length}`);
  if (payload.indexNow.enabled) {
    if (payload.indexNow.ok) {
      log(`IndexNow submitted ${payload.indexNow.submitted} URLs.`);
    } else {
      log(`IndexNow skipped/failed: ${payload.indexNow.reason || payload.indexNow.body || payload.indexNow.status}`);
    }
  } else {
    log(payload.indexNow.reason);
  }
  log(`Wrote log: ${logs.json}`);
  log(`Wrote Search Console candidate list: ${logs.txt}`);
} catch (error) {
  console.error(`[indexing] ${error.message}`);
  process.exit(1);
}
