<script lang="ts">
	import { onMount } from 'svelte';
	import { pushToast } from '$lib/chat/toasts.svelte';
	import {
		createMemoryRecord,
		forgetMemoryRecord,
		listMemoryAgents,
		listMemoryBackends,
		listMemoryRecords,
		searchMemoryRecords,
		updateMemoryRecord,
		type MemoryBackendsStatus,
		type MemoryAgentInfo,
		type MemoryRecord
	} from '$lib/api/memory';
	import { interruptDispatch, listActiveDispatches, type ActiveDispatch } from '$lib/api/control';
	import MemoryBackendStatusCard from '$lib/components/MemoryBackendStatusCard.svelte';
	import MemoryAgentContextCard from '$lib/components/MemoryAgentContextCard.svelte';
	import MemoryCreateCard from '$lib/components/MemoryCreateCard.svelte';
	import MemoryEditCard from '$lib/components/MemoryEditCard.svelte';

	interface Props {
		backendDisabled?: boolean;
	}

	let { backendDisabled = false }: Props = $props();

	let agents = $state<MemoryAgentInfo[]>([]);
	let records = $state<MemoryRecord[]>([]);
	let backendStatus = $state<MemoryBackendsStatus | null>(null);
	let activeDispatches = $state<ActiveDispatch[]>([]);
	let selectedAgent = $state('');
	let selectedRecordId = $state<string | null>(null);
	let query = $state('');
	let domainFilter = $state('');
	let loadingAgents = $state(false);
	let loadingRecords = $state(false);
	let loadingBackends = $state(false);
	let loadingDispatches = $state(false);
	let loadingCreate = $state(false);
	let loadingUpdate = $state(false);
	let loadingForgetId = $state<string | null>(null);
	let error = $state<string | null>(null);
	let backendError = $state<string | null>(null);

	const selectedRecord = $derived.by(
		() => records.find((record) => record.id === selectedRecordId) ?? null
	);
	const selectedAgentInfo = $derived.by(
		() => agents.find((agent) => agent.id === selectedAgent) ?? null
	);

	async function refreshAgents(): Promise<void> {
		if (backendDisabled) return;
		loadingAgents = true;
		error = null;
		try {
			agents = await listMemoryAgents();
			if (!selectedAgent && agents.length > 0) {
				selectedAgent = agents[0].id;
			}
		} catch (err) {
			console.warn('Failed to load memory agents:', err);
			error = 'Failed to load memory agent contexts.';
		} finally {
			loadingAgents = false;
		}
	}

	async function refreshRecords(): Promise<void> {
		if (backendDisabled || !selectedAgent) return;
		loadingRecords = true;
		error = null;
		try {
			const normalizedQuery = query.trim();
			if (normalizedQuery.length > 0) {
				records = await searchMemoryRecords(selectedAgent, normalizedQuery, {
					domain: domainFilter || undefined,
					limit: 80
				});
			} else {
				records = await listMemoryRecords(selectedAgent, {
					domain: domainFilter || undefined,
					limit: 120
				});
			}
			if (records.length === 0) {
				selectedRecordId = null;
			} else if (!selectedRecordId || !records.some((record) => record.id === selectedRecordId)) {
				selectedRecordId = records[0].id;
			}
		} catch (err) {
			console.warn('Failed to load memory records:', err);
			error = 'Failed to load memory records.';
		} finally {
			loadingRecords = false;
		}
	}

	async function refreshBackends(): Promise<void> {
		if (backendDisabled) return;
		loadingBackends = true;
		backendError = null;
		try {
			backendStatus = await listMemoryBackends();
		} catch (err) {
			console.warn('Failed to load memory backends:', err);
			backendError = 'Failed to load memory backend status.';
		} finally {
			loadingBackends = false;
		}
	}

	async function refreshDispatches(): Promise<void> {
		if (backendDisabled) return;
		loadingDispatches = true;
		try {
			activeDispatches = await listActiveDispatches();
		} catch (err) {
			console.warn('Failed to load active dispatches:', err);
		} finally {
			loadingDispatches = false;
		}
	}

	async function saveMemory(draft: {
		content: string;
		visibility: 'private' | 'shared';
		importance: number;
		tags: string[];
	}): Promise<boolean> {
		if (!selectedAgent) return false;
		loadingCreate = true;
		try {
			await createMemoryRecord({
				agent: selectedAgent,
				content: draft.content,
				visibility: draft.visibility,
				importance: draft.importance,
				tags: draft.tags,
				domain: domainFilter || undefined
			});
			pushToast('Memory saved.', 'success');
			await refreshRecords();
			return true;
		} catch (err) {
			console.warn('Failed to save memory:', err);
			pushToast('Failed to save memory record.', 'error');
			return false;
		} finally {
			loadingCreate = false;
		}
	}

	async function forgetMemory(recordId: string): Promise<void> {
		if (!selectedAgent) return;
		loadingForgetId = recordId;
		try {
			await forgetMemoryRecord(selectedAgent, recordId);
			pushToast('Memory forgotten.', 'success');
			if (selectedRecordId === recordId) selectedRecordId = null;
			await refreshRecords();
		} catch (err) {
			console.warn('Failed to forget memory:', err);
			pushToast('Failed to forget memory record.', 'error');
		} finally {
			loadingForgetId = null;
		}
	}

	async function updateMemory(draft: {
		recordId: string;
		content: string;
		visibility: 'private' | 'shared';
		importance: number;
		tags: string[];
	}): Promise<boolean> {
		if (!selectedAgent) return false;
		loadingUpdate = true;
		try {
			await updateMemoryRecord(draft.recordId, {
				agent: selectedAgent,
				content: draft.content,
				visibility: draft.visibility,
				importance: draft.importance,
				tags: draft.tags
			});
			pushToast('Memory updated.', 'success');
			await refreshRecords();
			selectedRecordId = draft.recordId;
			return true;
		} catch (err) {
			console.warn('Failed to update memory:', err);
			pushToast('Failed to update memory record.', 'error');
			return false;
		} finally {
			loadingUpdate = false;
		}
	}

	async function requestInterrupt(dispatchId: string): Promise<void> {
		try {
			await interruptDispatch(dispatchId);
			pushToast(`Interrupt requested for ${dispatchId.slice(0, 8)}.`, 'warning');
			await refreshDispatches();
		} catch (err) {
			console.warn('Failed to interrupt dispatch:', err);
			pushToast('Failed to interrupt dispatch.', 'error');
		}
	}

	onMount(() => {
		if (backendDisabled) return;
		void (async () => {
			await refreshAgents();
			await Promise.all([refreshRecords(), refreshDispatches(), refreshBackends()]);
		})();
	});
</script>

<section class="flex min-w-0 flex-1 flex-col overflow-hidden p-4" aria-label="Memory workspace panel">
	<div class="rounded border border-border-muted bg-surface px-4 py-3">
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div>
				<h2 class="text-sm font-semibold uppercase tracking-wide text-text-primary">Memory Workspace</h2>
				<p class="mt-1 text-xs text-text-muted">
					Search, curate, and inspect agent-scoped memory records with live dispatch awareness.
				</p>
			</div>
			<div class="flex items-center gap-2">
				<button
					type="button"
					class="rounded border border-border px-2 py-1 text-xs text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
					onclick={() => {
						void Promise.all([refreshAgents(), refreshRecords(), refreshDispatches(), refreshBackends()]);
					}}
				>
					Refresh
				</button>
			</div>
		</div>

		{#if backendDisabled}
			<div class="mt-3 rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
				Backend disabled mode: memory workspace is unavailable.
			</div>
		{:else}
			<div class="mt-3 grid gap-2 md:grid-cols-[200px,200px,minmax(0,1fr),auto]">
				<label class="rounded border border-border-muted bg-inset px-2 py-1 text-xs">
					<div class="text-[10px] uppercase tracking-wide text-text-muted">Agent Context</div>
					<select
						class="mt-1 w-full bg-transparent text-text-primary outline-none"
						bind:value={selectedAgent}
						disabled={loadingAgents}
						onchange={() => {
							void refreshRecords();
						}}
					>
						{#each agents as agent (agent.id)}
							<option value={agent.id}>{agent.label} ({agent.memoryDomain})</option>
						{/each}
					</select>
				</label>
				<label class="rounded border border-border-muted bg-inset px-2 py-1 text-xs">
					<div class="text-[10px] uppercase tracking-wide text-text-muted">Domain Filter</div>
					<input
						type="text"
						class="mt-1 w-full bg-transparent text-text-primary outline-none placeholder:text-text-muted"
						placeholder="all domains"
						bind:value={domainFilter}
					/>
				</label>
				<label class="rounded border border-border-muted bg-inset px-2 py-1 text-xs">
					<div class="text-[10px] uppercase tracking-wide text-text-muted">Search Query</div>
					<input
						type="text"
						class="mt-1 w-full bg-transparent text-text-primary outline-none placeholder:text-text-muted"
						placeholder="content, tags, context..."
						bind:value={query}
						onkeydown={(event) => {
							if (event.key === 'Enter') {
								event.preventDefault();
								void refreshRecords();
							}
						}}
					/>
				</label>
				<button
					type="button"
					class="rounded border border-focus bg-surface-raised px-3 py-1 text-xs text-text-primary"
					onclick={() => {
						void refreshRecords();
					}}
					disabled={!selectedAgent || loadingRecords}
				>
					{loadingRecords ? 'Loading...' : query.trim().length > 0 ? 'Search' : 'Load'}
				</button>
			</div>

			{#if error}
				<div class="mt-3 rounded border border-error/50 bg-error/10 px-3 py-2 text-xs text-error">{error}</div>
			{/if}

			<div class="mt-3 grid gap-3 xl:grid-cols-2">
				<MemoryAgentContextCard agent={selectedAgentInfo} loading={loadingAgents} />
				<MemoryBackendStatusCard
					status={backendStatus}
					loading={loadingBackends}
					error={backendError}
					onRefresh={refreshBackends}
				/>
			</div>
		{/if}
	</div>

	<div class="mt-3 grid min-h-0 flex-1 gap-3 xl:grid-cols-[320px,minmax(0,1fr),340px]">
		<div class="flex min-h-0 flex-col rounded border border-border-muted bg-surface">
			<div class="border-b border-border-muted px-3 py-2 text-xs text-text-muted">
				Memory Records ({records.length})
			</div>
			{#if loadingRecords}
				<div class="p-3 text-xs text-text-muted">Loading records...</div>
			{:else if records.length === 0}
				<div class="p-3 text-xs text-text-muted">No records for this filter set.</div>
			{:else}
				<div class="min-h-0 flex-1 overflow-y-auto p-2 space-y-2">
					{#each records as record (record.id)}
						<button
							type="button"
							class="w-full rounded border px-2 py-2 text-left text-xs transition-colors {selectedRecordId === record.id
								? 'border-focus bg-surface-raised'
								: 'border-border-muted bg-inset hover:border-border'}"
							onclick={() => {
								selectedRecordId = record.id;
							}}
						>
							<div class="font-mono text-[10px] text-text-muted">{record.id.slice(0, 8)}</div>
							<div class="mt-1 line-clamp-3 text-text-primary">{record.content}</div>
							<div class="mt-1 text-[10px] text-text-muted">
								{record.domain} · {record.visibility} · imp {record.importance.toFixed(2)}
							</div>
						</button>
					{/each}
				</div>
			{/if}
		</div>

		<div class="flex min-h-0 flex-col rounded border border-border-muted bg-surface">
			<div class="border-b border-border-muted px-3 py-2 text-xs text-text-muted">Record Detail</div>
			{#if !selectedRecord}
				<div class="p-3 text-xs text-text-muted">Select a record to inspect details.</div>
			{:else}
				<div class="min-h-0 flex-1 overflow-y-auto p-3 space-y-3 text-xs">
					<div>
						<div class="text-[10px] uppercase tracking-wide text-text-muted">Content</div>
						<div class="mt-1 whitespace-pre-wrap text-text-primary">{selectedRecord.content}</div>
					</div>
					<div class="grid gap-2 sm:grid-cols-2">
						<div>
							<div class="text-[10px] uppercase tracking-wide text-text-muted">Domain</div>
							<div class="mt-1 text-text-primary">{selectedRecord.domain}</div>
						</div>
						<div>
							<div class="text-[10px] uppercase tracking-wide text-text-muted">Visibility</div>
							<div class="mt-1 text-text-primary">{selectedRecord.visibility}</div>
						</div>
						<div>
							<div class="text-[10px] uppercase tracking-wide text-text-muted">Importance</div>
							<div class="mt-1 text-text-primary">{selectedRecord.importance.toFixed(2)}</div>
						</div>
						<div>
							<div class="text-[10px] uppercase tracking-wide text-text-muted">Score</div>
							<div class="mt-1 text-text-primary">{selectedRecord.score.toFixed(3)}</div>
						</div>
						<div>
							<div class="text-[10px] uppercase tracking-wide text-text-muted">Created</div>
							<div class="mt-1 text-text-primary">
								{selectedRecord.createdAt.toLocaleString([], {
									year: 'numeric',
									month: 'short',
									day: '2-digit',
									hour: '2-digit',
									minute: '2-digit'
								})}
							</div>
						</div>
						<div>
							<div class="text-[10px] uppercase tracking-wide text-text-muted">Source</div>
							<div class="mt-1 text-text-primary">{selectedRecord.source}</div>
						</div>
					</div>
					<div>
						<div class="text-[10px] uppercase tracking-wide text-text-muted">Tags</div>
						<div class="mt-1 flex flex-wrap gap-1">
							{#if selectedRecord.tags.length === 0}
								<span class="text-text-muted">No tags</span>
							{:else}
								{#each selectedRecord.tags as tag (tag)}
									<span class="rounded border border-border-muted px-1.5 py-0.5">{tag}</span>
								{/each}
							{/if}
						</div>
					</div>
					<div>
						<div class="text-[10px] uppercase tracking-wide text-text-muted">Metadata</div>
						<pre class="mt-1 overflow-x-auto rounded border border-border-muted bg-inset p-2 text-[10px] text-text-secondary">{JSON.stringify(selectedRecord.metadata, null, 2)}</pre>
					</div>
					<button
						type="button"
						class="rounded border border-error/60 bg-error/10 px-3 py-1 text-xs text-error"
						onclick={() => {
							void forgetMemory(selectedRecord.id);
						}}
						disabled={loadingForgetId === selectedRecord.id}
					>
						{loadingForgetId === selectedRecord.id ? 'Forgetting...' : 'Forget Record'}
					</button>
				</div>
			{/if}
		</div>

		<div class="flex min-h-0 flex-col gap-3">
			<MemoryCreateCard
				enabled={Boolean(selectedAgent && selectedAgentInfo?.canWrite)}
				loading={loadingCreate}
				domain={domainFilter || undefined}
				onSave={saveMemory}
			/>
			<MemoryEditCard
				record={selectedRecord}
				enabled={Boolean(selectedAgent && selectedAgentInfo?.canWrite)}
				loading={loadingUpdate}
				onSave={updateMemory}
			/>

			<div class="rounded border border-border-muted bg-surface">
				<div class="flex items-center justify-between border-b border-border-muted px-3 py-2 text-xs text-text-muted">
					<span>Active Dispatches ({activeDispatches.length})</span>
					<button
						type="button"
						class="rounded border border-border-muted px-2 py-0.5 text-[11px] text-text-secondary"
						onclick={() => {
							void refreshDispatches();
						}}
					>
						Refresh
					</button>
				</div>
				{#if loadingDispatches}
					<div class="p-3 text-xs text-text-muted">Loading active dispatches...</div>
				{:else if activeDispatches.length === 0}
					<div class="p-3 text-xs text-text-muted">No active dispatches.</div>
				{:else}
					<div class="max-h-[280px] overflow-y-auto p-2 space-y-2 text-xs">
						{#each activeDispatches as row (row.dispatchId)}
							<div class="rounded border border-border-muted bg-inset px-2 py-2">
								<div class="font-mono text-[10px] text-text-muted">{row.dispatchId.slice(0, 12)}</div>
								<div class="mt-1 text-text-secondary">session {row.sessionId.slice(0, 8)}</div>
								<div class="mt-1 text-text-muted">
									started {row.startedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
								</div>
								<button
									type="button"
									class="mt-2 rounded border border-warning/60 bg-warning/10 px-2 py-0.5 text-[11px] text-warning"
									onclick={() => {
										void requestInterrupt(row.dispatchId);
									}}
								>
									Interrupt
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>
</section>
