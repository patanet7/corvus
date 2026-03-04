<script lang="ts">
	import type {
		ChatMessage,
		AgentName,
		AgentStatus,
		ConfirmRequest,
		ConnectionStatus,
		DispatchMode,
		ModelInfo,
		AgentInfo,
		Task
	} from '$lib/types';
	import { getThemeContext } from '$lib/themes/context';
	import ChatComposer from './ChatComposer.svelte';
	import ChatHeaderBar from './ChatHeaderBar.svelte';
	import ChatMessageList from './ChatMessageList.svelte';
	import ConfirmCard from './ConfirmCard.svelte';

	const themeCtx = getThemeContext();
	const shikiTheme = $derived(themeCtx.theme.components.codeBlock.shikiTheme);

	interface Props {
		messages: ChatMessage[];
		activeAgent: AgentName | null;
		agentStatus: AgentStatus;
		connectionStatus: ConnectionStatus;
		sessionName: string;
		activeConfirmRequest: ConfirmRequest | null;
		models: ModelInfo[];
		selectedModel: string;
		contextPct: number;
		modelModeLabel: string;
		availableAgents: AgentInfo[];
		pinnedAgent: AgentName | null;
		dispatchMode: DispatchMode;
		selectedRecipients: string[];
		sendToAllRecipients: boolean;
		transcriptLoading?: boolean;
		transcriptError?: string | null;
		runtimeTask?: Task | null;
		onModelChange: (modelId: string) => void;
		onDispatchModeChange: (mode: DispatchMode) => void;
		onRecipientsChange: (recipients: string[], sendToAll: boolean) => void;
		onSendMessage: (message: string) => void;
		onInterrupt: () => void;
		onConfirmRespond: (callId: string, approved: boolean) => void;
		onClearPinnedAgent: () => void;
		onReconnect: () => void;
		onRetryTranscript?: () => void;
		onOpenToolTrace?: (callId: string) => void;
	}

	let {
		messages,
		activeAgent,
		agentStatus,
		connectionStatus,
		sessionName,
		activeConfirmRequest,
		models,
		selectedModel,
		contextPct,
		modelModeLabel,
		availableAgents,
		pinnedAgent,
		dispatchMode,
		selectedRecipients,
		sendToAllRecipients,
		transcriptLoading = false,
		transcriptError = null,
		runtimeTask = null,
		onModelChange,
		onDispatchModeChange,
		onRecipientsChange,
		onSendMessage,
		onInterrupt,
		onConfirmRespond,
		onClearPinnedAgent,
		onReconnect,
		onRetryTranscript,
		onOpenToolTrace
	}: Props = $props();

	const isStreaming = $derived(agentStatus === 'streaming' || agentStatus === 'thinking');
	const activeAgentInfo = $derived.by(() => {
		const agentId = activeAgent ?? pinnedAgent;
		if (!agentId) return null;
		return availableAgents.find((agent) => agent.id === agentId) ?? null;
	});
</script>

<div class="flex flex-col flex-1 min-w-0">
	<ChatHeaderBar
		{activeAgent}
		{agentStatus}
		{sessionName}
		{pinnedAgent}
		{activeAgentInfo}
		{selectedModel}
		{models}
		{contextPct}
		{onClearPinnedAgent}
	/>

	<ChatMessageList
		{messages}
		{agentStatus}
		{connectionStatus}
		{shikiTheme}
		{onReconnect}
		loadingTranscript={transcriptLoading}
		{transcriptError}
		onRetryTranscript={onRetryTranscript}
		{runtimeTask}
		onOpenToolTrace={onOpenToolTrace}
	/>

	<ChatComposer
		{models}
		{selectedModel}
		{modelModeLabel}
		{availableAgents}
		{dispatchMode}
		{selectedRecipients}
		{sendToAllRecipients}
		{isStreaming}
		{onModelChange}
		{onDispatchModeChange}
		{onRecipientsChange}
		{onSendMessage}
		{onInterrupt}
	/>
</div>

{#if activeConfirmRequest}
	<ConfirmCard confirmRequest={activeConfirmRequest} onRespond={onConfirmRespond} />
{/if}
