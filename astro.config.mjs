// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import rehypeWrapTables from './scripts/rehype-wrap-tables.mjs';

// https://astro.build/config
export default defineConfig({
  site: 'https://hiroto-fire.com',
  integrations: [
    sitemap(),
  ],
  output: 'static',
  markdown: {
    rehypePlugins: [rehypeWrapTables],
  },
});
