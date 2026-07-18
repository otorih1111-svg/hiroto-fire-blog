// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import rehypeWrapTables from './scripts/rehype-wrap-tables.mjs';

// https://astro.build/config
export default defineConfig({
  site: 'https://hiroto-fire.com',
  server: {
    port: Number(process.env.PORT) || 4321,
  },
  integrations: [
    sitemap({
      // noindexページはサイトマップに載せない（GSCの「noindexタグによって除外」警告対策）
      filter: (page) => !page.includes('/lp/') && !page.includes('/thanks/'),
    }),
  ],
  output: 'static',
  markdown: {
    rehypePlugins: [rehypeWrapTables],
  },
});
