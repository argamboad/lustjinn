/**
 * Server-sent events, read from a fetch body. `EventSource` only does GET; the API's turns are
 * POSTs that answer as a stream, so the stream is read by hand: bytes to lines, lines to events.
 * Pure, so it is unit-tested without a network.
 */

export interface SseEvent {
	event: string | null;
	data: string;
}

/** Feeds text in any chunking and yields complete events; the tail is kept between calls. */
export class SseParser {
	private buffer = '';

	push(chunk: string): SseEvent[] {
		this.buffer += chunk.replace(/\r\n/g, '\n');
		const events: SseEvent[] = [];
		let at: number;
		while ((at = this.buffer.indexOf('\n\n')) >= 0) {
			const block = this.buffer.slice(0, at);
			this.buffer = this.buffer.slice(at + 2);
			const parsed = parseBlock(block);
			if (parsed) events.push(parsed);
		}
		return events;
	}
}

function parseBlock(block: string): SseEvent | null {
	let event: string | null = null;
	const data: string[] = [];
	for (const line of block.split('\n')) {
		if (!line || line.startsWith(':')) continue; // a comment, or the keep-alive
		const colon = line.indexOf(':');
		const field = colon < 0 ? line : line.slice(0, colon);
		let value = colon < 0 ? '' : line.slice(colon + 1);
		if (value.startsWith(' ')) value = value.slice(1);
		if (field === 'event') event = value;
		else if (field === 'data') data.push(value);
	}
	if (data.length === 0 && event === null) return null;
	return { event, data: data.join('\n') };
}

/** Reads a whole response body as events, calling `on` for each as it arrives. */
export async function readEvents(
	body: ReadableStream<Uint8Array>,
	on: (event: SseEvent) => void
): Promise<void> {
	const reader = body.getReader();
	const decoder = new TextDecoder();
	const parser = new SseParser();
	for (;;) {
		const { value, done } = await reader.read();
		if (done) break;
		for (const event of parser.push(decoder.decode(value, { stream: true }))) on(event);
	}
	for (const event of parser.push(decoder.decode())) on(event);
}
