import { describe, expect, it } from 'vitest';

import { CHAT_VISIBLE_WINDOW, nextVisibleCount } from './visible-window';

describe('nextVisibleCount', () => {
	it('resets to a bounded window when dataset head changes', () => {
		expect(
			nextVisibleCount({
				messagesLength: 500,
				currentVisibleCount: 5,
				datasetHeadChanged: true
			})
		).toBe(CHAT_VISIBLE_WINDOW);
	});

	it('keeps all rows visible for short transcripts as new messages arrive', () => {
		const afterFirstMessage = nextVisibleCount({
			messagesLength: 1,
			currentVisibleCount: 0,
			datasetHeadChanged: true
		});
		expect(afterFirstMessage).toBe(1);

		const afterAssistantReply = nextVisibleCount({
			messagesLength: 2,
			currentVisibleCount: afterFirstMessage,
			datasetHeadChanged: false
		});
		expect(afterAssistantReply).toBe(2);
	});

	it('clamps count when rows shrink', () => {
		expect(
			nextVisibleCount({
				messagesLength: 3,
				currentVisibleCount: 8,
				datasetHeadChanged: false
			})
		).toBe(3);
	});
});
