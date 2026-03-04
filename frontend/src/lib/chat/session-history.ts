export type LoadStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface SessionHistoryState {
	sessionsStatus: LoadStatus;
	sessionsError: string | null;
	transcriptStatus: LoadStatus;
	transcriptSessionId: string | null;
	transcriptError: string | null;
}

export type SessionHistoryEvent =
	| { type: 'sessions_load_start' }
	| { type: 'sessions_load_success' }
	| { type: 'sessions_load_error'; error: string }
	| { type: 'transcript_load_start'; sessionId: string }
	| { type: 'transcript_load_success'; sessionId: string }
	| { type: 'transcript_load_error'; sessionId: string; error: string }
	| { type: 'transcript_reset' };

export function createSessionHistoryState(): SessionHistoryState {
	return {
		sessionsStatus: 'idle',
		sessionsError: null,
		transcriptStatus: 'idle',
		transcriptSessionId: null,
		transcriptError: null
	};
}

export function reduceSessionHistory(
	state: SessionHistoryState,
	event: SessionHistoryEvent
): SessionHistoryState {
	switch (event.type) {
		case 'sessions_load_start':
			return { ...state, sessionsStatus: 'loading', sessionsError: null };
		case 'sessions_load_success':
			return { ...state, sessionsStatus: 'ready', sessionsError: null };
		case 'sessions_load_error':
			return { ...state, sessionsStatus: 'error', sessionsError: event.error };
		case 'transcript_load_start':
			return {
				...state,
				transcriptStatus: 'loading',
				transcriptSessionId: event.sessionId,
				transcriptError: null
			};
		case 'transcript_load_success':
			if (state.transcriptSessionId !== event.sessionId) {
				return state;
			}
			return {
				...state,
				transcriptStatus: 'ready',
				transcriptError: null
			};
		case 'transcript_load_error':
			if (state.transcriptSessionId !== event.sessionId) {
				return state;
			}
			return {
				...state,
				transcriptStatus: 'error',
				transcriptError: event.error
			};
		case 'transcript_reset':
			return {
				...state,
				transcriptStatus: 'idle',
				transcriptSessionId: null,
				transcriptError: null
			};
		default:
			return state;
	}
}

export function isSessionsLoading(state: SessionHistoryState): boolean {
	return state.sessionsStatus === 'loading';
}

export function sessionsErrorMessage(state: SessionHistoryState): string | null {
	return state.sessionsStatus === 'error' ? state.sessionsError : null;
}

export function isTranscriptLoadingForSession(
	state: SessionHistoryState,
	sessionId: string | null
): boolean {
	if (!sessionId) return false;
	return state.transcriptStatus === 'loading' && state.transcriptSessionId === sessionId;
}

export function transcriptErrorForSession(
	state: SessionHistoryState,
	sessionId: string | null
): string | null {
	if (!sessionId) return null;
	if (state.transcriptStatus !== 'error' || state.transcriptSessionId !== sessionId) {
		return null;
	}
	return state.transcriptError;
}
