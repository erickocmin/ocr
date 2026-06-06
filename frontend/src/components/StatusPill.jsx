export function StatusPill({ variant = 'secondary', children }) {
  return <span className={`pill pill-${variant}`}>{children}</span>;
}

export function BoolPill({ value, trueLabel = 'Sí', falseLabel = 'No' }) {
  return (
    <StatusPill variant={value ? 'success' : 'danger'}>
      {value ? trueLabel : falseLabel}
    </StatusPill>
  );
}
