<script lang="ts">
	import ModeRail from '$lib/components/ModeRail.svelte';
	import StatusBar from '$lib/components/StatusBar.svelte';
	import SessionSidebar from '$lib/components/SessionSidebar.svelte';
	import AgentDirectorySidebar from '$lib/components/AgentDirectorySidebar.svelte';
	import AgentWorkspaceShell from '$lib/components/AgentWorkspaceShell.svelte';
	import ChatPanel from '$lib/components/ChatPanel.svelte';
	import TraceTimelinePanel from '$lib/components/TraceTimelinePanel.svelte';
	import MemoryPanel from '$lib/components/MemoryPanel.svelte';
	import ThemeSelector from '$lib/components/ThemeSelector.svelte';
	import TaskSidebar from '$lib/components/TaskSidebar.svelte';
	import TaskDetailPanel from '$lib/components/TaskDetailPanel.svelte';
	import ResizeHandle from '$lib/components/ResizeHandle.svelte';
	import ToastStack from '$lib/components/ToastStack.svelte';
	import {
		createAgent,
		getCapabilityHealth,
		getAgentProfile,
		getAgentPolicy,
		getAgentPromptPreview,
		getAgentTodos,
		listAgents,
		listAgentRuns,
		listAgentSessions,
		listRunEvents,
		type CreateAgentDraft,
		type CapabilityHealth,
		type AgentPromptPreview,
		type AgentPolicyMatrix,
		type AgentProfile,
		type AgentRun,
		type AgentTodoSnapshot,
		type RunEvent
	} from '$lib/api/agents';
	import { pushToast } from '$lib/chat/toasts.svelte';
	import { modelModeLabelForSelection } from '$lib/chat/presenters';
	import {
		isSessionsLoading,
		isTranscriptLoadingForSession,
		sessionsErrorMessage,
		transcriptErrorForSession
	} from '$lib/chat/session-history';
	import {
		defaultSidebarWidths,
		loadSidebarWidths,
		resizedSidebarWidth,
		saveSidebarWidths
	} from '$lib/layout/sidebar-width';
	import {
		connectionStatus,
		currentSession,
		sessions,
		activeConfirm,
		taskStore,
		modelStore,
		agentStore
	} from '$lib/stores.svelte';
	import { onMount } from 'svelte';
	import {
		chatUiState,
		clearPinnedAgent,
		deleteSessionEntry,
		handleNewChat,
		interrupt,
		renameSessionEntry,
		respondToConfirm,
		retryCurrentTranscriptLoad,
		retrySessionListLoad,
		selectSession,
		sendMessage,
		setComposerRecipients,
		setDispatchMode,
		setModeRequestHandler,
		setModelSelection,
		reconnectChatSession,
		startChatSession,
		stopChatSession
	} from '$lib/chat/orchestrator.svelte';
	import type { AppMode } from '$lib/chat/orchestrator.svelte';
	import type { AgentInfo, Session } from '$lib/types';
	import type { AgentWorkspaceTab } from '$lib/components/AgentWorkspaceShell.svelte';

	const BACKEND_DISABLED = import.meta.env.VITE_DISABLE_BACKEND === '1';

	let activeMode = $state<'chat' | 'agents' | 'tasks' | 'timeline' | 'memory' | 'config'>('chat');
	let sidebarWidths = $state(defaultSidebarWidths());
	let initialConnectionStatus = $state(connectionStatus.value);
	let focusedTraceCallId = $state<string | null>(null);
	let agentCreatePending = $state(false);
	let agentCreateError = $state<string | null>(null);
	let agentWorkspace = $state<{
		agents: AgentInfo[];
		profile: AgentProfile | null;
		moduleHealthByName: Record<string, CapabilityHealth>;
		promptPreview: AgentPromptPreview | null;
		promptPreviewLoading: boolean;
		promptPreviewError: string | null;
		agentPolicy: AgentPolicyMatrix | null;
		agentPolicyLoading: boolean;
		agentPolicyError: string | null;
		agentTodos: AgentTodoSnapshot | null;
		agentTodosLoading: boolean;
		agentTodosError: string | null;
		loading: boolean;
		error: string | null;
		activeAgentId: string | null;
		sessions: Session[];
		runs: AgentRun[];
		selectedRunId: string | null;
		runEvents: RunEvent[];
		runEventsLoading: boolean;
		runEventsError: string | null;
		tab: AgentWorkspaceTab;
	}>({
		agents: [],
		profile: null,
		moduleHealthByName: {},
		promptPreview: null,
		promptPreviewLoading: false,
		promptPreviewError: null,
		agentPolicy: null,
		agentPolicyLoading: false,
		agentPolicyError: null,
		agentTodos: null,
		agentTodosLoading: false,
		agentTodosError: null,
		loading: false,
		error: null,
		activeAgentId: null,
		sessions: [],
		runs: [],
		selectedRunId: null,
		runEvents: [],
		runEventsLoading: false,
		runEventsError: null,
		tab: 'chat'
	});

	const sidebarWidth = $derived.by(() => {
		if (activeMode === 'tasks') return sidebarWidths.tasks;
		if (activeMode === 'agents') return sidebarWidths.chat;
		return sidebarWidths.chat;
	});

	function handleSidebarResize(delta: number) {
		if (activeMode !== 'chat' && activeMode !== 'tasks' && activeMode !== 'agents') return;
		const updated = resizedSidebarWidth(sidebarWidth, delta);
		if (activeMode === 'tasks') {
			sidebarWidths.tasks = updated;
		} else {
			sidebarWidths.chat = updated;
		}
		saveSidebarWidths({ chat: sidebarWidths.chat, tasks: sidebarWidths.tasks });
	}

const activeWorkspaceAgent = $derived.by(() =>
		agentWorkspace.agents.find((agent) => agent.id === agentWorkspace.activeAgentId) ?? null
	);

async function loadModuleHealth(
	agent: AgentInfo | null,
	profile: AgentProfile | null
): Promise<Record<string, CapabilityHealth>> {
	const modules = new Set<string>();
	for (const moduleName of profile ? Object.keys(profile.moduleConfig) : []) {
		if (moduleName) modules.add(moduleName);
	}
	for (const moduleName of agent?.toolModules ?? []) {
		if (moduleName) modules.add(moduleName);
	}
	if (modules.size === 0) return {};

	const healthPairs = await Promise.all(
		Array.from(modules).map(async (moduleName) => {
			try {
				const health = await getCapabilityHealth(moduleName);
				return [moduleName, health] as const;
			} catch {
				return [
					moduleName,
					{ name: moduleName, status: 'unknown', message: 'Capability health unavailable' }
				] as const;
			}
		})
	);
	return Object.fromEntries(healthPairs);
}

async function refreshAgentDirectory(): Promise<void> {
	if (BACKEND_DISABLED) {
		agentWorkspace.agents = [];
		agentWorkspace.profile = null;
		agentWorkspace.moduleHealthByName = {};
		agentWorkspace.promptPreview = null;
		agentWorkspace.promptPreviewLoading = false;
		agentWorkspace.promptPreviewError = null;
		agentWorkspace.agentPolicy = null;
		agentWorkspace.agentPolicyLoading = false;
		agentWorkspace.agentPolicyError = null;
		agentWorkspace.agentTodos = null;
		agentWorkspace.agentTodosLoading = false;
		agentWorkspace.agentTodosError = null;
		agentWorkspace.sessions = [];
		agentWorkspace.runs = [];
		agentWorkspace.selectedRunId = null;
		agentWorkspace.runEvents = [];
		agentWorkspace.runEventsLoading = false;
		agentWorkspace.runEventsError = null;
		agentWorkspace.loading = false;
		agentWorkspace.error = null;
		return;
	}
	agentWorkspace.loading = true;
		agentWorkspace.error = null;
		try {
			agentWorkspace.agents = await listAgents();
			if (!agentWorkspace.activeAgentId && agentWorkspace.agents.length > 0) {
				agentWorkspace.activeAgentId = agentWorkspace.agents[0].id;
			}
			if (agentWorkspace.activeAgentId) {
				agentWorkspace.promptPreviewLoading = true;
				agentWorkspace.promptPreviewError = null;
				agentWorkspace.agentPolicyLoading = true;
				agentWorkspace.agentPolicyError = null;
				agentWorkspace.agentTodosLoading = true;
				agentWorkspace.agentTodosError = null;
				const [profile, sessionsForAgent, runsForAgent] = await Promise.all([
					getAgentProfile(agentWorkspace.activeAgentId),
					listAgentSessions(agentWorkspace.activeAgentId, 50),
					listAgentRuns(agentWorkspace.activeAgentId)
				]);
				agentWorkspace.profile = profile;
				const [previewResult, policyResult, todosResult] = await Promise.allSettled([
					getAgentPromptPreview(agentWorkspace.activeAgentId, {
						includeWorkspace: false,
						clipChars: 1200,
						maxChars: 12000
					}),
					getAgentPolicy(agentWorkspace.activeAgentId),
					getAgentTodos(agentWorkspace.activeAgentId, {
						limitFiles: 25,
						limitItems: 250
					})
				]);
				if (previewResult.status === 'fulfilled') {
					agentWorkspace.promptPreview = previewResult.value;
					agentWorkspace.promptPreviewError = null;
				} else {
					agentWorkspace.promptPreview = null;
					agentWorkspace.promptPreviewError = 'Failed to load prompt preview.';
				}
				if (policyResult.status === 'fulfilled') {
					agentWorkspace.agentPolicy = policyResult.value;
					agentWorkspace.agentPolicyError = null;
				} else {
					agentWorkspace.agentPolicy = null;
					agentWorkspace.agentPolicyError = 'Failed to load policy matrix.';
				}
				if (todosResult.status === 'fulfilled') {
					agentWorkspace.agentTodos = todosResult.value;
					agentWorkspace.agentTodosError = null;
				} else {
					agentWorkspace.agentTodos = null;
					agentWorkspace.agentTodosError = 'Failed to load agent todos.';
				}
				const activeAgent =
					agentWorkspace.agents.find((agent) => agent.id === agentWorkspace.activeAgentId) ?? null;
				agentWorkspace.moduleHealthByName = await loadModuleHealth(activeAgent, profile);
				agentWorkspace.sessions = sessionsForAgent;
				agentWorkspace.runs = runsForAgent;
				agentWorkspace.selectedRunId = runsForAgent[0]?.id ?? null;
				if (agentWorkspace.selectedRunId) {
					void selectWorkspaceRun(agentWorkspace.selectedRunId);
				} else {
					agentWorkspace.runEvents = [];
					agentWorkspace.runEventsError = null;
					agentWorkspace.runEventsLoading = false;
				}
				agentWorkspace.promptPreviewLoading = false;
				agentWorkspace.agentPolicyLoading = false;
				agentWorkspace.agentTodosLoading = false;
			}
		} catch (error) {
			console.warn('Failed to load agent directory:', error);
			agentWorkspace.profile = null;
			agentWorkspace.moduleHealthByName = {};
			agentWorkspace.promptPreview = null;
			agentWorkspace.promptPreviewLoading = false;
			agentWorkspace.promptPreviewError = null;
			agentWorkspace.agentPolicy = null;
			agentWorkspace.agentPolicyLoading = false;
			agentWorkspace.agentPolicyError = null;
			agentWorkspace.agentTodos = null;
			agentWorkspace.agentTodosLoading = false;
			agentWorkspace.agentTodosError = null;
			agentWorkspace.error = 'Failed to load agent directory.';
		} finally {
			agentWorkspace.loading = false;
		}
	}

	async function createWorkspaceAgent(draft: CreateAgentDraft): Promise<boolean> {
		agentCreatePending = true;
		agentCreateError = null;
		try {
			await createAgent(draft);
			await refreshAgentDirectory();
			if (draft.name.trim()) {
				await selectWorkspaceAgent(draft.name.trim());
			}
			pushToast(`Created agent @${draft.name.trim()}.`, 'success');
			return true;
		} catch (error) {
			console.warn('Failed to create agent:', error);
			agentCreateError = `Failed to create agent ${draft.name.trim()}.`;
			pushToast(agentCreateError, 'error');
			return false;
		} finally {
			agentCreatePending = false;
		}
	}

async function selectWorkspaceAgent(agentId: string): Promise<void> {
	if (BACKEND_DISABLED) {
		agentWorkspace.activeAgentId = agentId;
		agentWorkspace.profile = null;
		agentWorkspace.moduleHealthByName = {};
		agentWorkspace.promptPreview = null;
		agentWorkspace.promptPreviewLoading = false;
		agentWorkspace.promptPreviewError = null;
		agentWorkspace.agentPolicy = null;
		agentWorkspace.agentPolicyLoading = false;
		agentWorkspace.agentPolicyError = null;
		agentWorkspace.agentTodos = null;
		agentWorkspace.agentTodosLoading = false;
		agentWorkspace.agentTodosError = null;
		agentWorkspace.sessions = [];
		agentWorkspace.runs = [];
		agentWorkspace.selectedRunId = null;
		agentWorkspace.runEvents = [];
		agentWorkspace.runEventsLoading = false;
		agentWorkspace.runEventsError = null;
		agentWorkspace.error = null;
		agentWorkspace.loading = false;
		return;
	}
	agentWorkspace.activeAgentId = agentId;
	agentWorkspace.loading = true;
		agentWorkspace.error = null;
		try {
			agentWorkspace.promptPreviewLoading = true;
			agentWorkspace.promptPreviewError = null;
			agentWorkspace.agentPolicyLoading = true;
			agentWorkspace.agentPolicyError = null;
			agentWorkspace.agentTodosLoading = true;
			agentWorkspace.agentTodosError = null;
			const [profile, sessionsForAgent, runsForAgent] = await Promise.all([
				getAgentProfile(agentId),
				listAgentSessions(agentId, 50),
				listAgentRuns(agentId)
			]);
			agentWorkspace.profile = profile;
			const [previewResult, policyResult, todosResult] = await Promise.allSettled([
				getAgentPromptPreview(agentId, {
					includeWorkspace: false,
					clipChars: 1200,
					maxChars: 12000
				}),
				getAgentPolicy(agentId),
				getAgentTodos(agentId, {
					limitFiles: 25,
					limitItems: 250
				})
			]);
			if (previewResult.status === 'fulfilled') {
				agentWorkspace.promptPreview = previewResult.value;
				agentWorkspace.promptPreviewError = null;
			} else {
				agentWorkspace.promptPreview = null;
				agentWorkspace.promptPreviewError = 'Failed to load prompt preview.';
			}
			if (policyResult.status === 'fulfilled') {
				agentWorkspace.agentPolicy = policyResult.value;
				agentWorkspace.agentPolicyError = null;
			} else {
				agentWorkspace.agentPolicy = null;
				agentWorkspace.agentPolicyError = 'Failed to load policy matrix.';
			}
			if (todosResult.status === 'fulfilled') {
				agentWorkspace.agentTodos = todosResult.value;
				agentWorkspace.agentTodosError = null;
			} else {
				agentWorkspace.agentTodos = null;
				agentWorkspace.agentTodosError = 'Failed to load agent todos.';
			}
			const activeAgent = agentWorkspace.agents.find((agent) => agent.id === agentId) ?? null;
			agentWorkspace.moduleHealthByName = await loadModuleHealth(activeAgent, profile);
			agentWorkspace.sessions = sessionsForAgent;
			agentWorkspace.runs = runsForAgent;
			agentWorkspace.selectedRunId = runsForAgent[0]?.id ?? null;
			if (agentWorkspace.selectedRunId) {
				void selectWorkspaceRun(agentWorkspace.selectedRunId);
			} else {
				agentWorkspace.runEvents = [];
				agentWorkspace.runEventsError = null;
				agentWorkspace.runEventsLoading = false;
			}
			agentWorkspace.promptPreviewLoading = false;
			agentWorkspace.agentPolicyLoading = false;
			agentWorkspace.agentTodosLoading = false;
		} catch (error) {
			console.warn('Failed to load agent workspace:', error);
			agentWorkspace.profile = null;
			agentWorkspace.moduleHealthByName = {};
			agentWorkspace.promptPreview = null;
			agentWorkspace.promptPreviewLoading = false;
			agentWorkspace.promptPreviewError = null;
			agentWorkspace.agentPolicy = null;
			agentWorkspace.agentPolicyLoading = false;
			agentWorkspace.agentPolicyError = null;
			agentWorkspace.agentTodos = null;
			agentWorkspace.agentTodosLoading = false;
			agentWorkspace.agentTodosError = null;
			agentWorkspace.error = `Failed to load workspace for ${agentId}.`;
		} finally {
			agentWorkspace.loading = false;
		}
	}

async function selectWorkspaceRun(runId: string): Promise<void> {
	agentWorkspace.selectedRunId = runId;
	if (BACKEND_DISABLED) {
		agentWorkspace.runEvents = [];
		agentWorkspace.runEventsLoading = false;
		agentWorkspace.runEventsError = null;
		return;
	}
	agentWorkspace.runEventsLoading = true;
	agentWorkspace.runEventsError = null;
	try {
		const events = await listRunEvents(runId, 2000);
		if (agentWorkspace.selectedRunId !== runId) return;
		agentWorkspace.runEvents = events;
	} catch (error) {
		console.warn('Failed to load run events:', error);
		if (agentWorkspace.selectedRunId === runId) {
			agentWorkspace.runEvents = [];
			agentWorkspace.runEventsError = `Failed to load replay events for run ${runId.slice(0, 8)}.`;
		}
	} finally {
		if (agentWorkspace.selectedRunId === runId) {
			agentWorkspace.runEventsLoading = false;
		}
	}
}

	function pinWorkspaceAgent(agentId: string): void {
		setComposerRecipients([agentId], false);
		setDispatchMode('direct');
		activeMode = 'chat';
		pushToast(`Pinned @${agentId} in composer.`, 'success');
	}

	const activeTask = $derived.by(() => {
		if (!taskStore.activeTaskId) return null;
		return taskStore.tasks.get(taskStore.activeTaskId) ?? null;
	});

	const runtimeTask = $derived.by(() => {
		if (activeTask && activeMode === 'tasks') return activeTask;
		const preferredAgent = currentSession.activeAgent;
		const activeSessionId = currentSession.id;
		const candidates = Array.from(taskStore.tasks.values())
			.filter((task) => {
				if (!activeSessionId) return true;
				if (!task.sessionId) return false;
				return task.sessionId === activeSessionId;
			})
			.filter((task) => (preferredAgent ? task.agent === preferredAgent : true))
			.sort((a, b) => b.startedAt.getTime() - a.startedAt.getTime());
		return candidates[0] ?? null;
	});

	const visibleMessages = $derived.by(() => {
		return activeMode === 'tasks' ? (activeTask?.messages ?? []) : currentSession.messages;
	});

	const visibleAgent = $derived.by(() => {
		return activeMode === 'tasks' ? (activeTask?.agent ?? null) : currentSession.activeAgent;
	});

	const visibleSessionName = $derived.by(() => {
		if (activeMode === 'tasks') {
			return activeTask ? `${activeTask.agent} task` : 'Task Monitor';
		}
		return currentSession.name;
	});

	const modelModeLabel = $derived.by(() => {
		return modelModeLabelForSelection(
			chatUiState.modelSelectionMode,
			currentSession.selectedModel,
			modelStore.models
		);
	});

	const sessionsLoading = $derived.by(() => isSessionsLoading(chatUiState.history));
	const sessionsError = $derived.by(() => sessionsErrorMessage(chatUiState.history));
	const transcriptLoading = $derived.by(() =>
		isTranscriptLoadingForSession(chatUiState.history, currentSession.id)
	);
	const transcriptError = $derived.by(() =>
		transcriptErrorForSession(chatUiState.history, currentSession.id)
	);

	onMount(() => {
		sidebarWidths = loadSidebarWidths();
		setModeRequestHandler((mode: AppMode) => {
			activeMode = mode;
		});
		startChatSession();
		if (!BACKEND_DISABLED) {
			void refreshAgentDirectory();
		}
		return () => {
			setModeRequestHandler(null);
			stopChatSession();
		};
	});

	$effect(() => {
		const status = connectionStatus.value;
		if (status === initialConnectionStatus) return;

		if (status === 'connected') {
			pushToast('Chat connection restored.', 'success', { dedupeKey: 'conn:connected' });
		} else if (status === 'disconnected') {
			pushToast('Disconnected from chat backend.', 'warning', { dedupeKey: 'conn:disconnected' });
		} else if (status === 'error') {
			pushToast('Chat connection error. Retrying automatically.', 'error', { dedupeKey: 'conn:error' });
		}

		initialConnectionStatus = status;
	});

	function openToolTrace(callId: string): void {
		const tasksWithTrace = Array.from(taskStore.tasks.values()).filter((task) =>
			(task.events ?? []).some((event) => event.callId === callId)
		);
		if (tasksWithTrace.length === 0) {
			pushToast(`Trace ${callId} not found in task history.`, 'warning', { dedupeKey: `trace:${callId}` });
			return;
		}
		tasksWithTrace.sort((a, b) => b.startedAt.getTime() - a.startedAt.getTime());
		const targetTask = tasksWithTrace[0];
		taskStore.activeTaskId = targetTask.id;
		focusedTraceCallId = callId;
		activeMode = 'tasks';
		pushToast(`Opened trace ${callId}.`, 'success', { dedupeKey: `trace:open:${callId}` });
	}
</script>

<div class="flex flex-col h-full">
	<ToastStack />
	<StatusBar
		connectionStatus={connectionStatus.value}
		activeAgent={currentSession.activeAgent}
		sessionName={currentSession.name}
		costUsd={currentSession.costUsd}
		tokensUsed={currentSession.tokensUsed}
		contextPct={currentSession.contextPct}
	/>

	<div class="flex flex-1 min-h-0">
		<ModeRail {activeMode} onModeChange={(m) => (activeMode = m)} />

		{#if activeMode === 'chat'}
			<SessionSidebar
				sessions={sessions.list}
				activeSessionId={currentSession.id}
				width={sidebarWidth}
				loading={sessionsLoading}
				error={sessionsError}
				onSelectSession={(id) => {
					void selectSession(id);
				}}
				onRenameSession={(id, name) => {
					void renameSessionEntry(id, name);
				}}
				onDeleteSession={(id) => {
					void deleteSessionEntry(id);
				}}
				onNewChat={handleNewChat}
				onRetryLoad={retrySessionListLoad}
			/>
			<ResizeHandle onResize={handleSidebarResize} />
		{:else if activeMode === 'agents'}
			<AgentDirectorySidebar
				agents={agentWorkspace.agents}
				activeAgentId={agentWorkspace.activeAgentId}
				width={sidebarWidth}
				loading={agentWorkspace.loading}
				error={agentWorkspace.error}
				creatingAgent={agentCreatePending}
				createError={agentCreateError}
				onSelectAgent={(agentId) => {
					void selectWorkspaceAgent(agentId);
				}}
				onRefresh={() => {
					void refreshAgentDirectory();
				}}
				onCreateAgent={createWorkspaceAgent}
			/>
			<ResizeHandle onResize={handleSidebarResize} />
		{:else if activeMode === 'tasks'}
			<TaskSidebar
				width={sidebarWidth}
				onSelectTask={(taskId) => {
					taskStore.activeTaskId = taskId;
					focusedTraceCallId = null;
				}}
				onInterruptTask={(taskId) => {
					taskStore.activeTaskId = taskId;
					focusedTraceCallId = null;
					interrupt();
				}}
			/>
			<ResizeHandle onResize={handleSidebarResize} />
		{:else if activeMode === 'config'}
			<ThemeSelector />
		{/if}

		{#if activeMode === 'chat' || activeMode === 'tasks'}
			<div class="flex flex-1 min-w-0">
				<ChatPanel
					messages={visibleMessages}
					activeAgent={visibleAgent}
					agentStatus={currentSession.agentStatus}
					connectionStatus={connectionStatus.value}
					sessionName={visibleSessionName}
					activeConfirmRequest={activeConfirm.request}
					models={modelStore.models}
					selectedModel={currentSession.selectedModel}
					contextPct={currentSession.contextPct}
					modelModeLabel={modelModeLabel}
					availableAgents={agentStore.agents}
					pinnedAgent={chatUiState.pinnedAgent}
					dispatchMode={chatUiState.dispatchMode}
					selectedRecipients={chatUiState.selectedRecipients}
					sendToAllRecipients={chatUiState.sendToAllRecipients}
					transcriptLoading={activeMode === 'chat' ? transcriptLoading : false}
					transcriptError={activeMode === 'chat' ? transcriptError : null}
					runtimeTask={runtimeTask}
					onModelChange={setModelSelection}
					onDispatchModeChange={setDispatchMode}
					onRecipientsChange={setComposerRecipients}
					onSendMessage={sendMessage}
					onInterrupt={interrupt}
					onConfirmRespond={respondToConfirm}
					onClearPinnedAgent={clearPinnedAgent}
					onReconnect={reconnectChatSession}
					onRetryTranscript={() => {
						void retryCurrentTranscriptLoad();
					}}
					onOpenToolTrace={openToolTrace}
				/>
				{#if activeMode === 'tasks'}
					<TaskDetailPanel
						task={activeTask}
						traceCallId={focusedTraceCallId}
						onInterrupt={interrupt}
						onClearTraceFocus={() => {
							focusedTraceCallId = null;
						}}
					/>
				{/if}
			</div>
		{:else if activeMode === 'agents'}
			<AgentWorkspaceShell
				agent={activeWorkspaceAgent}
				agentProfile={agentWorkspace.profile}
				moduleHealthByName={agentWorkspace.moduleHealthByName}
				promptPreview={agentWorkspace.promptPreview}
				promptPreviewLoading={agentWorkspace.promptPreviewLoading}
				promptPreviewError={agentWorkspace.promptPreviewError}
				agentPolicy={agentWorkspace.agentPolicy}
				agentPolicyLoading={agentWorkspace.agentPolicyLoading}
				agentPolicyError={agentWorkspace.agentPolicyError}
				agentTodos={agentWorkspace.agentTodos}
				agentTodosLoading={agentWorkspace.agentTodosLoading}
				agentTodosError={agentWorkspace.agentTodosError}
				tab={agentWorkspace.tab}
				sessions={agentWorkspace.sessions}
				runs={agentWorkspace.runs}
				selectedRunId={agentWorkspace.selectedRunId}
				runEvents={agentWorkspace.runEvents}
				runEventsLoading={agentWorkspace.runEventsLoading}
				runEventsError={agentWorkspace.runEventsError}
				onTabChange={(tab) => {
					agentWorkspace.tab = tab;
				}}
				onSelectSession={(sessionId) => {
					void selectSession(sessionId);
					activeMode = 'chat';
				}}
				onSelectRun={(runId) => {
					void selectWorkspaceRun(runId);
				}}
				onPinAgent={pinWorkspaceAgent}
			/>
		{:else if activeMode === 'timeline'}
			<TraceTimelinePanel sessionId={currentSession.id} backendDisabled={BACKEND_DISABLED} />
		{:else if activeMode === 'memory'}
			<MemoryPanel backendDisabled={BACKEND_DISABLED} />
		{/if}
	</div>
</div>
