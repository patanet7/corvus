<script lang="ts">
	export interface SecurityDomainItem {
		id: string;
		label: string;
		count: number;
		icon?: string;
		sensitivity?: 'low' | 'medium' | 'high';
	}

	export interface SecurityAgentScope {
		id: string;
		status?: 'active' | 'idle' | 'offline';
	}

	interface Props {
		domains: SecurityDomainItem[];
		selectedDomainId?: string | null;
		agentScopes?: SecurityAgentScope[];
		onSelectDomain?: (domainId: string) => void;
	}

	let { domains, selectedDomainId = null, agentScopes = [], onSelectDomain }: Props = $props();

	function sensitivityClass(level: SecurityDomainItem['sensitivity']): string {
		switch (level) {
			case 'high':
				return 'text-error';
			case 'medium':
				return 'text-warning';
			default:
				return 'text-text-muted';
		}
	}

	function agentDotClass(status: SecurityAgentScope['status']): string {
		switch (status) {
			case 'active':
				return 'bg-success';
			case 'offline':
				return 'bg-error';
			default:
				return 'bg-border-emphasis';
		}
	}
</script>

<aside class="rounded border border-border-muted bg-surface p-2">
	<p class="px-2 text-[10px] uppercase tracking-wide text-text-muted">Security Domains</p>
	<div class="mt-2 space-y-1">
		{#if domains.length === 0}
			<div class="rounded border border-border-muted bg-inset px-2 py-2 text-xs text-text-muted">
				No domain policy data.
			</div>
		{:else}
			{#each domains as domain (domain.id)}
				<button
					type="button"
					class={`flex w-full items-center justify-between rounded border px-2 py-1.5 text-left transition-colors ${selectedDomainId === domain.id ? 'border-focus bg-surface-raised text-text-primary' : 'border-transparent text-text-secondary hover:border-border-muted hover:bg-inset hover:text-text-primary'}`}
					onclick={() => onSelectDomain?.(domain.id)}
				>
					<div class="min-w-0">
						<div class="flex items-center gap-2 text-xs">
							<span class="font-mono text-[11px]">{domain.icon ?? '[]'}</span>
							<span class="truncate">{domain.label}</span>
						</div>
						{#if domain.sensitivity}
							<div class={`text-[10px] ${sensitivityClass(domain.sensitivity)}`}>
								{domain.sensitivity} sensitivity
							</div>
						{/if}
					</div>
					<span class="rounded border border-border-muted px-1.5 py-0.5 text-[10px] text-text-muted">
						{domain.count}
					</span>
				</button>
			{/each}
		{/if}
	</div>

	{#if agentScopes.length > 0}
		<div class="mt-3 border-t border-border-muted pt-2">
			<p class="px-2 text-[10px] uppercase tracking-wide text-text-muted">Agents</p>
			<div class="mt-1 space-y-1 px-2">
				{#each agentScopes as scope (scope.id)}
					<div class="flex items-center gap-2 text-xs text-text-secondary">
						<span class={`h-1.5 w-1.5 rounded-full ${agentDotClass(scope.status)}`}></span>
						<span>{scope.id}</span>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</aside>
