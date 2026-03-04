import { describe, expect, it } from 'vitest';

import {
	createSessionHistoryState,
	isSessionsLoading,
	isTranscriptLoadingForSession,
	reduceSessionHistory,
	sessionsErrorMessage,
	transcriptErrorForSession
} from './session-history';

describe('session history reducer', () => {
	it('tracks session list loading and error states', () => {
		let state = createSessionHistoryState();
		expect(isSessionsLoading(state)).toBe(false);
		expect(sessionsErrorMessage(state)).toBeNull();

		state = reduceSessionHistory(state, { type: 'sessions_load_start' });
		expect(isSessionsLoading(state)).toBe(true);

		state = reduceSessionHistory(state, {
			type: 'sessions_load_error',
			error: 'failed to fetch'
		});
		expect(isSessionsLoading(state)).toBe(false);
		expect(sessionsErrorMessage(state)).toBe('failed to fetch');
	});

	it('tracks transcript load lifecycle for the active session', () => {
		let state = createSessionHistoryState();
		state = reduceSessionHistory(state, {
			type: 'transcript_load_start',
			sessionId: 'session-1'
		});
		expect(isTranscriptLoadingForSession(state, 'session-1')).toBe(true);
		expect(transcriptErrorForSession(state, 'session-1')).toBeNull();

		state = reduceSessionHistory(state, {
			type: 'transcript_load_success',
			sessionId: 'session-1'
		});
		expect(isTranscriptLoadingForSession(state, 'session-1')).toBe(false);
		expect(transcriptErrorForSession(state, 'session-1')).toBeNull();
	});

	it('ignores stale transcript completion events from older requests', () => {
		let state = createSessionHistoryState();
		state = reduceSessionHistory(state, {
			type: 'transcript_load_start',
			sessionId: 'session-1'
		});
		state = reduceSessionHistory(state, {
			type: 'transcript_load_start',
			sessionId: 'session-2'
		});
		state = reduceSessionHistory(state, {
			type: 'transcript_load_error',
			sessionId: 'session-1',
			error: 'stale'
		});
		expect(transcriptErrorForSession(state, 'session-2')).toBeNull();
		expect(isTranscriptLoadingForSession(state, 'session-2')).toBe(true);
	});

	it('exposes transcript error only for the failed session', () => {
		let state = createSessionHistoryState();
		state = reduceSessionHistory(state, {
			type: 'transcript_load_start',
			sessionId: 'session-7'
		});
		state = reduceSessionHistory(state, {
			type: 'transcript_load_error',
			sessionId: 'session-7',
			error: 'Unable to load transcript.'
		});
		expect(transcriptErrorForSession(state, 'session-7')).toBe('Unable to load transcript.');
		expect(transcriptErrorForSession(state, 'session-8')).toBeNull();
	});
});
