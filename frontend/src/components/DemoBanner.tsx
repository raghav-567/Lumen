'use client';

// A subtle, fixed badge shown only when the app runs in demo mode
// (NEXT_PUBLIC_DEMO_MODE=true) so visitors know the data is a bundled snapshot
// served without a backend. Renders nothing in normal (backed) mode.
export default function DemoBanner() {
  if (process.env.NEXT_PUBLIC_DEMO_MODE !== 'true') return null;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 16,
        right: 16,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '7px 12px',
        fontSize: '0.72rem',
        fontWeight: 600,
        color: 'var(--text-secondary)',
        background: 'rgba(255,255,255,0.9)',
        backdropFilter: 'blur(8px)',
        border: '1px solid var(--border, rgba(0,0,0,0.08))',
        borderRadius: 999,
        boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
        pointerEvents: 'none',
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: 'var(--accent-emerald, #10b981)',
          display: 'inline-block',
        }}
      />
      Demo mode — sample data, no backend
    </div>
  );
}
