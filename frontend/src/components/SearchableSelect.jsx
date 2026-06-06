import { useEffect, useRef, useState } from 'react';

export function SearchableSelect({
  options = [],
  value,
  onChange,
  placeholder = 'Seleccionar...',
  required = false,
  disabled = false,
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const wrapRef = useRef(null);
  const searchRef = useRef(null);

  const selected = options.find((o) => String(o.value) === String(value));

  const filtered = query
    ? options.filter((o) =>
        o.label.toLowerCase().includes(query.toLowerCase()) ||
        (o.sub || '').toLowerCase().includes(query.toLowerCase())
      )
    : options;

  useEffect(() => {
    if (open && searchRef.current) searchRef.current.focus();
  }, [open]);

  useEffect(() => {
    function handleDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
        setQuery('');
      }
    }
    document.addEventListener('mousedown', handleDown);
    return () => document.removeEventListener('mousedown', handleDown);
  }, []);

  function handleKey(e) {
    if (e.key === 'Escape') { setOpen(false); setQuery(''); }
    if (e.key === 'Enter' && filtered.length > 0) { pick(filtered[0].value); }
  }

  function pick(val) {
    onChange(val);
    setOpen(false);
    setQuery('');
  }

  function clear(e) {
    e.stopPropagation();
    onChange('');
  }

  return (
    <div
      ref={wrapRef}
      className={`ss${open ? ' ss-open' : ''}${disabled ? ' ss-disabled' : ''}`}
    >
      <button
        type="button"
        className="ss-trigger"
        onClick={() => !disabled && setOpen((v) => !v)}
      >
        {selected ? (
          <span className="ss-selected-label">
            {selected.label}
            {selected.sub && <span className="ss-selected-sub">{selected.sub}</span>}
          </span>
        ) : (
          <span className="ss-ph">{placeholder}</span>
        )}
        <span className="ss-icons">
          {selected && !required && (
            <span className="ss-x" onClick={clear} title="Limpiar selección">×</span>
          )}
          <span className="ss-chevron">{open ? '▲' : '▼'}</span>
        </span>
      </button>

      {open && (
        <div className="ss-drop">
          <div className="ss-search-row">
            <input
              ref={searchRef}
              className="ss-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Escribir para filtrar..."
            />
            {query && (
              <button className="ss-search-clear" onClick={() => setQuery('')}>×</button>
            )}
          </div>
          <div className="ss-list">
            {filtered.length === 0 ? (
              <div className="ss-no-result">Sin resultados para "{query}"</div>
            ) : (
              filtered.map((o) => (
                <div
                  key={o.value}
                  className={`ss-opt${String(o.value) === String(value) ? ' ss-opt-active' : ''}`}
                  onClick={() => pick(o.value)}
                >
                  <span className="ss-opt-label">{o.label}</span>
                  {o.sub && <span className="ss-opt-sub">{o.sub}</span>}
                </div>
              ))
            )}
          </div>
          {filtered.length > 0 && (
            <div className="ss-foot">
              {filtered.length} resultado{filtered.length !== 1 ? 's' : ''}
              {query && ` para "${query}"`}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
