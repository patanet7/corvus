<script lang="ts">
	import type { CapabilityHealth } from '$lib/api/agents';
	import StatusChip from './primitives/StatusChip.svelte';

	export interface ServiceConnection {
		id: string;
		label: string;
		status: 'active' | 'degraded' | 'offline' | 'unknown';
		detail?: string;
	}

	interface Props {
		connections: ServiceConnection[];
		onManage?: (connectionId: string) => void;
	}

	let { connections, onManage }: Props = $props();

	function tone(status: ServiceConnection['status']): 'success' | 'warning' | 'error' | 'neutral' {
		switch (status) {
			case 'active':
				return 'success';
			case 'degraded':
				return 'warning';
			case 'offline':
				return 'error';
			default:
				return 'neutral';
		}
	}

	export function fromCapabilityHealth(
		moduleHealthByName: Record<string, CapabilityHealth>
	): ServiceConnection[] {
		return Object.entries(moduleHealthByName).map(([name, health]) => ({
			id: name,
			label: name,
			status:
				health.status === 'ok' || health.status === 'healthy'
					? 'active'
					: health.status === 'degraded'
						? 'degraded'
						: health.status === 'offline' || health.status === 'error' || health.status === 'unhealthy'
							? 'offline'
							: 'unknown',
			detail: health.message
		}));
	}
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<h4 class="text-xs uppercase tracking-wide text-text-muted">Service Connections</h4>
	<div class="mt-2 space-y-1.5">
		{#if connections.length === 0}
			<div class="rounded border border-border-muted bg-inset px-2 py-2 text-xs text-text-muted">
				No service connections configured.
			</div>
		{:else}
			{#each connections as connection (connection.id)}
				<div class="flex items-center gap-2 rounded border border-border-muted bg-inset px-2 py-1.5">
					<div class="min-w-0 flex-1">
						<p class="text-xs text-text-primary">{connection.label}</p>
						{#if connection.detail}
							<p class="truncate text-[10px] text-text-muted">{connection.detail}</p>
						{/if}
					</div>
					<StatusChip label={connection.status} tone={tone(connection.status)} />
					{#if onManage}
						<button
							type="button"
							class="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary"
							onclick={() => onManage(connection.id)}
						>
							Manage
						</button>
					{/if}
				</div>
			{/each}
		{/if}
	</div>
</section>
