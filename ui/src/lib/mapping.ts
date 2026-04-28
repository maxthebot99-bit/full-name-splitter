// Map server-side dry-run-sample response into the UI's DryRunUi shape.
// The backend returns full Row records (status changed/unchanged/null);
// the Nocturne dry-run panel wants `kind`/`tag` instead.

import type {
  DryRunSampleResponse,
  DryRunUiResult,
  DryRunUiRow,
  Row,
} from '../types';

function rowToUi(r: Row): DryRunUiRow {
  let kind: DryRunUiRow['kind'];
  let clean: string;
  if ((r.orig ?? '').trim() === '') {
    kind = 'blank';
    clean = '(blank)';
  } else if (r.clean === null) {
    // Null with reason → flag (Grok had something to say); plain null → blank.
    kind = r.reason && r.reason.trim() ? 'flag' : 'blank';
    clean = r.reason ? '(flagged)' : '(blank)';
  } else if ((r.clean ?? '').trim() === (r.orig ?? '').trim()) {
    kind = 'same';
    clean = r.clean;
  } else {
    kind = 'changed';
    clean = r.clean;
  }
  // Tag — short summary of why this row landed where it did.
  const tag = (r.reason || '').slice(0, 60);
  return { n: r.n, orig: r.orig ?? '', clean, kind, tag };
}

export function mapDryRunSample(resp: DryRunSampleResponse): DryRunUiResult {
  return {
    rows: resp.rows.map(rowToUi),
    meta: {
      model: resp.meta.model,
      elapsedSeconds: resp.meta.elapsed_s,
      costUsd: resp.meta.cost_usd,
      count: resp.meta.count,
    },
  };
}
