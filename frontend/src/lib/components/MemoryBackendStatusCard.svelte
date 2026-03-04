<script lang="ts">
	import type { MemoryBackendConfig, MemoryBackendsStatus, MemoryBackendHealth } from '$lib/api/memory';
	import StatusChip from '$lib/components/primitives/StatusChip.svelte';

	interface Props {
		status: MemoryBackendsStatus | null;
		loading?: boolean;
		error?: string | null;
		onRefresh?: () => void | Promise<void>;
	}

	let { status, loading = false, error = null, onRefresh }: Props = $props();

	type OverlayRow = {
		config: MemoryBackendConfig;
		health: MemoryBackendHealth | null;
	};

	const overlayRows = $derived.by<OverlayRow[]>(() => {
		if (!status) return [];
		const health = status.overlays ?? [];
		return (status.configuredOverlays ?? []).map((config) => {
			const match =
				health.find((row) => row.name === config.name) ??
				health.find((row) => row.name.startsWith(config.name));
			return { config, health: match ?? null };
		});
	});

	function toneForStatus(state: string): 'neutral' | 'success' | 'warning' | 'error' {
		if (state === 'healthy') return 'success';
		if (state === 'unhealthy') return 'error';
		if (state === 'disabled') return 'neutral';
		return 'warning';
	}

	function statusLabel(row: OverlayRow): string {
		if (!row.config.enabled) return 'disabled';
		if (!row.health) return 'unavailable';
		return row.health.status;
	}
</script>

<div class="rounded border border-border-muted bg-surface p-3 text-xs">
	<div class="flex items-center justify-between gap-2">
		<div>
			<div class="text-[10px] uppercase tracking-wide text-text-muted">Memory Backends</div>
			<div class="mt-1 text-sm font-semibold text-text-primary">Primary + Overlay Health</div>
		</div>
		{#if onRefresh}
			<button
				type="button"
				class="rounded border border-border px-2 py-1 text-[11px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
				onclick={() => {
					void onRefresh?.();
				}}
			>
				Refresh
			</button>
		{/if}
	</div>

	{#if loading}
		<div class="mt-3 text-text-muted">Loading backend status...</div>
	{:else if error}
		<div class="mt-3 rounded border border-error/50 bg-error/10 px-2 py-1 text-error">{error}</div>
	{:else if !status}
		<div class="mt-3 text-text-muted">No backend status available.</div>
	{:else}
		<div class="mt-3 space-y-2">
			<div class="rounded border border-border-muted bg-inset px-2 py-2">
				<div class="flex items-center justify-between gap-2">
					<div class="font-medium text-text-primary">Primary: {status.primary.name}</div>
					<StatusChip
						label={status.primary.status}
						tone={toneForStatus(status.primary.status)}
						dot={true}
					/>
				</div>
				{#if status.primary.detail}
					<div class="mt-1 text-[11px] text-text-muted">{status.primary.detail}</div>
				{/if}
			</div>

			<div class="space-y-2">
				<div class="text-[10px] uppercase tracking-wide text-text-muted">Configured Overlays</div>
				{#if overlayRows.length === 0}
					<div class="rounded border border-border-muted bg-inset px-2 py-2 text-text-muted">
						No overlays configured.
					</div>
				{:else}
					{#each overlayRows as row (row.config.name)}
						<div class="rounded border border-border-muted bg-inset px-2 py-2">
							<div class="flex items-center justify-between gap-2">
								<div class="font-medium text-text-primary">{row.config.name}</div>
								<StatusChip
									label={statusLabel(row)}
									tone={toneForStatus(statusLabel(row))}
									dot={true}
								/>
							</div>
							<div class="mt-1 text-[11px] text-text-muted">weight {row.config.weight.toFixed(2)}</div>
							{#if row.health?.consecutiveFailures !== undefined && row.health.consecutiveFailures > 0}
								<div class="mt-1 text-[11px] text-warning">
									consecutive failures: {row.health.consecutiveFailures}
								</div>
							{/if}
							{#if row.health?.detail}
								<div class="mt-1 text-[11px] text-text-muted">{row.health.detail}</div>
							{/if}
						</div>
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>
