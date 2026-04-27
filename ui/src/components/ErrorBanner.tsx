import { useSlice } from '../store';
import type { Kind } from '../types';

export function ErrorBanner({ kind }: { kind: Kind }) {
  const slice = useSlice(kind);
  const err = slice.error;
  if (!err) return null;
  return (
    <div className="error-banner">
      <div className="error-banner-icon">⚠</div>
      <div className="error-banner-body">
        <div className="error-banner-title">
          {err.code === 401
            ? 'Server-side credential missing'
            : err.code === 413
            ? 'File too large'
            : err.code === 415
            ? 'Unsupported file type'
            : 'Something went wrong'}
        </div>
        <div className="error-banner-message">{err.message}</div>
      </div>
      <button className="link-btn" onClick={() => slice.setError(undefined)}>
        dismiss
      </button>
    </div>
  );
}
