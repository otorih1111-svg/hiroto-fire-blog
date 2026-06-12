#!/usr/bin/env node

import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { findExistingIndexNowKey, loadEnvFile } from './load_env.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BLOG_DIR = path.resolve(__dirname, '..');
const PUBLIC_DIR = path.join(BLOG_DIR, 'public');

await loadEnvFile();

const key = process.env.INDEXNOW_KEY?.trim() || (await findExistingIndexNowKey(PUBLIC_DIR));

if (!key) {
  console.log('[indexnow] INDEXNOW_KEY is not set. Skipping key file generation.');
  process.exit(0);
}

const keyFilePath = path.join(PUBLIC_DIR, `${key}.txt`);

await mkdir(PUBLIC_DIR, { recursive: true });
await writeFile(keyFilePath, `${key}\n`, 'utf8');

console.log(`[indexnow] Wrote key file: public/${key}.txt`);
