#!/usr/bin/env node

import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BLOG_DIR = path.resolve(__dirname, '..');
const ENV_PATH = path.join(BLOG_DIR, '.env');
const INDEXNOW_KEY_FILE_PATTERN = /^[a-f0-9]{32}\.txt$/i;

function parseEnvLine(line) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith('#')) return null;

  const separatorIndex = trimmed.indexOf('=');
  if (separatorIndex === -1) return null;

  const key = trimmed.slice(0, separatorIndex).trim();
  if (!key) return null;

  let value = trimmed.slice(separatorIndex + 1).trim();
  value = value.replace(/^['"]|['"]$/g, '');

  return { key, value };
}

export async function loadEnvFile() {
  try {
    const content = await readFile(ENV_PATH, 'utf8');
    for (const line of content.split('\n')) {
      const parsed = parseEnvLine(line);
      if (!parsed) continue;
      if (process.env[parsed.key] === undefined) {
        process.env[parsed.key] = parsed.value;
      }
    }
  } catch (error) {
    if (error.code !== 'ENOENT') {
      throw error;
    }
  }
}

export async function findExistingIndexNowKey(searchDir) {
  try {
    const entries = await readdir(searchDir, { withFileTypes: true });
    const match = entries.find((entry) => entry.isFile() && INDEXNOW_KEY_FILE_PATTERN.test(entry.name));
    return match ? match.name.replace(/\.txt$/i, '') : null;
  } catch (error) {
    if (error.code === 'ENOENT') {
      return null;
    }
    throw error;
  }
}
