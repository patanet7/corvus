import { ApiError } from '$lib/api/sessions';

export interface ActiveDispatch {
	dispatchId: string;
	sessionId: string;
	user: string;
	turnId: string;
	startedAt: Date;
	interruptRequestedAt?: Date | null;
	interruptSource?: string | null;
}

interface ApiActiveDispatch {
	dispatch_id: string;
	session_id: string;
	user: string;
	turn_id: string;
	started_at: string;
	interrupt_requested_at?: string | null;
	interrupt_source?: string | null;
}

function toActiveDispatch(raw: ApiActiveDispatch): ActiveDispatch {
	return {
		dispatchId: raw.dispatch_id,
		sessionId: raw.session_id,
		user: raw.user,
		turnId: raw.turn_id,
		startedAt: new Date(raw.started_at),
		interruptRequestedAt: raw.interrupt_requested_at ? new Date(raw.interrupt_requested_at) : null,
		interruptSource: raw.interrupt_source ?? null
	};
}

export async function listActiveDispatches(): Promise<ActiveDispatch[]> {
	const response = await fetch('/api/dispatch/active');
	if (!response.ok) {
		throw new ApiError(`Failed to load active dispatches (${response.status})`, response.status);
	}
	const body = (await response.json()) as ApiActiveDispatch[];
	return body.map(toActiveDispatch);
}

export async function interruptDispatch(dispatchId: string): Promise<void> {
	const response = await fetch(`/api/dispatch/${dispatchId}/interrupt`, {
		method: 'POST'
	});
	if (!response.ok) {
		throw new ApiError(`Failed to interrupt dispatch (${response.status})`, response.status);
	}
}
