export const CHAT_VISIBLE_WINDOW = 120;

export interface VisibleWindowInput {
	messagesLength: number;
	currentVisibleCount: number;
	datasetHeadChanged: boolean;
}

export function nextVisibleCount(input: VisibleWindowInput): number {
	const { messagesLength, currentVisibleCount, datasetHeadChanged } = input;
	if (datasetHeadChanged) {
		return Math.min(messagesLength, CHAT_VISIBLE_WINDOW);
	}

	let next = currentVisibleCount;
	if (messagesLength <= CHAT_VISIBLE_WINDOW && next < messagesLength) {
		next = messagesLength;
	}
	if (next > messagesLength) {
		next = messagesLength;
	}
	if (next === 0 && messagesLength > 0) {
		next = Math.min(messagesLength, CHAT_VISIBLE_WINDOW);
	}
	return next;
}
