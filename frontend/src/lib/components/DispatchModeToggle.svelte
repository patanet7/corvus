<script lang="ts">
	import type { DispatchMode } from '$lib/types';

	interface Props {
		mode: DispatchMode;
		onChange: (mode: DispatchMode) => void;
	}

	let { mode, onChange }: Props = $props();

	const modes: Array<{ id: DispatchMode; label: string; title: string }> = [
		{ id: 'router', label: 'Router', title: 'Huginn auto-routes to the best agent' },
		{ id: 'direct', label: 'Direct', title: 'Send to selected agent only' },
		{ id: 'parallel', label: 'Parallel', title: 'Send to all selected agents simultaneously' }
	];
</script>

<div class="inline-flex rounded border border-border-muted overflow-hidden text-[10px]">
	{#each modes as m (m.id)}
		<button
			class="px-2.5 py-1 transition-colors duration-100
				{mode === m.id
				? 'bg-surface-raised text-text-primary border-border'
				: 'bg-transparent text-text-muted hover:text-text-secondary hover:bg-surface'}"
			class:border-r={m.id !== 'parallel'}
			class:border-border-muted={m.id !== 'parallel'}
			onclick={() => onChange(m.id)}
			title={m.title}
		>
			{m.label}
		</button>
	{/each}
</div>
