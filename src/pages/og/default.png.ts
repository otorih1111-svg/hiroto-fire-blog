import type { APIRoute } from 'astro';
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const fontJpPath = fileURLToPath(new URL('../../../public/fonts/NotoSansJP-japanese-700.woff', import.meta.url));
const fontLatinPath = fileURLToPath(new URL('../../../public/fonts/NotoSansJP-latin-700.woff', import.meta.url));
const fontJpData = fs.readFileSync(fontJpPath);
const fontLatinData = fs.readFileSync(fontLatinPath);

export const GET: APIRoute = async () => {
  const svg = await satori(
    {
      type: 'div',
      props: {
        style: {
          width: '1200px',
          height: '630px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%)',
          fontFamily: '"NotoSansJP"',
        },
        children: [
          {
            type: 'div',
            props: {
              style: { fontSize: '80px', marginBottom: '24px' },
              children: '👨‍👦',
            },
          },
          {
            type: 'div',
            props: {
              style: {
                fontSize: '52px',
                fontWeight: 700,
                color: '#fff',
                marginBottom: '16px',
              },
              children: 'ひろとの副業実録',
            },
          },
          {
            type: 'div',
            props: {
              style: {
                fontSize: '28px',
                color: 'rgba(255,255,255,0.65)',
              },
              children: 'シングル父がAIと副業でFIREを目指す過程',
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
