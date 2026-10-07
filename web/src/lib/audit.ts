/** Reads the audit line kept with each reply — `character 2360 · world 417 · history 32 (1
 * dropped) · total 5278/6000` — into layers a screen can draw as bars. */

export interface Layer {
	name: string;
	tokens: number;
	dropped: number;
}

export interface Context {
	layers: Layer[];
	total: number;
	budget: number | null;
}

const LAYER = /^(\w+) (\d+)(?: \((\d+) dropped\))?$/;
const TOTAL = /^total (\d+)(?:\/(\d+))?$/;

export function parseContext(line: string | null | undefined): Context | null {
	if (!line) return null;
	const layers: Layer[] = [];
	let total = 0;
	let budget: number | null = null;
	for (const part of line.split(' · ')) {
		const t = TOTAL.exec(part.trim());
		if (t) {
			total = Number(t[1]);
			budget = t[2] ? Number(t[2]) : null;
			continue;
		}
		const l = LAYER.exec(part.trim());
		if (l) layers.push({ name: l[1], tokens: Number(l[2]), dropped: l[3] ? Number(l[3]) : 0 });
	}
	if (layers.length === 0 && total === 0) return null;
	return { layers, total, budget };
}
