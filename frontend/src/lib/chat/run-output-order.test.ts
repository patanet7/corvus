import { describe, expect, it } from 'vitest';

import { RunOutputOrderer, type RunOutputChunk } from '$lib/chat/run-output-order';

function chunk(
	runId: string,
	chunkIndex: number,
	content: string,
	overrides: Partial<RunOutputChunk> = {}
): RunOutputChunk {
	return {
		runId,
		taskId: `${runId}-task`,
		chunkIndex,
		final: false,
		content,
		timestamp: new Date('2026-03-03T12:00:00.000Z'),
		...overrides
	};
}

describe('RunOutputOrderer', () => {
	it('passes through in-order chunks immediately', () => {
		const orderer = new RunOutputOrderer();
		expect(orderer.ingest(chunk('run-a', 0, 'hello'))).toEqual([chunk('run-a', 0, 'hello')]);
		expect(orderer.ingest(chunk('run-a', 1, ' world'))).toEqual([chunk('run-a', 1, ' world')]);
	});

	it('buffers out-of-order chunks until missing index arrives', () => {
		const orderer = new RunOutputOrderer();
		expect(orderer.ingest(chunk('run-a', 1, 'second'))).toEqual([]);
		expect(orderer.ingest(chunk('run-a', 0, 'first'))).toEqual([
			chunk('run-a', 0, 'first'),
			chunk('run-a', 1, 'second')
		]);
	});

	it('ignores duplicate chunks that were already emitted', () => {
		const orderer = new RunOutputOrderer();
		expect(orderer.ingest(chunk('run-a', 0, 'first'))).toEqual([chunk('run-a', 0, 'first')]);
		expect(orderer.ingest(chunk('run-a', 0, 'first-duplicate'))).toEqual([]);
	});

	it('keeps runs isolated', () => {
		const orderer = new RunOutputOrderer();
		expect(orderer.ingest(chunk('run-a', 0, 'a0'))).toEqual([chunk('run-a', 0, 'a0')]);
		expect(orderer.ingest(chunk('run-b', 1, 'b1'))).toEqual([]);
		expect(orderer.ingest(chunk('run-b', 0, 'b0'))).toEqual([
			chunk('run-b', 0, 'b0'),
			chunk('run-b', 1, 'b1')
		]);
	});

	it('flushes buffered chunks with missing-range metadata', () => {
		const orderer = new RunOutputOrderer();
		expect(orderer.ingest(chunk('run-a', 0, 'zero'))).toEqual([chunk('run-a', 0, 'zero')]);
		expect(orderer.ingest(chunk('run-a', 3, 'three'))).toEqual([]);

		const flushed = orderer.flushRun('run-a');
		expect(flushed.chunks).toEqual([chunk('run-a', 3, 'three')]);
		expect(flushed.missingRanges).toEqual([{ from: 1, to: 2 }]);
	});

	it('drops invalid chunk indexes', () => {
		const orderer = new RunOutputOrderer();
		expect(orderer.ingest(chunk('run-a', -1, 'negative'))).toEqual([]);
		expect(orderer.ingest(chunk('run-a', 0.5, 'float'))).toEqual([]);
		expect(orderer.ingest(chunk('run-a', 0, 'valid'))).toEqual([chunk('run-a', 0, 'valid')]);
	});
});
