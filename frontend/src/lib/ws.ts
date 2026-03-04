import type { ClientMessage, ServerMessage, ConnectionStatus } from './types';

export type MessageHandler = (msg: ServerMessage) => void;

const BACKOFF_SCHEDULE = [1000, 2000, 4000, 8000, 16000, 30000];
const MAX_RETRIES = 5;

const PING_INTERVAL_MS = 30000;

export class GatewayClient {
	private ws: WebSocket | null = null;
	private url: string;
	private onMessage: MessageHandler;
	private onStatusChange: (status: ConnectionStatus) => void;
	private retryCount = 0;
	private retryTimer: ReturnType<typeof setTimeout> | null = null;
	private intentionalClose = false;
	private messageQueue: ClientMessage[] = [];
	private pingInterval: ReturnType<typeof setInterval> | null = null;

	constructor(
		url: string,
		onMessage: MessageHandler,
		onStatusChange: (status: ConnectionStatus) => void
	) {
		this.url = url;
		this.onMessage = onMessage;
		this.onStatusChange = onStatusChange;
	}

	connect(): void {
		this.intentionalClose = false;
		this.onStatusChange('connecting');

		try {
			this.ws = new WebSocket(this.url);
		} catch {
			this.onStatusChange('error');
			this.scheduleReconnect();
			return;
		}

		this.ws.onopen = () => {
			this.retryCount = 0;
			this.onStatusChange('connected');
			this.flushQueue();
			this.startPing();
		};

		this.ws.onmessage = (event: MessageEvent) => {
			try {
				const msg: ServerMessage = JSON.parse(event.data as string);
				this.onMessage(msg);
			} catch {
				console.error('Failed to parse WebSocket message:', event.data);
			}
		};

		this.ws.onclose = () => {
			this.stopPing();
			if (!this.intentionalClose) {
				this.onStatusChange('disconnected');
				this.scheduleReconnect();
			}
		};

		this.ws.onerror = () => {
			this.onStatusChange('error');
		};
	}

	send(msg: ClientMessage): void {
		if (this.ws?.readyState === WebSocket.OPEN) {
			this.ws.send(JSON.stringify(msg));
		} else {
			this.messageQueue.push(msg);
		}
	}

	private flushQueue(): void {
		while (this.messageQueue.length > 0) {
			const msg = this.messageQueue.shift()!;
			this.send(msg);
		}
	}

	private startPing(): void {
		this.stopPing();
		this.pingInterval = setInterval(() => {
			this.send({ type: 'ping' });
		}, PING_INTERVAL_MS);
	}

	private stopPing(): void {
		if (this.pingInterval) {
			clearInterval(this.pingInterval);
			this.pingInterval = null;
		}
	}

	sendChat(
		message: string,
		model?: string,
		targetAgent?: string,
		requiresTools?: boolean,
		targetAgents?: string[],
		dispatchMode?: 'router' | 'direct' | 'parallel'
	): void {
		this.send({
			type: 'chat',
			message,
			...(model ? { model } : {}),
			...(targetAgent ? { target_agent: targetAgent } : {}),
			...(targetAgents && targetAgents.length > 0 ? { target_agents: targetAgents } : {}),
			...(dispatchMode ? { dispatch_mode: dispatchMode } : {}),
			...(requiresTools ? { requires_tools: true } : {})
		});
	}

	sendConfirm(callId: string, approved: boolean): void {
		this.send({ type: 'confirm_response', tool_call_id: callId, approved });
	}

	sendInterrupt(): void {
		this.send({ type: 'interrupt' });
	}

	disconnect(): void {
		this.intentionalClose = true;
		this.stopPing();
		if (this.retryTimer) {
			clearTimeout(this.retryTimer);
			this.retryTimer = null;
		}
		this.ws?.close();
		this.ws = null;
		this.onStatusChange('disconnected');
	}

	private scheduleReconnect(): void {
		if (this.retryCount >= MAX_RETRIES) {
			this.onStatusChange('error');
			return;
		}
		const delay = BACKOFF_SCHEDULE[Math.min(this.retryCount, BACKOFF_SCHEDULE.length - 1)];
		this.retryCount++;
		this.retryTimer = setTimeout(() => this.connect(), delay);
	}

	get isConnected(): boolean {
		return this.ws?.readyState === WebSocket.OPEN;
	}
}
