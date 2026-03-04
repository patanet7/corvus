<script lang="ts">
	import StatusChip from './StatusChip.svelte';

	interface Props {
		eventType: string;
		count?: number;
	}

	let { eventType, count = 0 }: Props = $props();

	const tone = $derived.by<'neutral' | 'success' | 'warning' | 'error' | 'info'>(() => {
		if (eventType.startsWith('run_') || eventType === 'routing') return 'info';
		if (eventType.startsWith('task_') || eventType === 'done') return 'success';
		if (eventType.startsWith('tool_') || eventType.startsWith('confirm_')) return 'warning';
		if (eventType === 'error') return 'error';
		return 'neutral';
	});

	const label = $derived.by(() => {
		if (count > 0) return `${eventType} ${count}`;
		return eventType;
	});
</script>

<StatusChip {label} {tone} />
