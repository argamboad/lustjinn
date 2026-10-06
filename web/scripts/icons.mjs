// Renders the icon set from brand/logo.svg: the manifest icons, a maskable one with the safe
// zone respected, the Apple touch icon and a favicon. Run once after the logo changes:
//
//     node scripts/icons.mjs
//
// The outputs are committed, so a build needs no rasteriser.

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, '..', '..', 'brand', 'logo.svg');
const out = join(here, '..', 'static', 'icons');
const navy = { r: 10, g: 13, b: 27, alpha: 1 };

await mkdir(out, { recursive: true });
const svg = await readFile(source);

async function square(size, name) {
	await sharp(svg, { density: 300 }).resize(size, size).png().toFile(join(out, name));
}

// Maskable: the platform may crop to a circle or a squircle, so the mark sits in the inner 80%.
async function maskable(size, name) {
	const inner = Math.round(size * 0.8);
	const mark = await sharp(svg, { density: 300 }).resize(inner, inner).png().toBuffer();
	await sharp({ create: { width: size, height: size, channels: 4, background: navy } })
		.composite([{ input: mark, gravity: 'centre' }])
		.png()
		.toFile(join(out, name));
}

await square(192, 'icon-192.png');
await square(512, 'icon-512.png');
await maskable(512, 'maskable-512.png');
await square(180, 'apple-touch-icon.png');
await square(32, 'favicon-32.png');
await writeFile(join(out, 'favicon.svg'), svg);
console.log('icons written to', out);
