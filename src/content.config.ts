import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const blog = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/blog' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    category: z.enum(['副業実録', 'AI活用', 'FIRE設計', 'シングル父の日常', '買ってよかった']),
    tags: z.array(z.string()).default([]),
    draft: z.boolean().default(false),
    affiliate: z.boolean().default(false),
    image: z.string().optional(),
  }),
});

export const collections = { blog };
