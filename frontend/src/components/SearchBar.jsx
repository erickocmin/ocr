export function SearchBar({ value, onChange, placeholder = 'Buscar...' }) {
  return (
    <div className="search-wrap">
      <span className="search-icon">&#8981;</span>
      <input
        type="search"
        className="search-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      {value && (
        <button className="search-clear" onClick={() => onChange('')} aria-label="Limpiar búsqueda">
          ×
        </button>
      )}
    </div>
  );
}
