import { useEffect } from 'react';

const CONFIG = {
  success: { icon: '✓', label: 'Completado' },
  error:   { icon: '✕', label: 'Error' },
  warning: { icon: '!', label: 'Atención' },
};

export function AlertContainer({ alerts, onDismiss }) {
  if (alerts.length === 0) return null;
  return (
    <div className="alert-container">
      {alerts.map((a) => (
        <AlertToast key={a.id} alert={a} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function AlertToast({ alert, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(() => onDismiss(alert.id), 5000);
    return () => clearTimeout(t);
  }, [alert.id, onDismiss]);

  const { icon, label } = CONFIG[alert.type] || CONFIG.success;

  return (
    <div className={`alert-toast alert-${alert.type}`} role="alert">
      <span className="alert-icon">{icon}</span>
      <div className="alert-body">
        <div className="alert-type">{label}</div>
        <div className="alert-msg">{alert.message}</div>
      </div>
      <button className="alert-close" onClick={() => onDismiss(alert.id)} aria-label="Cerrar">×</button>
    </div>
  );
}
