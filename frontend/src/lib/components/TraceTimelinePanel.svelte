<script lang="ts">
	import { onMount } from 'svelte';
	import { getTraceFilterOptions, listRecentTraces } from '$lib/api/traces';
	import type { TraceEvent, TraceFilterOptions } from '$lib/types';
	import SecurityEventFeed from './SecurityEventFeed.svelte';

	interface SecurityEvent {
		id: string;
		timestamp: string;
		agent: string;
		action: string;
		detail?: string;
		status: 'queued' | 'allowed' | 'denied' | 'confirm';
		callId?: string;
	}

	interface Props {
		sessionId?: string | null;
		backendDisabled?: boolean;
	}

	let { sessionId = null, backendDisabled = false }: Props = $props();

	const MAX_EVENTS = 2000;
	const WS_RECONNECT_BASE_MS = 1500;
	const WS_RECONNECT_MAX_MS = 12000;

	let events = $state<TraceEvent[]>([]);
	let filterOptions = $state<TraceFilterOptions>({
		sourceApps: [],
		sessionIds: [],
		hookEventTypes: []
	});
	let loading = $state(false);
	let error = $state<string | null>(null);
	let search = $state('');
	let selectedSourceApps = $state<string[]>([]);
	let selectedHookEventTypes = $state<string[]>([]);
	let currentSessionOnly = $state(false);
	let liveStatus = $state<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected');
	let lastUpdatedAt = $state<Date | null>(null);

	let ws: WebSocket | null = null;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let reconnectAttempts = 0;
	let disposed = false;

	function uniqueSorted(values: string[]): string[] {
		return Array.from(new Set(values.filter((value) => value.trim().length > 0))).sort((a, b) =>
			a.localeCompare(b)
		);
	}

	function mergeFilterOptions(next: TraceFilterOptions): void {
		filterOptions = {
			sourceApps: uniqueSorted([...filterOptions.sourceApps, ...next.sourceApps]),
			sessionIds: uniqueSorted([...filterOptions.sessionIds, ...next.sessionIds]),
			hookEventTypes: uniqueSorted([...filterOptions.hookEventTypes, ...next.hookEventTypes])
		};
	}

	function toTraceEvent(raw: Record<string, unknown>): TraceEvent | null {
		if (typeof raw.id !== 'number') return null;
		if (typeof raw.source_app !== 'string') return null;
		if (typeof raw.session_id !== 'string') return null;
		if (typeof raw.hook_event_type !== 'string') return null;
		if (typeof raw.timestamp !== 'string') return null;
		return {
			id: raw.id,
			sourceApp: raw.source_app,
			sessionId: raw.session_id,
			dispatchId: typeof raw.dispatch_id === 'string' ? raw.dispatch_id : undefined,
			runId: typeof raw.run_id === 'string' ? raw.run_id : undefined,
			turnId: typeof raw.turn_id === 'string' ? raw.turn_id : undefined,
			hookEventType: raw.hook_event_type,
			payload:
				raw.payload && typeof raw.payload === 'object'
					? (raw.payload as Record<string, unknown>)
					: {},
			summary: typeof raw.summary === 'string' ? raw.summary : undefined,
			modelName: typeof raw.model_name === 'string' ? raw.model_name : undefined,
			timestamp: new Date(raw.timestamp)
		};
	}

	function prependEvent(next: TraceEvent): void {
		events = [next, ...events.filter((row) => row.id !== next.id)].slice(0, MAX_EVENTS);
		lastUpdatedAt = new Date();
	}

	async function hydrateFromApi(): Promise<void> {
		if (backendDisabled) {
			events = [];
			filterOptions = { sourceApps: [], sessionIds: [], hookEventTypes: [] };
			loading = false;
			error = null;
			return;
		}
		loading = true;
		error = null;
		try {
			const [recent, options] = await Promise.all([
				listRecentTraces({ limit: 300 }),
				getTraceFilterOptions()
			]);
			events = recent;
			filterOptions = options;
			lastUpdatedAt = new Date();
		} catch (err) {
			console.warn('Failed to hydrate traces:', err);
			error = 'Failed to load trace events.';
		} finally {
			loading = false;
		}
	}

	function traceWsUrl(): string {
		const isDev = location.port === '5173';
		const host = isDev ? `${location.hostname}:18789` : location.host;
		return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${host}/ws/traces?limit=300`;
	}

	function clearReconnectTimer(): void {
		if (!reconnectTimer) return;
		clearTimeout(reconnectTimer);
		reconnectTimer = null;
	}

	function disconnectStream(): void {
		clearReconnectTimer();
		if (ws) {
			const previous = ws;
			ws = null;
			previous.close();
		}
		liveStatus = 'disconnected';
	}

	function scheduleReconnect(): void {
		if (disposed || backendDisabled) return;
		clearReconnectTimer();
		const wait = Math.min(
			WS_RECONNECT_MAX_MS,
			WS_RECONNECT_BASE_MS * Math.max(1, 2 ** reconnectAttempts)
		);
		reconnectAttempts += 1;
		reconnectTimer = setTimeout(connectStream, wait);
	}

	function connectStream(): void {
		if (disposed || backendDisabled) return;
		if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
		liveStatus = 'connecting';
		try {
			ws = new WebSocket(traceWsUrl());
		} catch {
			liveStatus = 'error';
			scheduleReconnect();
			return;
		}

		ws.onopen = () => {
			reconnectAttempts = 0;
			liveStatus = 'connected';
		};

		ws.onmessage = (event: MessageEvent) => {
			let data: Record<string, unknown>;
			try {
				data = JSON.parse(event.data as string) as Record<string, unknown>;
			} catch {
				return;
			}
			if (data.type === 'trace_init') {
				const initEventsRaw = Array.isArray(data.events) ? data.events : [];
				const parsed = initEventsRaw
					.map((raw) => (raw && typeof raw === 'object' ? toTraceEvent(raw as Record<string, unknown>) : null))
					.filter((row): row is TraceEvent => row !== null);
				events = parsed;
				const rawFilters =
					data.filter_options && typeof data.filter_options === 'object'
						? (data.filter_options as Record<string, unknown>)
						: {};
				filterOptions = {
					sourceApps: Array.isArray(rawFilters.source_apps)
						? rawFilters.source_apps.filter((item): item is string => typeof item === 'string')
						: [],
					sessionIds: Array.isArray(rawFilters.session_ids)
						? rawFilters.session_ids.filter((item): item is string => typeof item === 'string')
						: [],
					hookEventTypes: Array.isArray(rawFilters.hook_event_types)
						? rawFilters.hook_event_types.filter((item): item is string => typeof item === 'string')
						: []
				};
				lastUpdatedAt = new Date();
				return;
			}
			if (data.type === 'trace_event' && data.data && typeof data.data === 'object') {
				const parsed = toTraceEvent(data.data as Record<string, unknown>);
				if (!parsed) return;
				prependEvent(parsed);
				mergeFilterOptions({
					sourceApps: [parsed.sourceApp],
					sessionIds: [parsed.sessionId],
					hookEventTypes: [parsed.hookEventType]
				});
			}
		};

		ws.onerror = () => {
			liveStatus = 'error';
		};

		ws.onclose = () => {
			ws = null;
			if (!disposed) {
				liveStatus = 'disconnected';
				scheduleReconnect();
			}
		};
	}

	function toggleSourceApp(sourceApp: string): void {
		selectedSourceApps = selectedSourceApps.includes(sourceApp)
			? selectedSourceApps.filter((item) => item !== sourceApp)
			: [...selectedSourceApps, sourceApp];
	}

	function toggleHookType(hookType: string): void {
		selectedHookEventTypes = selectedHookEventTypes.includes(hookType)
			? selectedHookEventTypes.filter((item) => item !== hookType)
			: [...selectedHookEventTypes, hookType];
	}

	function clearFilters(): void {
		selectedSourceApps = [];
		selectedHookEventTypes = [];
		search = '';
	}

	function eventTypeBadge(eventType: string): string {
		if (eventType === 'error') return 'border-error/50 text-error';
		if (eventType.startsWith('dispatch_')) return 'border-info/50 text-info';
		if (eventType.startsWith('run_')) return 'border-focus/50 text-text-primary';
		if (eventType.startsWith('task_')) return 'border-success/50 text-success';
		if (eventType.startsWith('tool_') || eventType.startsWith('confirm_')) {
			return 'border-warning/50 text-warning';
		}
		return 'border-border-muted text-text-muted';
	}

	function rowSummary(event: TraceEvent): string {
		if (event.summary && event.summary.trim().length > 0) return event.summary;
		const message = event.payload.message;
		if (typeof message === 'string' && message.trim().length > 0) {
			return message;
		}
		const content = event.payload.content;
		if (typeof content === 'string' && content.trim().length > 0) {
			return content;
		}
		return event.hookEventType;
	}

	function formatClock(value: Date): string {
		return value.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}

	const visibleEvents = $derived.by(() => {
		const normalizedSearch = search.trim().toLowerCase();
		return events.filter((event) => {
			if (currentSessionOnly && sessionId && event.sessionId !== sessionId) return false;
			if (selectedSourceApps.length > 0 && !selectedSourceApps.includes(event.sourceApp)) return false;
			if (
				selectedHookEventTypes.length > 0 &&
				!selectedHookEventTypes.includes(event.hookEventType)
			) {
				return false;
			}
			if (!normalizedSearch) return true;
			const payloadText = JSON.stringify(event.payload).toLowerCase();
			return (
				event.sourceApp.toLowerCase().includes(normalizedSearch) ||
				event.hookEventType.toLowerCase().includes(normalizedSearch) ||
				(event.summary ?? '').toLowerCase().includes(normalizedSearch) ||
				(event.modelName ?? '').toLowerCase().includes(normalizedSearch) ||
				payloadText.includes(normalizedSearch)
			);
		});
	});

	const lastUpdatedLabel = $derived.by(() => {
		if (!lastUpdatedAt) return 'Never';
		return lastUpdatedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	});

	const securityFeedEvents = $derived.by<SecurityEvent[]>(() =>
		visibleEvents.slice(0, 40).map((event) => ({
			id: String(event.id),
			timestamp: formatClock(event.timestamp),
			agent:
				typeof event.payload.agent === 'string'
					? event.payload.agent
					: typeof event.payload.source === 'string'
						? event.payload.source
						: event.sourceApp,
			action: event.hookEventType,
			detail: rowSummary(event),
			status:
				event.hookEventType === 'tool_permission_decision' &&
				event.payload.state === 'confirm'
					? 'confirm'
					: event.hookEventType === 'tool_permission_decision' &&
							event.payload.state === 'deny'
						? 'denied'
						: event.hookEventType === 'tool_permission_decision' &&
								event.payload.state === 'allow'
							? 'allowed'
							: event.hookEventType === 'confirm_request'
					? 'confirm'
					: event.hookEventType === 'error'
						? 'denied'
						: event.hookEventType.startsWith('run_') || event.hookEventType.startsWith('tool_')
							? 'allowed'
							: 'queued',
			callId: typeof event.payload.call_id === 'string' ? event.payload.call_id : undefined
		}))
	);

	onMount(() => {
		void hydrateFromApi();
		connectStream();
		return () => {
			disposed = true;
			disconnectStream();
		};
	});
</script>

<section class="flex min-w-0 flex-1 flex-col overflow-hidden p-4" aria-label="Trace timeline panel">
	<div class="rounded border border-border-muted bg-surface px-4 py-3">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<div class="min-w-[240px]">
				<h2 class="text-sm font-semibold uppercase tracking-wide text-text-primary">Agent Timeline</h2>
				<p class="mt-1 text-xs text-text-muted">
					Live execution traces for dispatches, runs, tools, and compacting phases.
				</p>
			</div>
			<div class="flex items-center gap-2 text-xs">
				<span
					class="inline-flex items-center gap-1 rounded border px-2 py-1 {liveStatus === 'connected'
						? 'border-success/50 text-success'
						: liveStatus === 'connecting'
							? 'border-warning/50 text-warning'
							: 'border-border-muted text-text-muted'}"
				>
					<span
						class="h-1.5 w-1.5 rounded-full {liveStatus === 'connected'
							? 'bg-success'
							: liveStatus === 'connecting'
								? 'bg-warning'
								: 'bg-border-muted'}"
					></span>
					{liveStatus}
				</span>
				<button
					type="button"
					class="rounded border border-border-muted bg-inset px-2 py-1 text-text-secondary hover:text-text-primary"
					onclick={() => {
						void hydrateFromApi();
					}}
				>
					Refresh
				</button>
			</div>
		</div>

		{#if backendDisabled}
			<div class="mt-3 rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
				Backend disabled mode: live traces are unavailable.
			</div>
		{:else}
			<div class="mt-3 flex flex-wrap items-center gap-2">
				<label class="flex min-w-[220px] flex-1 items-center gap-2 rounded border border-border-muted bg-inset px-2 py-1">
					<span class="text-[11px] uppercase tracking-wide text-text-muted">Search</span>
					<input
						type="text"
						class="min-w-0 flex-1 bg-transparent text-xs text-text-primary outline-none placeholder:text-text-muted"
						placeholder="event, source, model, payload..."
						bind:value={search}
					/>
				</label>
				{#if sessionId}
					<button
						type="button"
						class="rounded border px-2 py-1 text-xs {currentSessionOnly
							? 'border-focus text-text-primary bg-surface-raised'
							: 'border-border-muted text-text-secondary hover:text-text-primary'}"
						onclick={() => {
							currentSessionOnly = !currentSessionOnly;
						}}
					>
						{currentSessionOnly ? 'Current session only' : 'All sessions'}
					</button>
				{/if}
				<button
					type="button"
					class="rounded border border-border-muted px-2 py-1 text-xs text-text-secondary hover:text-text-primary"
					onclick={clearFilters}
				>
					Clear filters
				</button>
			</div>

			{#if filterOptions.sourceApps.length > 0}
				<div class="mt-2 flex flex-wrap gap-1">
					<span class="mr-1 text-[10px] uppercase tracking-wide text-text-muted">Source</span>
					{#each filterOptions.sourceApps as sourceApp}
						<button
							type="button"
							class="rounded border px-1.5 py-0.5 text-[10px] {selectedSourceApps.includes(sourceApp)
								? 'border-focus text-text-primary bg-surface-raised'
								: 'border-border-muted text-text-muted hover:text-text-primary'}"
							onclick={() => toggleSourceApp(sourceApp)}
						>
							{sourceApp}
						</button>
					{/each}
				</div>
			{/if}

			{#if filterOptions.hookEventTypes.length > 0}
				<div class="mt-2 flex flex-wrap gap-1">
					<span class="mr-1 text-[10px] uppercase tracking-wide text-text-muted">Event</span>
					{#each filterOptions.hookEventTypes as hookType}
						<button
							type="button"
							class="rounded border px-1.5 py-0.5 text-[10px] {selectedHookEventTypes.includes(hookType)
								? 'border-focus text-text-primary bg-surface-raised'
								: 'border-border-muted text-text-muted hover:text-text-primary'}"
							onclick={() => toggleHookType(hookType)}
						>
							{hookType}
						</button>
					{/each}
				</div>
			{/if}
		{/if}
	</div>

	<div class="mt-3 grid min-h-0 flex-1 gap-3 xl:grid-cols-[320px,minmax(0,1fr)]">
		<SecurityEventFeed events={securityFeedEvents} live={liveStatus === 'connected'} />

		<div class="flex min-h-0 flex-1 flex-col rounded border border-border-muted bg-surface">
			<div class="flex items-center justify-between border-b border-border-muted px-4 py-2 text-xs text-text-muted">
				<span>{visibleEvents.length} visible event{visibleEvents.length === 1 ? '' : 's'}</span>
				<span>Updated {lastUpdatedLabel}</span>
			</div>

			{#if loading}
				<div class="p-4 text-sm text-text-muted">Loading traces...</div>
			{:else if error}
				<div class="p-4 text-sm text-error">{error}</div>
			{:else if visibleEvents.length === 0}
				<div class="p-4 text-sm text-text-muted">No trace events for the current filter set.</div>
			{:else}
				<div class="min-h-0 flex-1 overflow-y-auto px-3 py-2">
					<div class="space-y-2">
						{#each visibleEvents as event (event.id)}
							<details class="rounded border border-border-muted bg-inset px-3 py-2">
								<summary class="cursor-pointer list-none">
									<div class="flex items-start gap-2">
										<span class="shrink-0 font-mono text-[10px] text-text-muted">
											{formatClock(event.timestamp)}
										</span>
										<span
											class="shrink-0 rounded border px-1 py-0.5 text-[10px] uppercase tracking-wide {eventTypeBadge(event.hookEventType)}"
										>
											{event.hookEventType}
										</span>
										<span class="shrink-0 rounded border border-border-muted px-1 py-0.5 text-[10px] text-text-secondary">
											{event.sourceApp}
										</span>
										{#if event.modelName}
											<span class="shrink-0 rounded border border-border-muted px-1 py-0.5 text-[10px] text-text-muted">
												{event.modelName}
											</span>
										{/if}
										<span class="min-w-0 flex-1 break-words text-xs text-text-primary">
											{rowSummary(event)}
										</span>
									</div>
								</summary>
								<div class="mt-2 space-y-2 text-[11px]">
									<div class="flex flex-wrap gap-2 text-text-muted">
										<span>session: <span class="font-mono">{event.sessionId}</span></span>
										{#if event.dispatchId}
											<span>dispatch: <span class="font-mono">{event.dispatchId}</span></span>
										{/if}
										{#if event.runId}
											<span>run: <span class="font-mono">{event.runId}</span></span>
										{/if}
										{#if event.turnId}
											<span>turn: <span class="font-mono">{event.turnId}</span></span>
										{/if}
									</div>
									<pre class="overflow-x-auto rounded border border-border-muted bg-surface px-2 py-1 text-[10px] text-text-secondary">{JSON.stringify(event.payload, null, 2)}</pre>
								</div>
							</details>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	</div>
</section>
