<script lang="ts">
	import StatusChip from './primitives/StatusChip.svelte';

	export interface SecurityEvent {
		id: string;
		timestamp: string;
		agent: string;
		action: string;
		detail?: string;
		status: 'queued' | 'allowed' | 'denied' | 'confirm';
		callId?: string;
	}

	interface Props {
		events: SecurityEvent[];
		live?: boolean;
		onApprove?: (eventId: string) => void;
		onDeny?: (eventId: string) => void;
	}

	let { events, live = false, onApprove, onDeny }: Props = $props();

	function toneFor(status: SecurityEvent['status']): 'warning' | 'success' | 'error' | 'neutral' {
		switch (status) {
			case 'allowed':
				return 'success';
			case 'denied':
				return 'error';
			case 'confirm':
				return 'warning';
			default:
				return 'neutral';
		}
	}
</script>

<section class="rounded border border-border-muted bg-surface">
	<div class="flex items-center justify-between border-b border-border-muted px-3 py-2">
		<p class="text-xs font-medium uppercase tracking-wide text-text-primary">Live Security Feed</p>
		<StatusChip label={live ? 'live' : 'offline'} tone={live ? 'success' : 'neutral'} dot />
	</div>
	{#if events.length === 0}
		<div class="px-3 py-4 text-xs text-text-muted">No security events in this scope.</div>
	{:else}
		<div class="max-h-[320px] overflow-y-auto">
			{#each events as event (event.id)}
				<div class="border-b border-border-muted px-3 py-2 last:border-b-0">
					<div class="flex items-start gap-2">
						<span class="shrink-0 font-mono text-[10px] text-text-muted">{event.timestamp}</span>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<span class="text-[11px] text-text-secondary">{event.agent}</span>
								<StatusChip label={event.status} tone={toneFor(event.status)} />
							</div>
							<p class="mt-1 text-xs text-text-primary">{event.action}</p>
							{#if event.detail}
								<p class="mt-0.5 text-[11px] text-text-muted">{event.detail}</p>
							{/if}
							{#if event.callId}
								<p class="mt-0.5 font-mono text-[10px] text-text-muted">{event.callId}</p>
							{/if}
						</div>
						{#if event.status === 'confirm' && (onApprove || onDeny)}
							<div class="flex shrink-0 items-center gap-1">
								{#if onApprove}
									<button
										type="button"
										class="rounded border border-success/50 px-2 py-0.5 text-[10px] text-success"
										onclick={() => onApprove(event.id)}
									>
										Approve
									</button>
								{/if}
								{#if onDeny}
									<button
										type="button"
										class="rounded border border-error/50 px-2 py-0.5 text-[10px] text-error"
										onclick={() => onDeny(event.id)}
									>
										Deny
									</button>
								{/if}
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</section>
