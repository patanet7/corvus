export type SidebarMode = 'chat' | 'tasks';

export type SidebarWidths = Record<SidebarMode, number>;

const STORAGE_KEY = 'corvus.layout.sidebar-widths.v1';
const MIN_WIDTH = 160;
const MAX_WIDTH = 400;
const DEFAULT_WIDTH = 240;

function clampWidth(value: number): number {
	return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Math.round(value)));
}

export function defaultSidebarWidths(): SidebarWidths {
	return {
		chat: DEFAULT_WIDTH,
		tasks: DEFAULT_WIDTH
	};
}

export function loadSidebarWidths(): SidebarWidths {
	if (typeof localStorage === 'undefined') return defaultSidebarWidths();
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return defaultSidebarWidths();
		const parsed = JSON.parse(raw) as Partial<SidebarWidths> | null;
		if (!parsed || typeof parsed !== 'object') return defaultSidebarWidths();
		return {
			chat: clampWidth(typeof parsed.chat === 'number' ? parsed.chat : DEFAULT_WIDTH),
			tasks: clampWidth(typeof parsed.tasks === 'number' ? parsed.tasks : DEFAULT_WIDTH)
		};
	} catch {
		return defaultSidebarWidths();
	}
}

export function saveSidebarWidths(widths: SidebarWidths): void {
	if (typeof localStorage === 'undefined') return;
	localStorage.setItem(
		STORAGE_KEY,
		JSON.stringify({
			chat: clampWidth(widths.chat),
			tasks: clampWidth(widths.tasks)
		})
	);
}

export function resizedSidebarWidth(current: number, delta: number): number {
	return clampWidth(current + delta);
}
