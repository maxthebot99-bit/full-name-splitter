import { useCallback, useRef, useState } from 'react';
import type { Kind } from '../types';

const ALLOWED = ['.xlsx', '.csv'];
const MAX_BYTES = 50 * 1024 * 1024;

export function DropZone({ kind, onFile }: { kind: Kind; onFile: (f: File) => void }) {
  const [hover, setHover] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLLabelElement>) => {
      e.preventDefault();
      setHover(false);
      const f = e.dataTransfer.files?.[0];
      if (f) tryFile(f);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  function tryFile(f: File) {
    setErrMsg(null);
    const ext = f.name.toLowerCase().slice(f.name.lastIndexOf('.'));
    if (!ALLOWED.includes(ext)) {
      setErrMsg(`Only ${ALLOWED.join(', ')} accepted (got ${ext || '<no extension>'}).`);
      return;
    }
    if (f.size > MAX_BYTES) {
      setErrMsg(`File is ${(f.size / 1024 / 1024).toFixed(1)} MB; max is 50 MB.`);
      return;
    }
    onFile(f);
  }

  return (
    <div className="dropzone-wrap">
      <div className="dropzone-headline">
        <h1>{kind === 'company' ? 'Clean a list of company names' : 'Clean a list of first names'}</h1>
        <p className="dropzone-sub">
          Drop an <code>.xlsx</code> or <code>.csv</code>. Pick a column. Grok cleans every row.
          Download the result.
        </p>
      </div>
      <label
        className={`dropzone ${hover ? 'dropzone--hover' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setHover(true);
        }}
        onDragLeave={() => setHover(false)}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.csv"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) tryFile(f);
          }}
        />
        <div className="dropzone-inner">
          <div className="dropzone-icon">⤓</div>
          <div className="dropzone-cta">
            Drop a file here or <span className="dropzone-link">choose one</span>
          </div>
          <div className="dropzone-meta">.xlsx or .csv · up to 50 MB</div>
        </div>
      </label>
      {errMsg && <div className="dropzone-error">{errMsg}</div>}
    </div>
  );
}
