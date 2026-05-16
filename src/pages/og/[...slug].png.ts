import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const categoryConfig: Record<string, { bg: string; accent: string; emoji: string }> = {
  '副業実録':       { bg: '#f97316', accent: '#c2410c', emoji: '📝' },
  'AI活用':         { bg: '#6366f1', accent: '#4338ca', emoji: '🤖' },
  'FIRE設計':       { bg: '#ef4444', accent: '#b91c1c', emoji: '🔥' },
  'シングル父の日常': { bg: '#10b981', accent: '#047857', emoji: '👨‍👦' },
  '買ってよかった':  { bg: '#ec4899', accent: '#be185d', emoji: '🛒' },
};

const fontJpPath = fileURLToPath(new URL('../../../public/fonts/NotoSansJP-japanese-700.woff', import.meta.url));
const fontLatinPath = fileURLToPath(new URL('../../../public/fonts/NotoSansJP-latin-700.woff', import.meta.url));
const fontJpData = fs.readFileSync(fontJpPath);
const fontLatinData = fs.readFileSync(fontLatinPath);

export async function getStaticPaths() {
  const posts = await getCollection('blog', ({ data }) => !data.draft);
  return posts.map(post => ({ params: { slug: post.id } }));
}

function truncate(text: string, max: number) {
  return text.length > max ? text.slice(0, max) + '…' : text;
}

export const GET: APIRoute = async ({ params }) => {
  const { slug } = params as { slug: string };
  const posts = await getCollection('blog');
  const post = posts.find(p => p.id === slug);

  const title = post?.data.title ?? 'ひろとの副業実録';
  const category = post?.data.category ?? '副業実録';
  const cfg = categoryConfig[category] ?? { bg: '#1a1a1a', accent: '#333', emoji: '📄' };

  const svg = await satori(
    {
      type: 'div',
      props: {
        style: {
          width: '1200px',
          height: '630px',
          display: 'flex',
          flexDirection: 'column',
          background: `linear-gradient(135deg, ${cfg.bg} 0%, ${cfg.accent} 100%)`,
          padding: '60px',
          fontFamily: '"NotoSansJP"',
          position: 'relative',
        },
        children: [
          // カテゴリバッジ
          {
            type: 'div',
            props: {
              style: {
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                marginBottom: '40px',
              },
              children: [
                {
                  type: 'div',
                  props: {
                    style: {
                      background: 'rgba(255,255,255,0.25)',
                      borderRadius: '30px',
                      padding: '8px 24px',
                      fontSize: '28px',
                      color: '#fff',
                      fontWeight: 700,
                    },
                    children: `${cfg.emoji}  ${category}`,
                  },
                },
              ],
            },
          },
          // タイトル
          {
            type: 'div',
            props: {
              style: {
                flex: 1,
                display: 'flex',
                alignItems: 'center',
              },
              children: [
                {
                  type: 'div',
                  props: {
                    style: {
                      fontSize: title.length > 30 ? '48px' : '56px',
                      fontWeight: 700,
                      color: '#fff',
                      lineHeight: 1.4,
                      letterSpacing: '-0.01em',
                      textShadow: '0 2px 8px rgba(0,0,0,0.2)',
                    },
                    children: truncate(title, 50),
                  },
                },
              ],
            },
          },
          // フッター
          {
            type: 'div',
            props: {
              style: {
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                borderTop: '2px solid rgba(255,255,255,0.3)',
                paddingTop: '24px',
              },
              children: [
                {
                  type: 'div',
                  props: {
                    style: {
                      fontSize: '24px',
                      color: 'rgba(255,255,255,0.9)',
                      fontWeight: 700,
                    },
                    children: 'ひろとの副業実録',
                  },
                },
                {
                  type: 'div',
                  props: {
                    style: {
                      fontSize: '20px',
                      color: 'rgba(255,255,255,0.7)',
                    },
                    children: 'hiroto-fire.com',
                  },
                },
              ],
            },
          },
        ],
      },
    },
    {
      width: 1200,
      height: 630,
      fonts: [
        { name: 'NotoSansJP', data: fontJpData,    weight: 700, style: 'normal' },
        { name: 'NotoSansJP', data: fontLatinData, weight: 700, style: 'normal' },
      ],
    }
  );

  const resvg = new Resvg(svg, { fitTo: { mode: 'width', value: 1200 } });
  const png = resvg.render().asPng();

  return new Response(png, {
    headers: { 'Content-Type': 'image/png' },
  });
};
