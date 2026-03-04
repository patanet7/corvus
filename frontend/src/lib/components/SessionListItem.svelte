<script lang="ts">
	import type { Session } from '$lib/types';
	import { getThemeContext } from '$lib/themes/context';

	interface Props {
		session: Session;
		active: boolean;
		onSelect: (id: string) => void;
		onRename?: (id: string, name: string) => void | Promise<void>;
		onDelete?: (id: string) => void | Promise<void>;
	}

	let { session, active, onSelect, onRename, onDelete }: Props = $props();
	const themeCtx = getThemeContext();
	const activeIndicator = $derived(themeCtx.theme.components.sidebar.activeSessionIndicator);
	const activeClass = $derived.by(() => {
		if (!active) return '';
		if (activeIndicator === 'glow') return 'bg-surface-raised session-active-glow';
		if (activeIndicator === 'background') return 'bg-surface-raised';
		return 'bg-surface-raised border-l-2 border-l-focus';
	});
	let editing = $state(false);
	let draftName = $state('');

	$effect(() => {
		if (!editing) {
			draftName = session.name || 'Chat session';
		}
	});

	async function commitRename(): Promise<void> {
		const trimmed = draftName.trim();
		if (!trimmed) {
			editing = false;
			return;
		}
		editing = false;
		await onRename?.(session.id, trimmed);
	}
</script>

<div
	class="w-full px-3 py-2 border-b border-border-muted hover:bg-surface-raised transition-colors
		focus-within:outline-none focus-within:ring-2 focus-within:ring-focus
		{activeClass}"
	aria-current={active ? 'true' : undefined}
>
	<div
		class="cursor-pointer"
		role="button"
		tabindex="0"
		onclick={() => onSelect(session.id)}
		onkeydown={(event) => {
			if (event.key === 'Enter' || event.key === ' ') {
				event.preventDefault();
				onSelect(session.id);
			}
		}}
	>
		{#if editing}
			<input
				class="w-full rounded border border-border bg-inset px-2 py-1 text-xs text-text-primary focus:outline-none focus:ring-2 focus:ring-focus"
				bind:value={draftName}
				onkeydown={(event) => {
					if (event.key === 'Enter') {
						event.preventDefault();
						void commitRename();
					}
					if (event.key === 'Escape') {
						event.preventDefault();
						editing = false;
					}
				}}
				onblur={() => {
					void commitRename();
				}}
			/>
		{:else}
			<div class="text-sm truncate text-text-primary">{session.name || 'Chat session'}</div>
		{/if}
		<div class="text-xs text-text-muted mt-0.5">
			{session.agentsUsed.join(', ')} -- {session.messageCount} msgs
		</div>
	</div>

	{#if !editing}
		<div class="mt-1 flex items-center gap-2">
			{#if onRename}
				<button
					class="text-[10px] text-text-muted hover:text-text-primary transition-colors"
					type="button"
					onclick={() => {
						editing = true;
					}}
				>
					Rename
				</button>
			{/if}
			{#if onDelete}
				<button
					class="text-[10px] text-text-muted hover:text-error transition-colors"
					type="button"
					onclick={() => {
						void onDelete(session.id);
					}}
				>
					Delete
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.session-active-glow {
		box-shadow:
			inset 0 0 0 1px var(--color-focus),
			0 0 10px color-mix(in srgb, var(--atmosphere-glow-color, var(--color-focus)) 30%, transparent);
	}
</style>
