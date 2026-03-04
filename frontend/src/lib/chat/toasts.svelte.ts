import { v4 as uuid } from 'uuid';

export type ToastKind = 'info' | 'warning' | 'error' | 'success';

export interface Toast {
	id: string;
	kind: ToastKind;
	message: string;
	createdAt: Date;
}

const DEDUPE_WINDOW_MS = 4000;

export const toastStore = $state<{ items: Toast[] }>({
	items: []
});

export function dismissToast(id: string): void {
	toastStore.items = toastStore.items.filter((toast) => toast.id !== id);
}

export function pushToast(
	message: string,
	kind: ToastKind = 'info',
	options?: { ttlMs?: number; dedupeKey?: string }
): string | null {
	const trimmed = message.trim();
	if (!trimmed) return null;

	const dedupeKey = options?.dedupeKey ?? `${kind}:${trimmed}`;
	const now = Date.now();
	const duplicate = toastStore.items.find((toast) => {
		const toastKey = `${toast.kind}:${toast.message}`;
		return toastKey === dedupeKey && now - toast.createdAt.getTime() < DEDUPE_WINDOW_MS;
	});
	if (duplicate) {
		return null;
	}

	const toast: Toast = {
		id: uuid(),
		kind,
		message: trimmed,
		createdAt: new Date()
	};
	toastStore.items = [...toastStore.items, toast].slice(-5);

	const ttlMs = options?.ttlMs ?? (kind === 'error' ? 8000 : 5000);
	setTimeout(() => {
		dismissToast(toast.id);
	}, ttlMs);

	return toast.id;
}
