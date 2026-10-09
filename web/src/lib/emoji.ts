// The emoji shortcodes the composer expands: `:smile:` becomes the emoji. The table is the API's
// (GET /emoji), read once per session and held here (#132): the app keeps no copy that could
// drift from the terminal's. Until it has been read, nothing expands and nothing is offered.

export interface Shortcode {
	name: string;
	emoji: string;
	keywords: string;
}

let table: readonly Shortcode[] = [];
let reading: Promise<void> | null = null;

/** The table as read, in the donor's order; empty until the API has answered. */
export function emojiTable(): readonly Shortcode[] {
	return table;
}

export function loadEmoji(codes: readonly Shortcode[]): void {
	table = codes;
}

/** Reads the table once; a failed read is forgotten, so the next caller asks again. */
export function readEmoji(fetch: () => Promise<Shortcode[]>): Promise<void> {
	if (table.length) return Promise.resolve();
	reading ??= fetch()
		.then(loadEmoji)
		.catch(() => {
			reading = null;
		});
	return reading;
}
