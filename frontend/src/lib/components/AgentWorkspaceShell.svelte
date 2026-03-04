<script lang="ts">
	import type { AgentInfo, Session } from '$lib/types';
	import type {
		AgentProfile,
		AgentRun,
		CapabilityHealth,
		RunEvent,
		AgentPromptPreview,
		AgentPolicyMatrix,
		AgentPolicyEntry,
		AgentTodoSnapshot
	} from '$lib/api/agents';
	import AgentSpecialtyAccess from './AgentSpecialtyAccess.svelte';
	import AgentIdentityCard from './AgentIdentityCard.svelte';
	import AgentPromptIdentityCard from './AgentPromptIdentityCard.svelte';
	import AgentToolsPermissionsCard from './AgentToolsPermissionsCard.svelte';
	import AgentConnectionsCard from './AgentConnectionsCard.svelte';
	import AgentPermissionsMatrixCard from './AgentPermissionsMatrixCard.svelte';
	import PromptInspectorPanel from './PromptInspectorPanel.svelte';
	import RunReplayTimeline from './RunReplayTimeline.svelte';
	import DispatchCommandBar from './DispatchCommandBar.svelte';
	import TaskMetricsRibbon from './TaskMetricsRibbon.svelte';
	import TaskFilterBar from './TaskFilterBar.svelte';
	import TaskRunCard from './TaskRunCard.svelte';
	import ExecutionTimelineView from './ExecutionTimelineView.svelte';
	import InlineDiffReviewCard from './InlineDiffReviewCard.svelte';
	import AgentIdentityBlueprintCard from './AgentIdentityBlueprintCard.svelte';
	import AgentSkillMatrixCard from './AgentSkillMatrixCard.svelte';
	import AgentModelRoutingCard from './AgentModelRoutingCard.svelte';
	import ServiceConnectionsCard from './ServiceConnectionsCard.svelte';
	import ValidationRail from './ValidationRail.svelte';
	import SecurityDomainSidebar from './SecurityDomainSidebar.svelte';
	import PermissionPolicyCard from './PermissionPolicyCard.svelte';
	import SecurityEventFeed from './SecurityEventFeed.svelte';
	import PermissionDecisionFeedCard from './PermissionDecisionFeedCard.svelte';

	export type AgentWorkspaceTab = 'chat' | 'tasks' | 'config' | 'validation';

	type TaskRunCardVariant = 'log-stream' | 'progress' | 'diff-preview';

	interface TaskMetric {
		id: string;
		label: string;
		value: string | number;
		hint?: string;
		tone?: 'neutral' | 'success' | 'warning' | 'error' | 'info';
	}

	interface TimelineBlock {
		id: string;
		kind: 'prompt' | 'tool' | 'output' | 'diff' | 'phase';
		title: string;
		content: string;
		meta?: string;
		timestamp?: string;
	}

	interface ServiceConnection {
		id: string;
		label: string;
		status: 'active' | 'degraded' | 'offline' | 'unknown';
		detail?: string;
	}

	interface ValidationMetrics {
		totalRuns: number;
		errorRatePct: number;
		avgCostUsd: number;
		uptimePct: number;
	}

	interface ValidationDependency {
		id: string;
		status: 'ok' | 'missing' | 'degraded';
		detail?: string;
	}

	interface ValidationQuota {
		id: string;
		label: string;
		used: number;
		limit: number;
	}

	interface ValidationAuditRow {
		id: string;
		timestamp: string;
		message: string;
		severity: 'info' | 'warning' | 'error';
	}

	interface SecurityDomainItem {
		id: string;
		label: string;
		count: number;
		icon?: string;
		sensitivity?: 'low' | 'medium' | 'high';
	}

	interface SecurityEvent {
		id: string;
		timestamp: string;
		agent: string;
		action: string;
		detail?: string;
		status: 'queued' | 'allowed' | 'denied' | 'confirm';
		callId?: string;
	}

	interface PermissionDecisionEvent {
		id: string;
		timestamp: string;
		agent: string;
		tool: string;
		state: 'allow' | 'deny' | 'confirm';
		scope?: string;
		reason?: string;
	}

	interface Props {
		agent: AgentInfo | null;
		agentProfile?: AgentProfile | null;
		moduleHealthByName?: Record<string, CapabilityHealth>;
		promptPreview?: AgentPromptPreview | null;
		promptPreviewLoading?: boolean;
		promptPreviewError?: string | null;
		agentPolicy?: AgentPolicyMatrix | null;
		agentPolicyLoading?: boolean;
		agentPolicyError?: string | null;
		agentTodos?: AgentTodoSnapshot | null;
		agentTodosLoading?: boolean;
		agentTodosError?: string | null;
		tab: AgentWorkspaceTab;
		sessions: Session[];
		runs: AgentRun[];
		selectedRunId: string | null;
		runEvents: RunEvent[];
		runEventsLoading?: boolean;
		runEventsError?: string | null;
		onTabChange: (tab: AgentWorkspaceTab) => void;
		onSelectSession: (sessionId: string) => void;
		onSelectRun: (runId: string) => void;
		onPinAgent: (agentId: string) => void;
	}

	let {
		agent,
		agentProfile = null,
		moduleHealthByName = {},
		promptPreview = null,
		promptPreviewLoading = false,
		promptPreviewError = null,
		agentPolicy = null,
		agentPolicyLoading = false,
		agentPolicyError = null,
		agentTodos = null,
		agentTodosLoading = false,
		agentTodosError = null,
		tab,
		sessions,
		runs,
		selectedRunId,
		runEvents,
		runEventsLoading = false,
		runEventsError = null,
		onTabChange,
		onSelectSession,
		onSelectRun,
		onPinAgent
	}: Props = $props();

	let runSearch = $state('');
	let selectedRunStates = $state<string[]>([]);
	let selectedRunAgents = $state<string[]>([]);
	let dispatchPaused = $state(false);
	let selectedPolicyDomainId = $state<string | null>(null);

	const runStatusOptions = $derived.by(() =>
		Array.from(new Set(runs.map((run) => run.status).filter((status) => status.length > 0))).sort((a, b) =>
			a.localeCompare(b)
		)
	);

	const runAgentOptions = $derived.by(() =>
		Array.from(new Set(runs.map((run) => run.agent).filter((agentId) => agentId.length > 0))).sort((a, b) =>
			a.localeCompare(b)
		)
	);

	const filteredRuns = $derived.by(() => {
		const q = runSearch.trim().toLowerCase();
		return runs.filter((run) => {
			if (selectedRunStates.length > 0 && !selectedRunStates.includes(run.status)) return false;
			if (selectedRunAgents.length > 0 && !selectedRunAgents.includes(run.agent)) return false;
			if (!q) return true;
			return (
				run.agent.toLowerCase().includes(q) ||
				run.status.toLowerCase().includes(q) ||
				(run.summary ?? '').toLowerCase().includes(q) ||
				(run.model ?? '').toLowerCase().includes(q)
			);
		});
	});

	const taskMetrics = $derived.by<TaskMetric[]>(() => {
		const active = runs.filter((run) => !['done', 'success', 'error'].includes(run.status)).length;
		const avgContext =
			runs.length === 0 ? 0 : runs.reduce((sum, run) => sum + (run.context_pct ?? 0), 0) / runs.length;
		const spend = runs.reduce((sum, run) => sum + (run.cost_usd ?? 0), 0);
		const tokenTotal = runs.reduce((sum, run) => sum + (run.tokens_used ?? 0), 0);
		return [
			{ id: 'active', label: 'Active Runs', value: active, tone: active > 0 ? 'info' : 'neutral' },
			{ id: 'spend', label: 'Run Spend', value: `$${spend.toFixed(2)}` },
			{ id: 'tokens', label: 'Tokens', value: tokenTotal.toLocaleString() },
			{
				id: 'context',
				label: 'Avg Context',
				value: `${avgContext.toFixed(1)}%`,
				tone: avgContext >= 85 ? 'warning' : 'success'
			}
		];
	});

	function toggleArrayItem(list: string[], value: string): string[] {
		return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
	}

	function clearRunFilters(): void {
		runSearch = '';
		selectedRunStates = [];
		selectedRunAgents = [];
	}

	function runVariant(run: AgentRun): TaskRunCardVariant {
		if ((run.summary ?? '').toLowerCase().includes('diff')) return 'diff-preview';
		if (['done', 'success'].includes(run.status)) return 'progress';
		return 'log-stream';
	}

	function runStatusLabel(run: AgentRun): 'running' | 'done' | 'error' {
		if (run.status === 'error') return 'error';
		if (['done', 'success'].includes(run.status)) return 'done';
		return 'running';
	}

	function elapsedLabel(run: AgentRun): string {
		const start = new Date(run.started_at);
		const end = run.completed_at ? new Date(run.completed_at) : new Date();
		const seconds = Math.max(0, Math.floor((end.getTime() - start.getTime()) / 1000));
		const mins = Math.floor(seconds / 60);
		const rem = seconds % 60;
		if (mins <= 0) return `${rem}s`;
		return `${mins}m ${rem}s`;
	}

	function modelLogsForRun(run: AgentRun): string[] {
		return runEvents
			.filter((event) => event.run_id === run.id && event.event_type === 'run_output_chunk')
			.map((event) => {
				const content = event.payload.content;
				return typeof content === 'string' && content.trim().length > 0
					? content.trim()
					: `chunk ${String(event.payload.chunk_index ?? '?')}`;
			})
			.slice(-4);
	}

	const timelineBlocks = $derived.by<TimelineBlock[]>(() => {
		return runEvents.slice(0, 120).map((event) => {
			const text =
				typeof event.payload.summary === 'string'
					? event.payload.summary
					: typeof event.payload.content === 'string'
						? event.payload.content
						: JSON.stringify(event.payload);
			const kind: TimelineBlock['kind'] =
				event.event_type === 'run_phase'
					? 'phase'
					: event.event_type === 'run_output_chunk'
						? 'output'
						: event.event_type.includes('tool') || event.event_type.includes('confirm')
							? 'tool'
							: 'prompt';
			return {
				id: String(event.id),
				kind,
				title: event.event_type,
				content: text,
				meta: event.run_id,
				timestamp: new Date(event.created_at).toLocaleTimeString([], {
					hour: '2-digit',
					minute: '2-digit',
					second: '2-digit'
				})
			};
		});
	});

	const diffPreviewLines = $derived.by(() => {
		const diffEvent = runEvents.find((event) => {
			const content = event.payload.content;
			return typeof content === 'string' && content.includes('@@');
		});
		if (!diffEvent) return [];
		const content = diffEvent.payload.content;
		if (typeof content !== 'string') return [];
		return content.split('\n').slice(0, 20);
	});

	const serviceConnections = $derived.by<ServiceConnection[]>(() => {
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
	});

	const policyDomains = $derived.by<SecurityDomainItem[]>(() => {
		if (!agentPolicy) return [];
		const counts = new Map<string, number>();
		for (const entry of agentPolicy.entries) {
			const scope = entry.scope || 'global';
			counts.set(scope, (counts.get(scope) ?? 0) + 1);
		}
		return Array.from(counts.entries()).map(([scope, count]) => ({
			id: scope,
			label: scope,
			count,
			icon: scope.slice(0, 2).toUpperCase(),
			sensitivity: scope.includes('memory') ? 'high' : scope.includes('module') ? 'medium' : 'low'
		}));
	});

	$effect(() => {
		if (policyDomains.length === 0) {
			selectedPolicyDomainId = null;
			return;
		}
		if (!selectedPolicyDomainId || !policyDomains.some((domain) => domain.id === selectedPolicyDomainId)) {
			selectedPolicyDomainId = policyDomains[0].id;
		}
	});

	const visiblePolicyEntries = $derived.by(() => {
		if (!agentPolicy) return [];
		if (!selectedPolicyDomainId) return agentPolicy.entries;
		return agentPolicy.entries.filter((entry) => entry.scope === selectedPolicyDomainId);
	});

	function riskForPolicy(entry: AgentPolicyEntry): 'low' | 'medium' | 'high' | 'critical' {
		if (entry.state === 'deny') return 'critical';
		if (entry.state === 'confirm') return 'high';
		if (entry.scope.includes('memory')) return 'medium';
		return 'low';
	}

	function trustForPolicy(entry: AgentPolicyEntry): number {
		if (entry.state === 'allow') return 92;
		if (entry.state === 'confirm') return 55;
		return 10;
	}

	function todoStatusTone(status: string): 'default' | 'success' | 'warning' {
		if (status === 'completed') return 'success';
		if (status === 'in_progress') return 'warning';
		return 'default';
	}

	const securityEvents = $derived.by<SecurityEvent[]>(() => {
		return runEvents
			.slice(-120)
			.reverse()
			.map((event) => {
				const permissionState =
					event.event_type === 'tool_permission_decision' &&
					typeof event.payload.state === 'string'
						? event.payload.state
						: null;
				const status: SecurityEvent['status'] =
					event.event_type === 'tool_permission_decision' && permissionState === 'confirm'
						? 'confirm'
						: event.event_type === 'tool_permission_decision' && permissionState === 'allow'
							? 'allowed'
							: event.event_type === 'tool_permission_decision' && permissionState === 'deny'
								? 'denied'
								: event.event_type === 'confirm_request'
						? 'confirm'
						: event.event_type === 'tool_result' && event.payload.status === 'error'
							? 'denied'
							: event.event_type === 'tool_result' || event.event_type === 'run_complete'
								? 'allowed'
								: 'queued';
				return {
					id: String(event.id),
					timestamp: new Date(event.created_at).toLocaleTimeString([], {
						hour: '2-digit',
						minute: '2-digit',
						second: '2-digit'
					}),
					agent: event.payload.agent && typeof event.payload.agent === 'string' ? event.payload.agent : 'agent',
					action:
						event.event_type === 'tool_permission_decision'
							? `tool_permission_decision (${permissionState ?? 'deny'})`
							: event.event_type,
					detail:
						typeof event.payload.summary === 'string'
							? event.payload.summary
							: typeof event.payload.reason === 'string'
								? event.payload.reason
								: typeof event.payload.content === 'string'
									? event.payload.content.slice(0, 140)
									: '',
					status,
					callId:
						typeof event.payload.call_id === 'string'
							? event.payload.call_id
							: typeof event.payload.callId === 'string'
								? event.payload.callId
								: undefined
				};
			});
	});

	const permissionDecisionEvents = $derived.by<PermissionDecisionEvent[]>(() =>
		runEvents
			.filter((event) => event.event_type === 'tool_permission_decision')
			.slice(-120)
			.reverse()
			.map((event) => {
				const rawState = typeof event.payload.state === 'string' ? event.payload.state : 'deny';
				const state: PermissionDecisionEvent['state'] =
					rawState === 'allow' || rawState === 'confirm' ? rawState : 'deny';
				return {
					id: String(event.id),
					timestamp: new Date(event.created_at).toLocaleTimeString([], {
						hour: '2-digit',
						minute: '2-digit',
						second: '2-digit'
					}),
					agent:
						typeof event.payload.agent === 'string'
							? event.payload.agent
							: agent?.id ?? 'agent',
					tool: typeof event.payload.tool === 'string' ? event.payload.tool : 'tool',
					state,
					scope: typeof event.payload.scope === 'string' ? event.payload.scope : undefined,
					reason: typeof event.payload.reason === 'string' ? event.payload.reason : undefined
				};
			})
	);

	const validationMetrics = $derived.by<ValidationMetrics>(() => {
		const total = runs.length;
		const errors = runs.filter((run) => run.status === 'error').length;
		const errorRate = total > 0 ? (errors / total) * 100 : 0;
		const avgCost = total > 0 ? runs.reduce((sum, run) => sum + run.cost_usd, 0) / total : 0;
		const uptime = Math.max(0, 100 - errorRate);
		return {
			totalRuns: total,
			errorRatePct: errorRate,
			avgCostUsd: avgCost,
			uptimePct: uptime
		};
	});

	const validationDependencies = $derived.by<ValidationDependency[]>(() =>
		Object.entries(moduleHealthByName).map(([name, health]) => ({
			id: name,
			status:
				health.status === 'ok' || health.status === 'healthy'
					? 'ok'
					: health.status === 'degraded'
						? 'degraded'
						: 'missing',
			detail: health.message
		}))
	);

	const validationQuotas = $derived.by<ValidationQuota[]>(() => {
		if (runs.length === 0) return [];
		const latest = runs[0];
		return [
			{
				id: 'context',
				label: 'Context Window',
				used: Math.round(latest.context_pct),
				limit: 100
			},
			{
				id: 'tokens',
				label: 'Tokens / Run',
				used: Math.round(latest.tokens_used),
				limit: Math.max(1, latest.context_limit || latest.tokens_used || 1)
			}
		];
	});

	const validationAuditRows = $derived.by<ValidationAuditRow[]>(() =>
		securityEvents.slice(0, 40).map((event) => ({
			id: event.id,
			timestamp: event.timestamp,
			message: `${event.agent}: ${event.action}`,
			severity: event.status === 'denied' ? 'error' : event.status === 'confirm' ? 'warning' : 'info'
		}))
	);
</script>

<section class="flex min-w-0 flex-1 flex-col">
	<div class="border-b border-border-muted bg-surface px-3 py-2">
		<div class="flex items-center gap-2">
			<h2 class="text-sm font-medium text-text-primary">
				{agent ? `${agent.label} Workspace` : 'Agent Workspace'}
			</h2>
			{#if agent}
				<button
					type="button"
					class="rounded border border-border px-2 py-0.5 text-[11px] text-text-secondary transition-colors hover:border-border-muted hover:text-text-primary"
					onclick={() => onPinAgent(agent.id)}
				>
					Pin @{agent.id}
				</button>
			{/if}
		</div>
		{#if agent}
			<div class="mt-2">
				<AgentSpecialtyAccess {agent} />
			</div>
		{/if}
		<div class="mt-2 flex items-center gap-1 text-[11px]">
			<button
				type="button"
				class="rounded border px-2 py-0.5 {tab === 'chat'
					? 'border-focus bg-surface-raised text-text-primary'
					: 'border-border-muted text-text-secondary hover:text-text-primary'}"
				onclick={() => onTabChange('chat')}
			>
				Chat
			</button>
			<button
				type="button"
				class="rounded border px-2 py-0.5 {tab === 'tasks'
					? 'border-focus bg-surface-raised text-text-primary'
					: 'border-border-muted text-text-secondary hover:text-text-primary'}"
				onclick={() => onTabChange('tasks')}
			>
				Tasks
			</button>
			<button
				type="button"
				class="rounded border px-2 py-0.5 {tab === 'config'
					? 'border-focus bg-surface-raised text-text-primary'
					: 'border-border-muted text-text-secondary hover:text-text-primary'}"
				onclick={() => onTabChange('config')}
			>
				Config
			</button>
			<button
				type="button"
				class="rounded border px-2 py-0.5 {tab === 'validation'
					? 'border-focus bg-surface-raised text-text-primary'
					: 'border-border-muted text-text-secondary hover:text-text-primary'}"
				onclick={() => onTabChange('validation')}
			>
				Validation
			</button>
		</div>
	</div>

	<div class="min-h-0 flex-1 overflow-y-auto p-3">
		{#if !agent}
			<div class="text-sm text-text-muted">Select an agent from the directory.</div>
		{:else if tab === 'chat'}
			<div class="space-y-2">
				<h3 class="text-xs uppercase tracking-wide text-text-muted">Recent Sessions</h3>
				{#if sessions.length === 0}
					<div class="text-sm text-text-muted">No sessions for this agent yet.</div>
				{:else}
					{#each sessions as session (session.id)}
						<button
							type="button"
							class="w-full rounded border border-border-muted bg-surface px-3 py-2 text-left transition-colors hover:border-border"
							onclick={() => onSelectSession(session.id)}
						>
							<div class="text-sm text-text-primary">
								{session.name ?? `Session ${session.id.slice(0, 8)}`}
							</div>
							<div class="mt-1 text-[11px] text-text-muted">
								{session.messageCount} messages • {session.startedAt}
							</div>
						</button>
					{/each}
				{/if}
			</div>
		{:else if tab === 'tasks'}
			<div class="space-y-3">
				<DispatchCommandBar
					activeCount={runs.filter((run) => !['done', 'success', 'error'].includes(run.status)).length}
					paused={dispatchPaused}
					onPauseToggle={() => {
						dispatchPaused = !dispatchPaused;
					}}
				/>
				<TaskMetricsRibbon metrics={taskMetrics} />
				<TaskFilterBar
					search={runSearch}
					statusOptions={runStatusOptions}
					selectedStatuses={selectedRunStates}
					agentOptions={runAgentOptions}
					selectedAgents={selectedRunAgents}
					onSearchChange={(value) => {
						runSearch = value;
					}}
					onStatusToggle={(status) => {
						selectedRunStates = toggleArrayItem(selectedRunStates, status);
					}}
					onAgentToggle={(agentId) => {
						selectedRunAgents = toggleArrayItem(selectedRunAgents, agentId);
					}}
					onClear={clearRunFilters}
				/>
				<div class="grid min-h-0 gap-3 xl:grid-cols-[360px,minmax(0,1fr)]">
					<div class="space-y-2">
						<h3 class="text-xs uppercase tracking-wide text-text-muted">Runs</h3>
						{#if filteredRuns.length === 0}
							<div class="rounded border border-border-muted bg-surface px-3 py-3 text-sm text-text-muted">
								No runs match the current filters.
							</div>
						{:else}
							<div class="max-h-[680px] space-y-2 overflow-y-auto pr-1">
								{#each filteredRuns as run (run.id)}
									<button
										type="button"
										class="w-full rounded border p-0 text-left transition-colors {selectedRunId === run.id
											? 'border-focus bg-surface-raised'
											: 'border-border-muted bg-surface hover:border-border'}"
										onclick={() => onSelectRun(run.id)}
									>
										<TaskRunCard
											variant={runVariant(run)}
											title={run.summary ?? run.id}
											agent={run.agent}
											model={run.model ?? undefined}
											status={runStatusLabel(run)}
											elapsedLabel={elapsedLabel(run)}
											summary={run.summary ?? ''}
											progressPct={run.context_pct}
											logLines={modelLogsForRun(run)}
											diffLines={diffPreviewLines}
										/>
									</button>
								{/each}
							</div>
						{/if}
					</div>
					<div class="space-y-3">
						<RunReplayTimeline events={runEvents} loading={runEventsLoading} error={runEventsError} />
						<ExecutionTimelineView blocks={timelineBlocks} />
						{#if diffPreviewLines.length > 0}
							<InlineDiffReviewCard filePath="runtime-generated.diff" hunks={[{ header: '@@ runtime @@', lines: diffPreviewLines }]} />
						{/if}
					</div>
				</div>
			</div>
		{:else if tab === 'config'}
			<div class="space-y-3 text-sm text-text-secondary">
				<div class="rounded border border-border-muted bg-surface px-3 py-2">
					<div class="text-xs uppercase tracking-wide text-text-muted">Specialty Access</div>
					<div class="mt-1">
						<AgentSpecialtyAccess {agent} />
					</div>
				</div>
				<div class="grid gap-3 xl:grid-cols-3">
					<AgentIdentityBlueprintCard {agent} profile={agentProfile} />
					<AgentSkillMatrixCard {agent} profile={agentProfile} />
					<AgentModelRoutingCard {agent} profile={agentProfile} />
					<ServiceConnectionsCard connections={serviceConnections} />
					<AgentIdentityCard {agent} profile={agentProfile} />
					<AgentPromptIdentityCard {agent} profile={agentProfile} />
					<AgentToolsPermissionsCard {agent} profile={agentProfile} />
					<AgentConnectionsCard {agent} profile={agentProfile} {moduleHealthByName} />
					<AgentPermissionsMatrixCard
						{agent}
						policy={agentPolicy}
						loading={agentPolicyLoading}
						error={agentPolicyError}
					/>
				</div>
				<PermissionDecisionFeedCard
					events={permissionDecisionEvents}
					loading={runEventsLoading}
					error={runEventsError}
				/>
				<div class="grid gap-3 xl:grid-cols-[220px,minmax(0,1fr)]">
					<SecurityDomainSidebar
						domains={policyDomains}
						selectedDomainId={selectedPolicyDomainId}
						agentScopes={[{ id: agent.id, status: agent.runtimeStatus === 'offline' ? 'offline' : 'active' }]}
						onSelectDomain={(domainId) => {
							selectedPolicyDomainId = domainId;
						}}
					/>
					<div class="space-y-2">
						{#if visiblePolicyEntries.length === 0}
							<div class="rounded border border-border-muted bg-surface px-3 py-2 text-xs text-text-muted">
								No policy rows for this domain.
							</div>
						{:else}
							<div class="grid gap-2 md:grid-cols-2">
								{#each visiblePolicyEntries as entry (entry.key)}
									<PermissionPolicyCard
										toolId={entry.subject}
										description={entry.scope}
										state={entry.state === 'allow' || entry.state === 'confirm' || entry.state === 'deny' ? entry.state : 'deny'}
										risk={riskForPolicy(entry)}
										trustScore={trustForPolicy(entry)}
										requiresConfirm={entry.state === 'confirm'}
										reason={entry.reason}
									/>
								{/each}
							</div>
						{/if}
					</div>
				</div>
				<PromptInspectorPanel preview={promptPreview} loading={promptPreviewLoading} error={promptPreviewError} />
				<div class="rounded border border-border-muted bg-surface px-3 py-3">
					<div class="flex flex-wrap items-center gap-2">
						<h4 class="text-xs uppercase tracking-wide text-text-muted">Runtime Todos</h4>
						{#if agentTodos}
							<span class="rounded border border-border-muted px-2 py-0.5 text-[11px] text-text-muted">
								Scope: {agentTodos.scope}
							</span>
							<span class="rounded border border-border-muted px-2 py-0.5 text-[11px] text-text-muted">
								Files: {agentTodos.totals.files}
							</span>
							<span class="rounded border border-border-muted px-2 py-0.5 text-[11px] text-text-muted">
								Open: {agentTodos.totals.pending + agentTodos.totals.inProgress}
							</span>
							<span class="rounded border border-border-muted px-2 py-0.5 text-[11px] text-text-muted">
								Done: {agentTodos.totals.completed}
							</span>
						{/if}
					</div>
					{#if agentTodosLoading}
						<div class="mt-2 text-xs text-text-muted">Loading todo artifacts…</div>
					{:else if agentTodosError}
						<div class="mt-2 text-xs text-danger">{agentTodosError}</div>
					{:else if !agentTodos || agentTodos.files.length === 0}
						<div class="mt-2 text-xs text-text-muted">No todo artifacts captured yet for this agent.</div>
					{:else}
						<div class="mt-3 space-y-2">
							{#each agentTodos.files as file (file.id)}
								<div class="rounded border border-border-muted bg-surface-raised px-2 py-2">
									<div class="flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
										<span class="font-medium text-text-primary">{file.sessionId ?? file.id}</span>
										<span>{file.itemCount} items</span>
										<span>{new Date(file.updatedAt).toLocaleString()}</span>
									</div>
									{#if file.items.length > 0}
										<ul class="mt-2 space-y-1">
											{#each file.items as item (item.id)}
												<li class="rounded border border-border-muted/60 px-2 py-1 text-xs">
													<div class="flex items-start justify-between gap-2">
														<span class="text-text-primary">{item.content}</span>
														<span class="rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide {todoStatusTone(item.status) === 'success'
															? 'bg-success-subtle text-success'
															: todoStatusTone(item.status) === 'warning'
																? 'bg-warning-subtle text-warning'
																: 'bg-surface text-text-muted'}">
															{item.status.replace('_', ' ')}
														</span>
													</div>
													{#if item.activeForm}
														<div class="mt-1 text-[11px] text-text-muted">{item.activeForm}</div>
													{/if}
												</li>
											{/each}
										</ul>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
				<div class="rounded border border-border-muted bg-surface px-3 py-2 text-[12px]">
					Config edits remain backend-managed; this pane is read-only for now.
				</div>
			</div>
		{:else}
			<div class="space-y-3 text-sm text-text-secondary">
				<ValidationRail
					metrics={validationMetrics}
					dependencies={validationDependencies}
					quotas={validationQuotas}
					auditRows={validationAuditRows}
				/>
				<SecurityEventFeed events={securityEvents} live={!runEventsLoading && !runEventsError} />
				<ExecutionTimelineView blocks={timelineBlocks} />
			</div>
		{/if}
	</div>
</section>
