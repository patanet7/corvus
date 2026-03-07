<script lang="ts">
import type { AgentInfo, DispatchMode, DraftAttachment, ModelInfo } from '$lib/types';
import { getThemeContext } from '$lib/themes/context';
import { agentSuggestionSource } from '$lib/chat/presenters';
import { pushToast } from '$lib/chat/toasts.svelte';
import AgentPickerStrip from './AgentPickerStrip.svelte';
import ComposerCapabilityRail from './ComposerCapabilityRail.svelte';
import DispatchModeToggle from './DispatchModeToggle.svelte';
import ModelSelector from './ModelSelector.svelte';
import SuggestionOverlay from './SuggestionOverlay.svelte';
import RecipientPicker from './RecipientPicker.svelte';

	interface Props {
		models: ModelInfo[];
		selectedModel: string;
		modelModeLabel: string;
		availableAgents: AgentInfo[];
		dispatchMode: DispatchMode;
		selectedRecipients: string[];
		sendToAllRecipients: boolean;
		isStreaming: boolean;
		onModelChange: (modelId: string) => void;
		onDispatchModeChange: (mode: DispatchMode) => void;
		onRecipientsChange: (recipients: string[], sendToAll: boolean) => void;
		onSendMessage: (message: string) => void;
		onInterrupt: () => void;
	}

	let {
		models,
		selectedModel,
		modelModeLabel,
		availableAgents,
		dispatchMode,
		selectedRecipients,
		sendToAllRecipients,
		isStreaming,
		onModelChange,
		onDispatchModeChange,
		onRecipientsChange,
		onSendMessage,
		onInterrupt
	}: Props = $props();
	const themeCtx = getThemeContext();
	const chatMaxWidth = $derived(themeCtx.theme.components.chatPanel.maxWidth);

	let inputValue = $state('');
	let inputElement: HTMLTextAreaElement | undefined = $state(undefined);
	let imageInput: HTMLInputElement | undefined = $state(undefined);
	let audioInput: HTMLInputElement | undefined = $state(undefined);
	let fileInput: HTMLInputElement | undefined = $state(undefined);
	let activeSuggestionIndex = $state(0);
	let stagedAttachments = $state<DraftAttachment[]>([]);

	const slashCommandSuggestions: Array<{
		id: string;
		insert: string;
		description: string;
	}> = [
		{ id: 'new', insert: '/new', description: 'Start a new chat' },
		{ id: 'clear', insert: '/clear', description: 'Clear current transcript' },
		{ id: 'sessions', insert: '/sessions', description: 'Open session history' },
		{ id: 'agents', insert: '/agents', description: 'Open agents workspace' },
		{ id: 'tasks', insert: '/tasks', description: 'Open tasks workspace' },
		{ id: 'timeline', insert: '/timeline', description: 'Open trace timeline' },
		{ id: 'memory', insert: '/memory', description: 'Open memory workspace' },
		{ id: 'config', insert: '/config', description: 'Open settings' },
		{ id: 'agent', insert: '/agent ', description: 'Pin agent for next turns' },
		{ id: 'dispatch', insert: '/dispatch ', description: 'Set dispatch mode' },
		{ id: 'model', insert: '/model ', description: 'Set model override' },
		{ id: 'skill', insert: '/skill ', description: 'Run skill command' },
		{ id: 'help', insert: '/help', description: 'Show available commands' }
	];

	const modKey = $derived(
		typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent) ? 'Cmd' : 'Ctrl'
	);

	function autoGrow() {
		if (!inputElement) return;
		inputElement.style.height = 'auto';
		inputElement.style.height = Math.min(inputElement.scrollHeight, 200) + 'px';
	}

	function focusComposer(): void {
		requestAnimationFrame(() => {
			inputElement?.focus();
			autoGrow();
		});
	}

	function applyAgentSuggestion(agent: string): void {
		const leftPadding = inputValue.match(/^\s*/)?.[0] ?? '';
		inputValue = `${leftPadding}@${agent} `;
		focusComposer();
	}

	function applySlashSuggestion(insert: string): void {
		const leftPadding = inputValue.match(/^\s*/)?.[0] ?? '';
		inputValue = `${leftPadding}${insert}`;
		focusComposer();
	}

	function handleSend() {
		const msg = inputValue.trim();
		if (!msg) return;
		if (stagedAttachments.length > 0) {
			pushToast('Attachments are staged in UI; backend ingestion is not wired yet.', 'warning', {
				dedupeKey: 'attachments-staged'
			});
			stagedAttachments = [];
		}
		onSendMessage(msg);
		inputValue = '';
		if (inputElement) inputElement.style.height = 'auto';
	}

	function createAttachmentId(): string {
		if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
			return crypto.randomUUID();
		}
		return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
	}

	function stageFiles(kind: DraftAttachment['kind'], fileList: FileList | null): void {
		if (!fileList || fileList.length === 0) return;
		const next = Array.from(fileList).map((file) => ({
			id: createAttachmentId(),
			kind,
			name: file.name,
			sizeBytes: file.size,
			mimeType: file.type || undefined
		}));
		stagedAttachments = [...stagedAttachments, ...next];
		pushToast(`Staged ${next.length} ${kind} attachment${next.length > 1 ? 's' : ''}.`, 'success');
	}

	function removeStagedAttachment(attachmentId: string): void {
		stagedAttachments = stagedAttachments.filter((attachment) => attachment.id !== attachmentId);
	}

	function openImagePicker(): void {
		imageInput?.click();
	}

	function openAudioPicker(): void {
		audioInput?.click();
	}

	function openFilePicker(): void {
		fileInput?.click();
	}

	function stageVoiceCapture(): void {
		pushToast('Voice capture controls are staged. Streaming voice backend wiring is next.', 'warning', {
			dedupeKey: 'voice-staged'
		});
	}

	const leftTrimmedInput = $derived(inputValue.trimStart());

	const mentionQuery = $derived.by(() => {
		if (!leftTrimmedInput.startsWith('@') || leftTrimmedInput.startsWith('@@')) return null;
		if (leftTrimmedInput.includes(' ')) return null;
		return leftTrimmedInput.slice(1).toLowerCase();
	});

	const mentionSuggestions = $derived.by(() => {
		if (mentionQuery === null) return [];
		const source = agentSuggestionSource(availableAgents);
		return source.filter((id) => id.toLowerCase().includes(mentionQuery)).slice(0, 8);
	});

	const slashQuery = $derived.by(() => {
		if (!leftTrimmedInput.startsWith('/')) return null;
		if (leftTrimmedInput.includes(' ')) return null;
		return leftTrimmedInput.slice(1).toLowerCase();
	});

	const slashSuggestions = $derived.by(() => {
		if (slashQuery === null) return [];
		return slashCommandSuggestions.filter((cmd) => cmd.id.startsWith(slashQuery)).slice(0, 8);
	});

	type SuggestionItem =
		| { kind: 'agent'; id: string; label: string; description: string }
		| { kind: 'slash'; id: string; label: string; insert: string; description: string };

	const suggestionItems = $derived.by<SuggestionItem[]>(() => {
		if (mentionSuggestions.length > 0) {
			return mentionSuggestions.map((id) => ({
				kind: 'agent',
				id,
				label: `@${id}`,
				description: `Route message to ${id}`
			}));
		}
		return slashSuggestions.map((cmd) => ({
			kind: 'slash',
			id: cmd.id,
			label: `/${cmd.id}`,
			insert: cmd.insert,
			description: cmd.description
		}));
	});

	function commitActiveSuggestion(): void {
		const selected = suggestionItems[activeSuggestionIndex];
		if (!selected) return;
		if (selected.kind === 'agent') {
			applyAgentSuggestion(selected.id);
			return;
		}
		applySlashSuggestion(selected.insert);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (suggestionItems.length > 0) {
			if (e.key === 'ArrowDown') {
				e.preventDefault();
				activeSuggestionIndex = (activeSuggestionIndex + 1) % suggestionItems.length;
				return;
			}
			if (e.key === 'ArrowUp') {
				e.preventDefault();
				activeSuggestionIndex =
					(activeSuggestionIndex - 1 + suggestionItems.length) % suggestionItems.length;
				return;
			}
			if (e.key === 'Enter' && !e.shiftKey) {
				e.preventDefault();
				commitActiveSuggestion();
				return;
			}
			if (e.key === 'Tab') {
				e.preventDefault();
				commitActiveSuggestion();
				return;
			}
			if (e.key === 'Escape') {
				e.preventDefault();
				activeSuggestionIndex = 0;
				return;
			}
		}

		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSend();
		}
		if (e.key === '.' && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			onInterrupt();
		}
	}

	function handleGlobalKeydown(e: KeyboardEvent) {
		if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement)?.tagName)) {
			e.preventDefault();
			inputElement?.focus();
		}
		if (e.key === '.' && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			onInterrupt();
		}
	}

	$effect(() => {
		if (activeSuggestionIndex >= suggestionItems.length) {
			activeSuggestionIndex = 0;
		}
	});
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

<div class="border-t border-border p-3">
	<div class="mx-auto relative" style="max-width: {chatMaxWidth};">
		<RecipientPicker
			{availableAgents}
			selectedRecipients={selectedRecipients}
			sendToAll={sendToAllRecipients}
			{onRecipientsChange}
		/>

		<!-- Visible dispatch mode + agent picker -->
		<div class="flex items-center gap-2 py-1 mb-1">
			<DispatchModeToggle mode={dispatchMode} onChange={onDispatchModeChange} />
			{#if dispatchMode !== 'router'}
				<AgentPickerStrip
					agents={availableAgents}
					{selectedRecipients}
					{dispatchMode}
					onToggleAgent={(agentId) => {
						const current = [...selectedRecipients];
						const idx = current.indexOf(agentId);
						if (idx >= 0) {
							current.splice(idx, 1);
						} else {
							if (dispatchMode === 'direct') {
								onRecipientsChange([agentId], false);
								return;
							}
							current.push(agentId);
						}
						onRecipientsChange(current, false);
					}}
				/>
			{/if}
		</div>

		<ComposerCapabilityRail
			attachments={stagedAttachments}
			onVoiceClick={stageVoiceCapture}
			onImagePickClick={openImagePicker}
			onAudioPickClick={openAudioPicker}
			onFilePickClick={openFilePicker}
			onRemoveAttachment={removeStagedAttachment}
		/>

		<input
			class="hidden"
			type="file"
			accept="image/*"
			multiple
			bind:this={imageInput}
			onchange={(event) => {
				const target = event.currentTarget as HTMLInputElement | null;
				stageFiles('image', target?.files ?? null);
				if (target) target.value = '';
			}}
		/>

		<input
			class="hidden"
			type="file"
			accept="audio/*"
			multiple
			bind:this={audioInput}
			onchange={(event) => {
				const target = event.currentTarget as HTMLInputElement | null;
				stageFiles('audio', target?.files ?? null);
				if (target) target.value = '';
			}}
		/>

		<input
			class="hidden"
			type="file"
			multiple
			bind:this={fileInput}
			onchange={(event) => {
				const target = event.currentTarget as HTMLInputElement | null;
				stageFiles('file', target?.files ?? null);
				if (target) target.value = '';
			}}
		/>

		{#if suggestionItems.length > 0}
			<div class="absolute left-0 right-0 bottom-[calc(100%+0.5rem)] z-20">
				<SuggestionOverlay
					items={suggestionItems.map((item) => ({
						id: `${item.kind}-${item.id}`,
						label: item.label,
						description: item.description
					}))}
					activeIndex={activeSuggestionIndex}
					onSelect={(idx) => {
						activeSuggestionIndex = idx;
						commitActiveSuggestion();
					}}
				/>
			</div>
		{/if}

		<div class="flex gap-2">
			<textarea
				class="flex-1 bg-inset border border-border rounded-lg px-3 py-2 text-sm text-text-primary
					placeholder:text-text-muted resize-none focus:outline-none focus:ring-2 focus:ring-focus"
				style="max-height: 200px; overflow-y: auto;"
				placeholder="Message Corvus..."
				aria-label="Send a message to Corvus"
				rows={1}
				bind:value={inputValue}
				bind:this={inputElement}
				onkeydown={handleKeydown}
				oninput={autoGrow}
			></textarea>
			{#if isStreaming}
				<button
					class="w-9 h-9 flex items-center justify-center rounded-full bg-error text-[var(--color-text-on-accent)] hover:brightness-110 transition-all"
					onclick={onInterrupt}
					title="Stop ({modKey}+.)"
					aria-label="Stop generation"
				>
					<svg class="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
						<rect x="3" y="3" width="10" height="10" rx="1" />
					</svg>
				</button>
			{/if}
			<button
				class="w-9 h-9 flex items-center justify-center rounded-full text-[var(--color-text-on-accent)] transition-all
					{inputValue.trim() && !isStreaming
						? 'bg-focus hover:brightness-110'
						: 'bg-border-muted cursor-not-allowed opacity-40'}"
				onclick={handleSend}
				disabled={!inputValue.trim() || isStreaming}
				title={isStreaming ? 'Replying...' : 'Send (Enter)'}
				aria-label="Send message"
			>
				{#if isStreaming}
					<svg class="w-4 h-4 animate-spin" viewBox="0 0 16 16" fill="none" aria-hidden="true">
						<circle
							cx="8"
							cy="8"
							r="6"
							stroke="currentColor"
							stroke-opacity="0.35"
							stroke-width="2"
						></circle>
						<path d="M8 2a6 6 0 0 1 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path>
					</svg>
				{:else}
					<svg
						class="w-4 h-4"
						viewBox="0 0 16 16"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
					>
						<path d="M8 12V4M4 7l4-4 4 4" />
					</svg>
				{/if}
			</button>
		</div>
	</div>
	<div class="mx-auto flex items-center justify-between mt-1" style="max-width: {chatMaxWidth};">
		{#if models.length > 0}
			<ModelSelector {models} {selectedModel} modeLabel={modelModeLabel} {onModelChange} />
		{:else}
			<span></span>
		{/if}
		<div class="text-xs text-text-muted">
			<kbd class="text-[10px] px-1 py-0.5 bg-surface rounded">Enter</kbd> send
			<kbd class="text-[10px] px-1 py-0.5 bg-surface rounded ml-1">Shift+Enter</kbd> newline
			<kbd class="text-[10px] px-1 py-0.5 bg-surface rounded ml-1">{modKey}+.</kbd> stop
		</div>
	</div>
	<div class="mx-auto mt-1 text-[11px] text-text-muted" style="max-width: {chatMaxWidth};">
		Voice and uploads are staged at UI level; backend ingestion and media streaming are pending.
	</div>
</div>
