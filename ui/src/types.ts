export type Kind = 'company' | 'name';

export type RunState =
  | 'idle'
  | 'uploaded'
  | 'columns_loaded'
  | 'running'
  | 'done'
  | 'cancelled'
  | 'error'
  | 'spend_blocked';

export type RowStatus = 'changed' | 'unchanged' | 'null' | 'pending';

export interface Row {
  n: number;
  orig: string;
  clean: string | null;
  status: RowStatus;
  reason: string;
  flags?: string[];
  route?: string | null;
}

export interface ColumnInfo {
  name: string;
  samples: string[];
}

export interface ColumnsResponse {
  sid: string;
  kind: Kind;
  columns: ColumnInfo[];
  row_count_estimate: number;
  suggested: string | null;
}

export interface DryRunResponse {
  row_count: number;
  estimated_cost_usd: number;
  today_usd: number;
  cap_usd: number;
  would_exceed_cap: boolean;
}

export interface UploadResponse {
  sid: string;
  kind: Kind;
  state: string;
  filename: string;
  size_bytes: number;
  row_count: number | null;
  selected_column: string | null;
  result_row_count: number;
  result_cost_usd: number;
  error_msg: string | null;
}

export interface WhoamiResponse {
  email: string;
  today_usd: number;
  cap_usd: number;
  remaining_usd: number;
}

export interface Telemetry {
  rowsPerSecond: number;
  tokensIn: number;
  tokensOut: number;
  nullCount: number;
  rulesFired: number;
  costUsd: number;
}

export interface SseEvent {
  kind: string;
  payload: unknown;
}

export interface ErrorPayload {
  code: number;
  message: string;
}
