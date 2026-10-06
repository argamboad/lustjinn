/** Short notices stacked at the bottom of the screen: a refusal, a one-time warning, a result. */

export type ToastTone = 'info' | 'warn' | 'danger' | 'ok';

export interface Toast {
	id: number;
	tone: ToastTone;
	title: string;
	detail?: string;
	/** Milliseconds before it goes by itself; 0 keeps it until dismissed. */
	ttl: number;
}

class Toasts {
	list = $state<Toast[]>([]);
	private next = 1;

	show(tone: ToastTone, title: string, detail?: string, ttl = 6000): number {
		const id = this.next++;
		this.list = [...this.list, { id, tone, title, detail, ttl }];
		if (ttl > 0) setTimeout(() => this.dismiss(id), ttl);
		return id;
	}

	dismiss(id: number) {
		this.list = this.list.filter((t) => t.id !== id);
	}
}

export const toasts = new Toasts();
