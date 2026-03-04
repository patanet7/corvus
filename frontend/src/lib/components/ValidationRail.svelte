<script lang="ts">
	import MetricCard from './primitives/MetricCard.svelte';
	import SectionAccordion from './primitives/SectionAccordion.svelte';
	import StatusChip from './primitives/StatusChip.svelte';

	export interface ValidationMetrics {
		totalRuns: number;
		errorRatePct: number;
		avgCostUsd: number;
		uptimePct: number;
	}

	export interface ValidationDependency {
		id: string;
		status: 'ok' | 'missing' | 'degraded';
		detail?: string;
	}

	export interface ValidationQuota {
		id: string;
		label: string;
		used: number;
		limit: number;
	}

	export interface ValidationAuditRow {
		id: string;
		timestamp: string;
		message: string;
		severity: 'info' | 'warning' | 'error';
	}

	interface Props {
		metrics: ValidationMetrics;
		dependencies?: ValidationDependency[];
		quotas?: ValidationQuota[];
		auditRows?: ValidationAuditRow[];
	}

	let { metrics, dependencies = [], quotas = [], auditRows = [] }: Props = $props();

	function depTone(status: ValidationDependency['status']): 'success' | 'warning' | 'error' {
		switch (status) {
			case 'ok':
				return 'success';
			case 'degraded':
				return 'warning';
			default:
				return 'error';
		}
	}

	function severityTone(level: ValidationAuditRow['severity']): 'info' | 'warning' | 'error' {
		if (level === 'error') return 'error';
		if (level === 'warning') return 'warning';
		return 'info';
	}
</script>

<section class="space-y-2">
	<div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
		<MetricCard title="Runs" value={metrics.totalRuns} />
		<MetricCard title="Error Rate" value={`${metrics.errorRatePct.toFixed(1)}%`} tone={metrics.errorRatePct > 5 ? 'warning' : 'success'} />
		<MetricCard title="Avg Cost" value={`$${metrics.avgCostUsd.toFixed(2)}`} />
		<MetricCard title="Uptime" value={`${metrics.uptimePct.toFixed(1)}%`} tone={metrics.uptimePct < 95 ? 'warning' : 'success'} />
	</div>

	<SectionAccordion title="Skill Dependencies" badge={`${dependencies.length}`} defaultOpen>
		<div class="space-y-1">
			{#if dependencies.length === 0}
				<p class="text-xs text-text-muted">No dependency checks reported.</p>
			{:else}
				{#each dependencies as dependency (dependency.id)}
					<div class="flex items-center gap-2 rounded border border-border-muted bg-inset px-2 py-1">
						<StatusChip label={dependency.status} tone={depTone(dependency.status)} />
						<div class="min-w-0 flex-1">
							<p class="text-xs text-text-primary">{dependency.id}</p>
							{#if dependency.detail}
								<p class="truncate text-[10px] text-text-muted">{dependency.detail}</p>
							{/if}
						</div>
					</div>
				{/each}
			{/if}
		</div>
	</SectionAccordion>

	<SectionAccordion title="Quota" badge={`${quotas.length}`}>
		<div class="space-y-1">
			{#if quotas.length === 0}
				<p class="text-xs text-text-muted">No quota data available.</p>
			{:else}
				{#each quotas as quota (quota.id)}
					{@const pct = quota.limit <= 0 ? 0 : Math.min(100, (quota.used / quota.limit) * 100)}
					<div class="rounded border border-border-muted bg-inset px-2 py-1.5">
						<div class="flex items-center justify-between text-[11px]">
							<span class="text-text-secondary">{quota.label}</span>
							<span class="font-mono text-text-muted">{quota.used}/{quota.limit}</span>
						</div>
						<div class="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-raised">
							<div
								class={`h-full ${pct >= 90 ? 'bg-error' : pct >= 70 ? 'bg-warning' : 'bg-success'}`}
								style={`width:${pct}%`}
							></div>
						</div>
					</div>
				{/each}
			{/if}
		</div>
	</SectionAccordion>

	<SectionAccordion title="Audit Log" badge={`${auditRows.length}`}>
		<div class="max-h-48 space-y-1 overflow-y-auto pr-1">
			{#if auditRows.length === 0}
				<p class="text-xs text-text-muted">No audit rows recorded for this scope.</p>
			{:else}
				{#each auditRows as row (row.id)}
					<div class="rounded border border-border-muted bg-inset px-2 py-1.5">
						<div class="flex items-center gap-2">
							<span class="font-mono text-[10px] text-text-muted">{row.timestamp}</span>
							<StatusChip label={row.severity} tone={severityTone(row.severity)} />
						</div>
						<p class="mt-1 text-xs text-text-secondary">{row.message}</p>
					</div>
				{/each}
			{/if}
		</div>
	</SectionAccordion>
</section>
