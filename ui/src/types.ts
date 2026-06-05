// Splitter-only types. Phase C stripped this down from the cleaners-hub
// multi-kind shape (company / name / address) to a single ``fullname`` kind.
// Anything that switches on ``kind`` is now unreachable — there's only one.

export type Kind = 'fullname';

// Backend session.state values that come down the SSE stream.
export type RunState =
  | 'idle'
  | 'uploaded'
  | 'columns_loaded'
  | 'running'
  | 'done'
  | 'cancelled'
  | 'error'
  | 'spend_blocked';

// Derived UI state — what the workspace renders. Computed from RunState +
// slice presence.
export type AppState =
  | 'empty'             // no upload yet
  | 'awaiting_column'   // uploaded, user picking column
  | 'indexed'           // column picked, ready to run
  | 'running'
  | 'done'
  | 'cancelled'         // user pressed Cancel — table stays, "Continue" resumes
  | 'error';

export type RowStatus = 'changed' | 'unchanged' | 'null' | 'pending';

export interface Row {
  n: number;
  orig: string;
  // Splitter output: two independent cells. Either can be null (or empty),
  // meaning Grok declined to split that part. Both null → the row is in the
  // ``null`` status (red row state).
  first: string | null;
  last: string | null;
  // Legacy "<first> <last>" mirror string. Some consumers (notably the
  // dry-run-sample mapper) still want a single display string; new UI code
  // reads first/last directly.
  clean: string | null;
  status: RowStatus;
  reason: string;
  flags?: string[];
  route?: string | null;
}

// Single column from /api/columns — includes server-side samples.
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

// /api/dry-run cost-pre-check (NOT the dry-run-sample — that's below).
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
  is_admin: boolean;
  today_usd: number;
  cap_usd: number;
  hard_cap_usd: number;
  remaining_usd: number;
}

// /api/dry-run-sample → 25 (or N) rows actually scored by Grok.
export interface DryRunSampleMeta {
  model: string;
  elapsed_s: number;
  cost_usd: number;
  count: number;
  tokens_in: number;
  tokens_out: number;
}
export interface DryRunSampleResponse {
  meta: DryRunSampleMeta;
  rows: Row[];
}

// /api/runs — past run records.
export interface RunRecord {
  run_id: string;
  email: string;
  kind: Kind;
  column: string | null;
  filename: string | null;
  state: string;
  row_count: number | null;
  cost_usd: number | null;
  started_at: string;
  finished_at: string | null;
  error_msg: string | null;
  output_path?: string | null;
}

export interface RunsListResponse {
  total: number;
  limit: number;
  offset: number;
  rows: RunRecord[];
}

// /api/settings — mutable runtime settings. Splitter only.
export interface AppSettings {
  daily_cap_usd: number;
  batch_size_fullname: number;
  model_fullname: string;
  is_admin: boolean;
  hard_cap_usd: number;
  min_batch_size: number;
  max_batch_size: number;
  min_daily_cap_usd: number;
  allowed_models: string[];
}

export type AppSettingsPatch = Partial<{
  daily_cap_usd: number;
  batch_size_fullname: number;
  model_fullname: string;
}>;

// Derived from upload + columns.
export interface FileMeta {
  name: string;
  rows: number;
  encoding: string;       // not surfaced by backend; stays as 'utf-8' placeholder
  column: string;         // currently selected column (may be empty pre-pick)
  columns?: string[];
}

export interface Progress {
  processed: number;
  total: number;
  etaSeconds: number;
  elapsedSeconds: number;
}

export interface Telemetry {
  rowsPerSecond: number;
  rowsPerSecondHistory: number[];
  tokensIn: number;
  tokensOut: number;
  nullCount: number;
  rulesFired: number;
  costUsd: number;
}

export interface UiError {
  code: number;
  retryAfter: number;
  message: string;
  lastRow: number;
}

// Filter values used in the workspace header pills.
export type FilterKind =
  | 'all'
  | 'changed' | 'unchanged' | 'null';
export type DryRunKind = 'changed' | 'same' | 'flag' | 'blank';

// What the workspace renders during dry-run-sample. Rows are mapped from
// the server's Row[] into this UI shape.
export interface DryRunUiRow {
  n: number;
  orig: string;
  clean: string;
  kind: DryRunKind;
  tag: string;
}
export interface DryRunUiMeta {
  model: string;
  elapsedSeconds: number;
  costUsd: number;
  count: number;
}
export interface DryRunUiResult {
  rows: DryRunUiRow[];
  meta: DryRunUiMeta;
}

export interface SseEvent {
  kind: string;
  payload: unknown;
}

export interface ErrorPayload {
  code: number;
  message: string;
}

export interface CostModalState {
  rows: number;
  costUsd: number;
  elapsedSeconds: number;
  column: string;
  rowLimit?: number;
}

// Mapper info — derived from ColumnsResponse + suggested column name.
export interface MapperColumn {
  id: string;
  name: string;
  meta: string;
  preview: string[];
  suggested: boolean;
}
