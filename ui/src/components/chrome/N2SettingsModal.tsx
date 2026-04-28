import { useEffect, useState } from 'react';
import { N2, fSerif, fBody, fMono } from '../../theme';
import { useStore } from '../../store';
import { refreshSettings, saveSettings } from '../../lib/actions';
import { sendTestAlert } from '../../api';
import type { AppSettings, AppSettingsPatch } from '../../types';

// Admin-only settings modal. Reads /api/settings on open and PUTs a patch
// of the changed fields. Backend rejects non-admins with 403.
export function N2SettingsModal() {
  const open = useStore((s) => s.settingsModalOpen);
  const setOpen = useStore((s) => s.setSettingsModalOpen);
  const settings = useStore((s) => s.settings);
  const whoami = useStore((s) => s.whoami);

  const [draft, setDraft] = useState<AppSettingsPatch>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testStatus, setTestStatus] = useState<'idle' | 'sending' | 'sent' | 'failed'>('idle');
  const [testError, setTestError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      void refreshSettings();
      setDraft({});
      setError(null);
      setTestStatus('idle');
      setTestError(null);
    }
  }, [open]);

  const onSendTest = async () => {
    setTestStatus('sending');
    setTestError(null);
    try {
      const r = await sendTestAlert();
      if (r.sent) {
        setTestStatus('sent');
      } else {
        setTestStatus('failed');
        setTestError(r.error ?? 'unknown error');
      }
    } catch (err) {
      setTestStatus('failed');
      setTestError(err instanceof Error ? err.message : 'request failed');
    }
  };

  // Escape closes the modal. Hook before early return per React rules.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, setOpen]);

  if (!open || !settings) return null;

  const isAdmin = whoami?.is_admin ?? false;
  // The patch keys (AppSettingsPatch) are a subset of the full settings
  // shape (AppSettings), so a properly-typed read can pull the current
  // value off either object — `as never` previously papered over the
  // intersection.
  const get = <K extends keyof AppSettingsPatch>(
    k: K,
  ): AppSettingsPatch[K] | AppSettings[K & keyof AppSettings] => {
    const drafted = draft[k];
    if (drafted !== undefined) return drafted;
    return settings[k as K & keyof AppSettings];
  };

  const onSave = async () => {
    if (!isAdmin) return;
    if (Object.keys(draft).length === 0) {
      setOpen(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await saveSettings(draft);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(8,9,15,0.72)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
    >
      <div
        style={{
          width: 560,
          maxWidth: '100%',
          background: N2.bg,
          border: `1px solid ${N2.hair2}`,
          borderRadius: 4,
          padding: '32px 36px 28px',
          boxShadow: '0 40px 120px rgba(0,0,0,0.55)',
          fontFamily: fBody,
        }}
      >
        <div
          style={{
            fontFamily: fSerif,
            fontSize: 26,
            color: N2.text,
            letterSpacing: -0.4,
            fontWeight: 500,
            marginBottom: 4,
            fontVariationSettings: '"opsz" 60, "SOFT" 30',
          }}
        >
          Settings
        </div>
        <div
          style={{
            fontFamily: fMono,
            fontSize: 9.5,
            color: N2.text3,
            letterSpacing: 1.4,
            textTransform: 'uppercase',
            marginBottom: 18,
          }}
        >
          {isAdmin ? 'admin · changes apply on next run' : 'view only'}
        </div>

        <Field
          label="Daily soft cap (USD)"
          hint={`hard ceiling: $${settings.hard_cap_usd.toFixed(0)}`}
        >
          <input
            type="number"
            min={settings.min_daily_cap_usd}
            max={settings.hard_cap_usd}
            step="0.5"
            disabled={!isAdmin || saving}
            value={get('daily_cap_usd') ?? settings.daily_cap_usd}
            onChange={(e) =>
              setDraft((d) => ({ ...d, daily_cap_usd: Number(e.target.value) }))
            }
            style={inputStyle()}
          />
        </Field>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <Field label="Batch size · companies">
            <input
              type="number"
              min={settings.min_batch_size}
              max={settings.max_batch_size}
              disabled={!isAdmin || saving}
              value={get('batch_size_company') ?? settings.batch_size_company}
              onChange={(e) =>
                setDraft((d) => ({ ...d, batch_size_company: Number(e.target.value) }))
              }
              style={inputStyle()}
            />
          </Field>
          <Field label="Batch size · names">
            <input
              type="number"
              min={settings.min_batch_size}
              max={settings.max_batch_size}
              disabled={!isAdmin || saving}
              value={get('batch_size_name') ?? settings.batch_size_name}
              onChange={(e) =>
                setDraft((d) => ({ ...d, batch_size_name: Number(e.target.value) }))
              }
              style={inputStyle()}
            />
          </Field>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <Field label="Model · companies">
            <select
              disabled={!isAdmin || saving}
              value={get('model_company') ?? settings.model_company}
              onChange={(e) =>
                setDraft((d) => ({ ...d, model_company: e.target.value }))
              }
              style={inputStyle()}
            >
              {settings.allowed_models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Model · names">
            <select
              disabled={!isAdmin || saving}
              value={get('model_name') ?? settings.model_name}
              onChange={(e) =>
                setDraft((d) => ({ ...d, model_name: e.target.value }))
              }
              style={inputStyle()}
            >
              {settings.allowed_models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
        </div>

        {error && (
          <div
            style={{
              padding: '10px 12px',
              border: `1px solid ${N2.rose}66`,
              background: N2.roseDim,
              color: N2.rose,
              fontFamily: fMono,
              fontSize: 11,
              borderRadius: 2,
              marginTop: 12,
            }}
          >
            {error}
          </div>
        )}

        {/* Email alerts test — fires a one-off through the live Resend
            wiring (sender + recipient as configured in alerts.py). Useful
            after planting / rotating the Resend key. */}
        {isAdmin && (
          <div
            style={{
              marginTop: 22,
              paddingTop: 18,
              borderTop: `1px solid ${N2.hair}`,
            }}
          >
            <div
              style={{
                fontFamily: fMono,
                fontSize: 9.5,
                color: N2.text3,
                letterSpacing: 1.4,
                textTransform: 'uppercase',
                fontWeight: 600,
                marginBottom: 6,
              }}
            >
              Email alerts
            </div>
            <div
              style={{
                fontSize: 12,
                color: N2.text2,
                lineHeight: 1.5,
                marginBottom: 10,
              }}
            >
              Test the Resend wiring end-to-end. Sends one email from{' '}
              <code style={{ fontFamily: fMono, color: N2.text3 }}>
                onboarding@resend.dev
              </code>{' '}
              to the configured recipient.
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button
                type="button"
                onClick={onSendTest}
                disabled={testStatus === 'sending'}
                style={{
                  background: 'transparent',
                  color: N2.accent,
                  border: `1px solid ${N2.accentDeep}`,
                  padding: '8px 14px',
                  borderRadius: 2,
                  fontFamily: fMono,
                  fontSize: 10,
                  letterSpacing: 1.5,
                  textTransform: 'uppercase',
                  fontWeight: 700,
                  cursor: testStatus === 'sending' ? 'wait' : 'pointer',
                  opacity: testStatus === 'sending' ? 0.6 : 1,
                }}
              >
                {testStatus === 'sending' ? 'Sending…' : 'Send test email'}
              </button>
              {testStatus === 'sent' && (
                <span
                  style={{
                    fontFamily: fMono,
                    fontSize: 10,
                    color: N2.sage,
                    letterSpacing: 1.2,
                    textTransform: 'uppercase',
                  }}
                >
                  ✓ Sent — check your inbox (and spam)
                </span>
              )}
              {testStatus === 'failed' && (
                <span
                  style={{
                    fontFamily: fMono,
                    fontSize: 10,
                    color: N2.rose,
                    letterSpacing: 0.8,
                  }}
                >
                  Failed: {testError}
                </span>
              )}
            </div>
          </div>
        )}

        <div
          style={{
            display: 'flex',
            gap: 12,
            justifyContent: 'flex-end',
            marginTop: 22,
          }}
        >
          <button
            type="button"
            onClick={() => setOpen(false)}
            style={btnGhost()}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!isAdmin || saving}
            onClick={onSave}
            style={btnPrimary(!isAdmin || saving)}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 6,
        }}
      >
        <label
          style={{
            fontFamily: fMono,
            fontSize: 9.5,
            color: N2.text3,
            letterSpacing: 1.4,
            textTransform: 'uppercase',
            fontWeight: 600,
          }}
        >
          {label}
        </label>
        {hint && (
          <span style={{ fontFamily: fMono, fontSize: 9, color: N2.text4 }}>
            {hint}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function inputStyle(): React.CSSProperties {
  return {
    width: '100%',
    background: 'rgba(255,253,247,0.03)',
    border: `1px solid ${N2.hair2}`,
    borderRadius: 2,
    color: N2.text,
    fontFamily: fMono,
    fontSize: 12,
    padding: '8px 10px',
    outline: 'none',
    letterSpacing: 0.3,
  };
}

function btnGhost(): React.CSSProperties {
  return {
    background: 'transparent',
    color: N2.text2,
    border: `1px solid ${N2.hair2}`,
    padding: '10px 18px',
    borderRadius: 2,
    fontFamily: fMono,
    fontSize: 10.5,
    letterSpacing: 1.6,
    textTransform: 'uppercase',
    fontWeight: 700,
    cursor: 'pointer',
  };
}

function btnPrimary(disabled: boolean): React.CSSProperties {
  return {
    background: disabled
      ? 'transparent'
      : `linear-gradient(180deg, ${N2.accent}, ${N2.accentSoft})`,
    color: disabled ? N2.text4 : '#0a0612',
    border: disabled ? `1px solid ${N2.hair2}` : 'none',
    padding: '10px 22px',
    borderRadius: 2,
    fontFamily: fMono,
    fontSize: 10.5,
    letterSpacing: 1.6,
    textTransform: 'uppercase',
    fontWeight: 700,
    cursor: disabled ? 'not-allowed' : 'pointer',
    boxShadow: disabled ? 'none' : `0 0 18px ${N2.accentGlow}`,
  };
}
