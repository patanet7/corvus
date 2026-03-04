export interface RunOutputChunk {
	runId: string;
	taskId: string;
	chunkIndex: number;
	final: boolean;
	content: string;
	timestamp: Date;
}

interface RunOutputState {
	nextIndex: number;
	buffer: Map<number, RunOutputChunk>;
}

export interface RunOutputFlushResult {
	chunks: RunOutputChunk[];
	missingRanges: Array<{ from: number; to: number }>;
}

export class RunOutputOrderer {
	private readonly states = new Map<string, RunOutputState>();

	ingest(chunk: RunOutputChunk): RunOutputChunk[] {
		if (!Number.isInteger(chunk.chunkIndex) || chunk.chunkIndex < 0) {
			return [];
		}
		const state = this.ensureState(chunk.runId);

		// Duplicate or already-committed chunk.
		if (chunk.chunkIndex < state.nextIndex || state.buffer.has(chunk.chunkIndex)) {
			return [];
		}

		state.buffer.set(chunk.chunkIndex, chunk);
		return this.drainSequential(chunk.runId);
	}

	flushRun(runId: string): RunOutputFlushResult {
		const state = this.states.get(runId);
		if (!state || state.buffer.size === 0) {
			return { chunks: [], missingRanges: [] };
		}

		const missingRanges: Array<{ from: number; to: number }> = [];
		const chunks: RunOutputChunk[] = [];
		const indices = [...state.buffer.keys()].sort((a, b) => a - b);
		let cursor = state.nextIndex;

		for (const index of indices) {
			const chunk = state.buffer.get(index);
			if (!chunk) continue;
			if (index > cursor) {
				missingRanges.push({ from: cursor, to: index - 1 });
			}
			chunks.push(chunk);
			cursor = index + 1;
		}

		state.nextIndex = cursor;
		state.buffer.clear();
		return { chunks, missingRanges };
	}

	resetRun(runId: string): void {
		this.states.delete(runId);
	}

	resetAll(): void {
		this.states.clear();
	}

	private ensureState(runId: string): RunOutputState {
		const existing = this.states.get(runId);
		if (existing) return existing;
		const created: RunOutputState = {
			nextIndex: 0,
			buffer: new Map<number, RunOutputChunk>()
		};
		this.states.set(runId, created);
		return created;
	}

	private drainSequential(runId: string): RunOutputChunk[] {
		const state = this.states.get(runId);
		if (!state) return [];
		const ordered: RunOutputChunk[] = [];
		while (state.buffer.has(state.nextIndex)) {
			const chunk = state.buffer.get(state.nextIndex);
			state.buffer.delete(state.nextIndex);
			if (!chunk) break;
			ordered.push(chunk);
			state.nextIndex += 1;
		}
		return ordered;
	}
}
