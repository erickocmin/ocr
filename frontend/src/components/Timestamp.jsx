export function Timestamp({ value }) {
  if (!value) return <span className="text-muted">—</span>;
  const d = new Date(value);
  const formatted = d.toLocaleString('es-PE', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
  return (
    <time dateTime={value} title={d.toLocaleString('es-PE')} className="timestamp">
      {formatted}
    </time>
  );
}

export function DateOnly({ value }) {
  if (!value) return <span className="text-muted">—</span>;
  const d = new Date(value + 'T00:00:00');
  return (
    <time dateTime={value} className="timestamp">
      {d.toLocaleDateString('es-PE', { day: '2-digit', month: 'short', year: 'numeric' })}
    </time>
  );
}
