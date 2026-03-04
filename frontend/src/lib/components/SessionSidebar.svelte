<script lang="ts">
	import type { Session } from '$lib/types';
	import SessionListItem from './SessionListItem.svelte';

	interface Props {
		sessions: Session[];
		activeSessionId: string | null;
		width: number;
		loading?: boolean;
		error?: string | null;
		onSelectSession: (id: string) => void;
		onNewChat: () => void;
		onRetryLoad?: () => void;
		onRenameSession?: (id: string, name: string) => void | Promise<void>;
		onDeleteSession?: (id: string) => void | Promise<void>;
	}

	let {
		sessions,
		activeSessionId,
		width,
		loading = false,
		error = null,
		onSelectSession,
		onNewChat,
		onRetryLoad,
		onRenameSession,
		onDeleteSession
	}: Props = $props();

	let searchQuery = $state('');

	const filteredSessions = $derived(
		searchQuery.trim()
			? sessions.filter(
					(s) =>
						(s.name ?? '').toLowerCase().includes(searchQuery.toLowerCase()) ||
						s.agentsUsed.some((a) => a.toLowerCase().includes(searchQuery.toLowerCase()))
				)
			: sessions
	);
</script>

<aside
	class="flex flex-col bg-surface border-r border-border overflow-hidden"
	style="width: {width}px; min-width: 160px; max-width: 400px;"
	aria-label="Session sidebar"
>
	<!-- Header -->
	<div class="flex items-center justify-between p-3 border-b border-border-muted">
		<span class="text-sm font-medium">Sessions</span>
		<button
			class="text-xs px-2 py-1 rounded bg-surface-raised hover:bg-overlay text-text-secondary hover:text-text-primary transition-colors"
			onclick={onNewChat}
		>
			+ New
		</button>
	</div>

	<!-- Search -->
	<div class="p-2">
		<input
			type="text"
			placeholder="Search sessions..."
			class="w-full px-2 py-1 text-sm bg-inset border border-border rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-focus"
			bind:value={searchQuery}
		/>
	</div>

	<!-- Session list -->
	<div class="flex-1 overflow-y-auto" aria-label="Session list">
		{#if loading}
			<div class="p-4 text-center text-text-muted text-sm">Loading session history...</div>
		{:else if error}
			<div class="p-4 text-center text-error text-sm">
				<div>{error}</div>
				{#if onRetryLoad}
					<button
						class="mt-2 rounded border border-border px-2 py-1 text-xs text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
						type="button"
						onclick={onRetryLoad}
					>
						Retry
					</button>
				{/if}
			</div>
		{:else if filteredSessions.length === 0 && sessions.length === 0}
			<div class="p-4 text-center text-text-muted text-sm">
				No sessions yet.<br />Start a conversation to get going.
			</div>
		{:else if filteredSessions.length === 0}
			<div class="p-4 text-center text-text-muted text-sm">No matching sessions.</div>
		{:else}
			{#each filteredSessions as session (session.id)}
				<SessionListItem
					{session}
					active={session.id === activeSessionId}
					onSelect={onSelectSession}
					onRename={onRenameSession}
					onDelete={onDeleteSession}
				/>
			{/each}
		{/if}
	</div>
</aside>
