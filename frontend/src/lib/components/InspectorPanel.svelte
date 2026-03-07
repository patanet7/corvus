<script lang="ts">
	import type { AgentInfo, AgentStatus } from '$lib/types';
	import AgentPortrait from './AgentPortrait.svelte';

	interface Props {
		sessionId: string | null;
		activeAgent: string | null;
		agentStatus: AgentStatus;
		agentInfo: AgentInfo | null;
		costUsd: number;
		tokensUsed: number;
		contextPct: number;
		contextLimit: number;
		selectedModel: string;
		messageCount: number;
		visible: boolean;
		onClose: () => void;
	}

	let {
		activeAgent,
		agentStatus,
		agentInfo,
		costUsd,
		tokensUsed,
		contextPct,
		contextLimit,
		selectedModel,
		messageCount,
		visible,
		onClose
	}: Props = $props();

	const contextColor = $derived(
		contextPct < 50
			? 'var(--color-success)'
			: contextPct < 80
				? 'var(--color-warning)'
				: 'var(--color-error)'
	);
</script>

{#if visible}
	<aside
		class="flex flex-col w-[260px] min-w-[260px] border-l border-border bg-surface overflow-y-auto"
		style="font-family: var(--font-mono);"
	>
		<!-- Session Stats -->
		<section class="p-3 border-b border-border">
			<h3 class="text-[10px] uppercase tracking-widest text-text-muted mb-2">Session</h3>
			<div class="grid grid-cols-2 gap-2 text-xs">
				<div>
					<span class="text-text-muted">Messages</span>
					<div class="text-text-primary tabular-nums">{messageCount}</div>
				</div>
				<div>
					<span class="text-text-muted">Cost</span>
					<div class="text-text-primary tabular-nums">${costUsd.toFixed(3)}</div>
				</div>
				<div>
					<span class="text-text-muted">Tokens</span>
					<div class="text-text-primary tabular-nums">{tokensUsed.toLocaleString()}</div>
				</div>
				<div>
					<span class="text-text-muted">Context</span>
					<div class="tabular-nums" style="color: {contextColor};">{contextPct.toFixed(1)}%</div>
				</div>
			</div>
			<!-- Context bar -->
			<div class="mt-2 w-full h-1.5 bg-border-muted rounded-full overflow-hidden">
				<div
					class="h-full rounded-full transition-all duration-300"
					style="width: {Math.min(contextPct, 100)}%; background: {contextColor};"
				></div>
			</div>
			<div class="mt-1 text-[10px] text-text-muted tabular-nums">
				{tokensUsed.toLocaleString()} / {contextLimit.toLocaleString()} tokens
			</div>
		</section>

		<!-- Active Agent Card -->
		{#if activeAgent && agentInfo}
			<section class="p-3 border-b border-border">
				<h3 class="text-[10px] uppercase tracking-widest text-text-muted mb-2">Active Agent</h3>
				<div class="flex items-start gap-3">
					<AgentPortrait agent={activeAgent} status={agentStatus} size="lg" />
					<div class="flex-1 min-w-0">
						<div
							class="text-sm font-medium text-text-primary"
							style="color: var(--color-agent-{activeAgent});"
						>
							@{activeAgent}
						</div>
						<div class="text-xs text-text-secondary mt-0.5">{agentInfo.label}</div>
						{#if agentInfo.description}
							<div class="text-[11px] text-text-muted mt-1 line-clamp-2">
								{agentInfo.description}
							</div>
						{/if}
					</div>
				</div>
				<!-- Model + Backend -->
				<div class="mt-2 flex flex-wrap gap-1">
					<span
						class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-surface-raised text-text-secondary border border-border-muted"
					>
						{selectedModel}
					</span>
					{#if agentInfo.currentModel}
						<span
							class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-surface-raised text-text-muted border border-border-muted"
						>
							{agentInfo.currentModel}
						</span>
					{/if}
				</div>
				<!-- Capabilities -->
				{#if agentInfo.toolModules && agentInfo.toolModules.length > 0}
					<div class="mt-2 flex flex-wrap gap-1">
						{#each agentInfo.toolModules as mod}
							<span
								class="px-1.5 py-0.5 rounded text-[10px] bg-canvas text-text-muted border border-border-muted"
							>
								{mod}
							</span>
						{/each}
					</div>
				{/if}
			</section>
		{/if}

		<!-- Environment Health -->
		<section class="p-3 border-b border-border">
			<h3 class="text-[10px] uppercase tracking-widest text-text-muted mb-2">Environment</h3>
			<div class="grid grid-cols-2 gap-2 text-xs">
				<div>
					<span class="text-text-muted">Gateway</span>
					<div class="flex items-center gap-1">
						<span class="w-1.5 h-1.5 rounded-full bg-success"></span>
						<span class="text-text-secondary">Online</span>
					</div>
				</div>
				<div>
					<span class="text-text-muted">Model</span>
					<div class="text-text-secondary truncate">{selectedModel || 'auto'}</div>
				</div>
			</div>
		</section>

		<!-- Close button -->
		<div class="p-2 mt-auto">
			<button
				class="w-full text-[10px] text-text-muted hover:text-text-secondary py-1 border border-border-muted rounded"
				onclick={onClose}
			>
				Hide Inspector
			</button>
		</div>
	</aside>
{/if}
