import { N2, fSerif } from '../../theme';
import { useStore } from '../../store';

export function N2EmptyHero() {
  const kind = useStore((s) => s.active);
  const isCompany = kind === 'company';
  const subject = isCompany ? 'company names' : 'first names';
  return (
    <div
      style={{
        height: '100%',
        minHeight: 420,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 40,
      }}
    >
      <div style={{ textAlign: 'center', maxWidth: 560 }}>
        <div
          style={{
            fontFamily: fSerif,
            fontStyle: 'italic',
            fontSize: 62,
            color: N2.accent,
            letterSpacing: -2,
            lineHeight: 1,
            fontWeight: 400,
            fontVariationSettings: '"opsz" 144, "SOFT" 100',
          }}
        >
          Bring your list.
        </div>
        <div
          style={{
            fontFamily: fSerif,
            fontSize: 62,
            color: N2.text,
            letterSpacing: -2,
            lineHeight: 1,
            marginTop: 6,
            fontWeight: 400,
            fontVariationSettings: '"opsz" 144',
          }}
        >
          We'll read it carefully.
        </div>
        <div
          style={{
            color: N2.text2,
            fontSize: 13.5,
            lineHeight: 1.7,
            marginTop: 26,
            maxWidth: 460,
            margin: '26px auto 0',
          }}
        >
          Drop a CSV on the left. Grok reads each {subject.replace(/s$/, '')}, explains
          what's off, and returns an auditable list — every change, with reasoning.
        </div>
      </div>
    </div>
  );
}
