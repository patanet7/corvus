/**
 * WebSocket protocol types — synced from corvus/gateway/protocol.py.
 *
 * This is the single source of truth for frontend WS message typing.
 */

export type WsEventType =
  | 'init'
  | 'routing'
  | 'dispatch_start'
  | 'dispatch_plan'
  | 'dispatch_complete'
  | 'run_start'
  | 'run_phase'
  | 'run_output_chunk'
  | 'run_complete'
  | 'task_start'
  | 'task_progress'
  | 'task_complete'
  | 'tool_start'
  | 'tool_result'
  | 'tool_permission_decision'
  | 'confirm_request'
  | 'confirm_response'
  | 'interrupt_ack'
  | 'text'
  | 'done'
  | 'error'
  | 'pong'
  | 'agent_status';

/** Base fields present on every WS message */
export interface WsMessageBase {
  type: WsEventType;
  agent?: string;
  session_id?: string;
  turn_id?: string;
  dispatch_id?: string;
  run_id?: string;
  task_id?: string;
}

/** Run lifecycle events */
export interface RunStartEvent extends WsMessageBase {
  type: 'run_start';
  backend: string;
  model: string;
  workspace_cwd: string;
  status: string;
}

export interface RunOutputChunkEvent extends WsMessageBase {
  type: 'run_output_chunk';
  chunk_index: number;
  content: string;
  final: boolean;
  model: string;
  tokens_used?: number;
  cost_usd?: number;
  context_limit?: number;
  context_pct?: number;
}

export interface RunCompleteEvent extends WsMessageBase {
  type: 'run_complete';
  result: 'success' | 'error' | 'interrupted';
  summary: string;
  cost_usd: number;
  tokens_used: number;
  context_limit: number;
  context_pct: number;
}

/** Task lifecycle events */
export interface TaskStartEvent extends WsMessageBase {
  type: 'task_start';
  description: string;
}

export interface TaskProgressEvent extends WsMessageBase {
  type: 'task_progress';
  status: string;
  summary: string;
}

export interface TaskCompleteEvent extends WsMessageBase {
  type: 'task_complete';
  result: 'success' | 'error' | 'interrupted';
  summary: string;
  cost_usd?: number;
}

/** Confirm gate events */
export interface ConfirmRequestEvent extends WsMessageBase {
  type: 'confirm_request';
  tool: string;
  params: Record<string, unknown>;
  call_id: string;
  timeout_s: number;
}

/** Generic fallback for events not yet typed */
export interface GenericWsEvent extends WsMessageBase {
  type: WsEventType;
  [key: string]: unknown;
}

export type WsMessage =
  | RunStartEvent
  | RunOutputChunkEvent
  | RunCompleteEvent
  | TaskStartEvent
  | TaskProgressEvent
  | TaskCompleteEvent
  | ConfirmRequestEvent
  | GenericWsEvent;
