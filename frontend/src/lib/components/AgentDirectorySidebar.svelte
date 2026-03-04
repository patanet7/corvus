<script lang="ts">
	import type { CreateAgentDraft } from '$lib/api/agents';
	import type { AgentInfo } from '$lib/types';
	import AgentSpecialtyAccess from './AgentSpecialtyAccess.svelte';

	interface Props {
		agents: AgentInfo[];
		activeAgentId: string | null;
		width: number;
		loading?: boolean;
		error?: string | null;
		creatingAgent?: boolean;
		createError?: string | null;
		onSelectAgent: (agentId: string) => void;
		onRefresh?: () => void;
		onCreateAgent?: (draft: CreateAgentDraft) => Promise<boolean | void>;
	}

	let {
		agents,
		activeAgentId,
		width,
		loading = false,
		error = null,
		creatingAgent = false,
		createError = null,
		onSelectAgent,
		onRefresh,
		onCreateAgent
	}: Props = $props();

	let searchQuery = $state('');
	let createExpanded = $state(false);
	let draftName = $state('');
	let draftDescription = $state('');
	let draftMemoryDomain = $state('');
	let draftPreferredModel = $state('');
	let draftBuiltinTools = $state('');
	let draftModules = $state('');
	let draftConfirmGated = $state('');
	let draftPermissionMode = $state<'default' | 'acceptEdits' | 'plan' | 'bypassPermissions'>('default');

	const filtered = $derived.by(() => {
		const query = searchQuery.trim().toLowerCase();
		if (!query) return agents;
		return agents.filter((agent) => {
			const hay = `${agent.id} ${agent.label} ${agent.description ?? ''}`.toLowerCase();
			return hay.includes(query);
		});
	});

	const isDraftNameValid = $derived.by(() => {
		const trimmed = draftName.trim();
		if (!trimmed) return false;
		return /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(trimmed);
	});

	function statusColor(status: AgentInfo['runtimeStatus']): string {
		switch (status) {
			case 'busy':
				return 'var(--color-warning)';
			case 'offline':
				return 'var(--color-error)';
			case 'degraded':
				return 'var(--color-info)';
			default:
				return 'var(--color-success)';
		}
	}

	function parseCsv(value: string): string[] {
		return value
			.split(',')
			.map((token) => token.trim())
			.filter((token) => token.length > 0);
	}

	function resetDraft(): void {
		draftName = '';
		draftDescription = '';
		draftMemoryDomain = '';
		draftPreferredModel = '';
		draftBuiltinTools = '';
		draftModules = '';
		draftConfirmGated = '';
		draftPermissionMode = 'default';
	}

	async function submitCreate(): Promise<void> {
		if (!onCreateAgent || !isDraftNameValid || !draftDescription.trim()) return;
		const created = await onCreateAgent({
			name: draftName.trim(),
			description: draftDescription.trim(),
			memoryDomain: draftMemoryDomain.trim() || undefined,
			preferredModel: draftPreferredModel.trim() || undefined,
			builtinTools: parseCsv(draftBuiltinTools),
			moduleNames: parseCsv(draftModules),
			confirmGatedTools: parseCsv(draftConfirmGated),
			permissionMode: draftPermissionMode
		});
		if (created !== false) {
			resetDraft();
			createExpanded = false;
		}
	}
</script>

<aside
	class="flex flex-col overflow-hidden border-r border-border bg-surface"
	style="width: {width}px; min-width: 200px; max-width: 420px;"
	aria-label="Agent directory"
>
	<div class="flex items-center justify-between border-b border-border-muted p-3">
		<span class="text-sm font-medium">Agents</span>
		<div class="flex items-center gap-1">
			{#if onCreateAgent}
				<button
					type="button"
					class="rounded border border-border px-2 py-0.5 text-[11px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
					onclick={() => {
						createExpanded = !createExpanded;
					}}
				>
					{createExpanded ? 'Close' : 'New Agent'}
				</button>
			{/if}
			{#if onRefresh}
				<button
					type="button"
					class="rounded border border-border px-2 py-0.5 text-[11px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
					onclick={onRefresh}
				>
					Refresh
				</button>
			{/if}
		</div>
	</div>

	<div class="border-b border-border-muted p-2">
		<input
			type="text"
			class="w-full rounded border border-border bg-inset px-2 py-1 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-focus"
			placeholder="Search agents..."
			bind:value={searchQuery}
		/>
	</div>

	{#if createExpanded}
		<div class="space-y-2 border-b border-border-muted p-2 text-[11px]">
			<div class="rounded border border-border-muted bg-inset px-2 py-2">
				<div class="text-[10px] uppercase tracking-wide text-text-muted">Create Agent</div>
				<div class="mt-2 grid gap-2">
					<label class="grid gap-1">
						<span class="text-text-muted">Name</span>
						<input
							type="text"
							class="w-full rounded border border-border bg-surface px-2 py-1 text-text-primary outline-none focus:ring-2 focus:ring-focus"
							placeholder="agent-id"
							bind:value={draftName}
						/>
					</label>
					<label class="grid gap-1">
						<span class="text-text-muted">Description</span>
						<input
							type="text"
							class="w-full rounded border border-border bg-surface px-2 py-1 text-text-primary outline-none focus:ring-2 focus:ring-focus"
							placeholder="Describe this agent..."
							bind:value={draftDescription}
						/>
					</label>
					<label class="grid gap-1">
						<span class="text-text-muted">Memory Domain</span>
						<input
							type="text"
							class="w-full rounded border border-border bg-surface px-2 py-1 text-text-primary outline-none focus:ring-2 focus:ring-focus"
							placeholder="same as name (optional)"
							bind:value={draftMemoryDomain}
						/>
					</label>
					<label class="grid gap-1">
						<span class="text-text-muted">Preferred Model</span>
						<input
							type="text"
							class="w-full rounded border border-border bg-surface px-2 py-1 text-text-primary outline-none focus:ring-2 focus:ring-focus"
							placeholder="ollama/llama3:8b (optional)"
							bind:value={draftPreferredModel}
						/>
					</label>
					<label class="grid gap-1">
						<span class="text-text-muted">Builtin Tools (CSV)</span>
						<input
							type="text"
							class="w-full rounded border border-border bg-surface px-2 py-1 text-text-primary outline-none focus:ring-2 focus:ring-focus"
							placeholder="Bash,Read"
							bind:value={draftBuiltinTools}
						/>
					</label>
					<label class="grid gap-1">
						<span class="text-text-muted">Tool Modules (CSV)</span>
						<input
							type="text"
							class="w-full rounded border border-border bg-surface px-2 py-1 text-text-primary outline-none focus:ring-2 focus:ring-focus"
							placeholder="paperless,obsidian"
							bind:value={draftModules}
						/>
					</label>
					<label class="grid gap-1">
						<span class="text-text-muted">Confirm-Gated Tools (CSV)</span>
						<input
							type="text"
							class="w-full rounded border border-border bg-surface px-2 py-1 text-text-primary outline-none focus:ring-2 focus:ring-focus"
							placeholder="paperless.tag"
							bind:value={draftConfirmGated}
						/>
					</label>
					<label class="grid gap-1">
						<span class="text-text-muted">Permission Mode</span>
						<select
							class="w-full rounded border border-border bg-surface px-2 py-1 text-text-primary outline-none focus:ring-2 focus:ring-focus"
							bind:value={draftPermissionMode}
						>
							<option value="default">default</option>
							<option value="acceptEdits">acceptEdits</option>
							<option value="plan">plan</option>
							<option value="bypassPermissions">bypassPermissions</option>
						</select>
					</label>
				</div>
				{#if !isDraftNameValid && draftName.trim().length > 0}
					<div class="mt-2 rounded border border-warning/40 bg-warning/10 px-2 py-1 text-warning">
						Name must be alphanumeric with optional `-` or `_`.
					</div>
				{/if}
				{#if createError}
					<div class="mt-2 rounded border border-error/40 bg-error/10 px-2 py-1 text-error">{createError}</div>
				{/if}
				<div class="mt-2 flex items-center gap-2">
					<button
						type="button"
						class="rounded border border-focus bg-surface px-2 py-1 text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
						disabled={creatingAgent || !isDraftNameValid || !draftDescription.trim()}
						onclick={() => {
							void submitCreate();
						}}
					>
						{creatingAgent ? 'Creating...' : 'Create Agent'}
					</button>
					<button
						type="button"
						class="rounded border border-border px-2 py-1 text-text-secondary"
						disabled={creatingAgent}
						onclick={() => {
							createExpanded = false;
						}}
					>
						Cancel
					</button>
				</div>
			</div>
		</div>
	{/if}

	<div class="flex-1 overflow-y-auto">
		{#if loading}
			<div class="p-4 text-sm text-text-muted">Loading agents...</div>
		{:else if error}
			<div class="p-4 text-sm text-error">{error}</div>
		{:else if filtered.length === 0}
			<div class="p-4 text-sm text-text-muted">No agents found.</div>
		{:else}
			{#each filtered as agent (agent.id)}
				<button
					type="button"
					class="w-full border-b border-border-muted px-3 py-2 text-left transition-colors {activeAgentId === agent.id
						? 'bg-surface-raised'
						: 'hover:bg-surface-raised'}"
					onclick={() => onSelectAgent(agent.id)}
				>
					<div class="flex items-center gap-2">
						<span class="h-2 w-2 rounded-full" style="background: {statusColor(agent.runtimeStatus)}"></span>
						<span class="text-sm text-text-primary">{agent.label}</span>
						<span class="ml-auto text-[10px] uppercase tracking-wide text-text-muted"
							>{agent.runtimeStatus ?? 'active'}</span
						>
					</div>
					<div class="mt-1 line-clamp-2 text-xs text-text-secondary">
						{agent.description ?? 'No description'}
					</div>
					<div class="mt-1 flex items-center gap-2 text-[10px] text-text-muted">
						{#if agent.currentModel}
							<span>model: {agent.currentModel}</span>
						{/if}
						{#if agent.queueDepth !== undefined}
							<span>queue: {agent.queueDepth}</span>
						{/if}
					</div>
					<div class="mt-1">
						<AgentSpecialtyAccess {agent} compact />
					</div>
				</button>
			{/each}
		{/if}
	</div>
</aside>
