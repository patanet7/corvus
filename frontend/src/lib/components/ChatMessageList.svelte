<script lang="ts">
	import { tick } from 'svelte';
	import { CHAT_VISIBLE_WINDOW, nextVisibleCount } from '$lib/chat/visible-window';
	import type { AgentInfo, AgentStatus, ChatMessage, ConnectionStatus, Task } from '$lib/types';
	import { WELL_KNOWN_AGENTS } from '$lib/types';
	import { getThemeContext } from '$lib/themes/context';
	import AgentPortrait from './AgentPortrait.svelte';
	import ChatRuntimeStatus from './ChatRuntimeStatus.svelte';
	import ConnectionToast from './ConnectionToast.svelte';
	import ErrorBanner from './ErrorBanner.svelte';
	import MessageContent from './MessageContent.svelte';
	import MessageRuntimeTimeline from './MessageRuntimeTimeline.svelte';
	import ToolCallCard from './ToolCallCard.svelte';

	interface Props {
		messages: ChatMessage[];
		agentStatus: AgentStatus;
		connectionStatus: ConnectionStatus;
		shikiTheme: string;
		onReconnect: () => void;
		loadingTranscript?: boolean;
		transcriptError?: string | null;
		onRetryTranscript?: () => void;
		runtimeTask?: Task | null;
		onOpenToolTrace?: (callId: string) => void;
		availableAgents?: AgentInfo[];
	}

	let {
		messages,
		agentStatus,
		connectionStatus,
		shikiTheme,
		onReconnect,
		loadingTranscript = false,
		transcriptError = null,
		onRetryTranscript,
		runtimeTask = null,
		onOpenToolTrace,
		availableAgents = []
	}: Props = $props();

	const welcomeAgents = $derived(
		availableAgents.length > 0
			? availableAgents.filter((a) => a.id !== 'general')
			: WELL_KNOWN_AGENTS.filter((n) => n !== 'general').map((n) => ({ id: n, label: n, description: undefined } as AgentInfo))
	);
	const themeCtx = getThemeContext();
	const chatMaxWidth = $derived(themeCtx.theme.components.chatPanel.maxWidth);
	const messagePadding = $derived(themeCtx.theme.components.chatPanel.messagePadding);
	let chatContainer: HTMLDivElement | undefined = $state(undefined);
	let visibleCount = $state(120);
	let datasetHeadId = $state<string | null>(null);
	let expandingOlder = $state(false);

	const isStreaming = $derived(agentStatus === 'streaming' || agentStatus === 'thinking');
	const hiddenMessageCount = $derived(Math.max(0, messages.length - visibleCount));
	const visibleMessages = $derived.by(() => {
		const start = Math.max(0, messages.length - visibleCount);
		return messages.slice(start);
	});

	const lastAssistantId = $derived.by(() => {
		for (let i = visibleMessages.length - 1; i >= 0; i--) {
			if (visibleMessages[i]?.role === 'assistant') return visibleMessages[i]?.id;
		}
		return null;
	});

	$effect(() => {
		const headId = messages[0]?.id ?? null;
		const headChanged = headId !== datasetHeadId;
		if (headChanged) {
			datasetHeadId = headId;
		}
		visibleCount = nextVisibleCount({
			messagesLength: messages.length,
			currentVisibleCount: visibleCount,
			datasetHeadChanged: headChanged
		});
	});

	$effect(() => {
		if (visibleMessages.length && chatContainer) {
			const { scrollTop, scrollHeight, clientHeight } = chatContainer;
			const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
			if (isNearBottom) {
				requestAnimationFrame(() => {
					if (chatContainer) {
						chatContainer.scrollTop = chatContainer.scrollHeight;
					}
				});
			}
		}
	});

	async function loadOlderMessages(): Promise<void> {
		if (!chatContainer || hiddenMessageCount === 0 || expandingOlder) return;
		expandingOlder = true;
		const previousHeight = chatContainer.scrollHeight;
		visibleCount = Math.min(messages.length, visibleCount + CHAT_VISIBLE_WINDOW);
		await tick();
		if (chatContainer) {
			const nextHeight = chatContainer.scrollHeight;
			chatContainer.scrollTop += nextHeight - previousHeight;
		}
		expandingOlder = false;
	}

	function handleScroll(): void {
		if (!chatContainer || hiddenMessageCount === 0) return;
		if (chatContainer.scrollTop < 80) {
			void loadOlderMessages();
		}
	}
</script>

<div
	class="relative flex-1 overflow-y-auto py-4"
	style="padding-inline: {messagePadding};"
	bind:this={chatContainer}
	onscroll={handleScroll}
	aria-live="polite"
	aria-relevant="additions"
>
	<ConnectionToast status={connectionStatus} {onReconnect} />
	<div class="mx-auto space-y-4" style="max-width: {chatMaxWidth};">
		<ChatRuntimeStatus
			{agentStatus}
			{runtimeTask}
			onOpenTrace={onOpenToolTrace}
		/>

		{#if loadingTranscript}
			<div class="flex flex-col items-center justify-center py-20 text-center">
				<div class="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-focus"></div>
				<p class="mt-3 text-sm text-text-secondary">Loading session transcript...</p>
			</div>
		{:else if transcriptError}
			<div
				class="rounded border border-error px-4 py-3 text-sm text-text-secondary"
				style="background: color-mix(in srgb, var(--color-error) 10%, transparent);"
			>
				<div class="font-medium text-error">Failed to load session history</div>
				<div class="mt-1">{transcriptError}</div>
				{#if onRetryTranscript}
					<button
						class="mt-3 rounded border border-border px-2 py-1 text-xs text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
						type="button"
						onclick={onRetryTranscript}
					>
						Retry
					</button>
				{/if}
			</div>
		{:else if messages.length === 0}
			<div class="flex flex-col items-center justify-center h-full text-center py-20">
				<AgentPortrait agent="general" size="lg" />
				<h2 class="welcome-heading">Welcome to Corvus</h2>
				<p class="text-text-secondary mt-1 text-sm max-w-md">
					Your messages are automatically routed to the right agent. Just start typing.
				</p>
				<div class="welcome-agent-grid">
					{#each welcomeAgents as agent (agent.id)}
						<div class="welcome-agent-card">
							<AgentPortrait agent={agent.id} size="sm" />
							<span class="welcome-agent-label">{agent.label || agent.id}</span>
						</div>
					{/each}
				</div>
			</div>
		{:else}
			{#if hiddenMessageCount > 0}
				<div class="flex justify-center pb-1">
					<button
						class="rounded-full border border-border px-3 py-1 text-[11px] text-text-secondary hover:border-border-muted hover:text-text-primary"
						type="button"
						onclick={() => {
							void loadOlderMessages();
						}}
					>
						Load {hiddenMessageCount} older message{hiddenMessageCount === 1 ? '' : 's'}
					</button>
				</div>
			{/if}
			{#each visibleMessages as message (message.id)}
				<div
					class="flex gap-3 {message.role === 'user'
						? 'bg-[var(--color-user-message-bg)] -mx-4 px-4 py-3 rounded'
						: ''}"
				>
					{#if message.role === 'assistant' && message.agent}
						<AgentPortrait
							agent={message.agent}
							status={message.id === lastAssistantId && isStreaming ? agentStatus : 'idle'}
							size="lg"
						/>
					{/if}
					<div class="flex-1 min-w-0">
						{#if message.role === 'assistant' && message.agent}
							<div class="flex items-center gap-1.5 mb-1">
								<span
									class="text-xs font-medium"
									style="color: var(--color-agent-{message.agent});"
								>
									@{message.agent}
								</span>
								{#if message.model}
									<span class="text-[10px] px-1 py-px rounded bg-surface-raised text-text-muted border border-border-muted">
										{message.model}
									</span>
								{/if}
							</div>
						{/if}
						{#if message.role === 'assistant' && message.isError}
							<ErrorBanner message={message.content.replace(/^\*\*Error:\*\*\s*/, '')} />
						{:else if message.role === 'assistant'}
							{#if message.runtimeEvents && message.runtimeEvents.length > 0}
								<div class="mb-2">
									<MessageRuntimeTimeline
										events={message.runtimeEvents}
										streaming={isStreaming && message.id === lastAssistantId}
										onOpenTrace={onOpenToolTrace}
									/>
								</div>
							{/if}
							{#if message.content.trim().length > 0 || (isStreaming && message.id === lastAssistantId)}
								<MessageContent
									content={message.content}
									streaming={isStreaming && message.id === lastAssistantId}
									{shikiTheme}
								/>
							{/if}
						{:else}
							<div class="text-sm leading-relaxed whitespace-pre-wrap">
								{message.content}
							</div>
						{/if}
						{#if message.toolCalls && message.toolCalls.length > 0}
							<div class="mt-2">
								{#each message.toolCalls as tc (tc.callId)}
									<ToolCallCard toolCall={tc} onOpenTrace={onOpenToolTrace} />
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{/each}
		{/if}
	</div>
</div>

<style>
	.welcome-heading {
		margin-top: 1rem;
		font-family: var(--font-display);
		font-size: 1.5rem;
		line-height: 2rem;
		font-weight: 500;
	}

	.welcome-agent-grid {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: 0.75rem;
		margin-top: 1.5rem;
		max-width: 500px;
	}

	.welcome-agent-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.375rem;
		width: 90px;
		padding: 0.75rem 0.5rem;
		background: var(--color-surface-raised);
		border: 1px solid var(--color-border-muted);
		border-radius: var(--radius-default, 6px);
	}

	.welcome-agent-label {
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--color-text-secondary);
	}
</style>
