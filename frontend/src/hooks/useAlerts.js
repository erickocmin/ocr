import { useCallback, useState } from 'react';

let nextId = 1;

export function useAlerts() {
  const [alerts, setAlerts] = useState([]);

  const addAlert = useCallback((type, message) => {
    const id = nextId++;
    setAlerts((prev) => [...prev, { id, type, message }]);
    return id;
  }, []);

  const removeAlert = useCallback((id) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const success = useCallback((msg) => addAlert('success', msg), [addAlert]);
  const error = useCallback((msg) => addAlert('error', msg), [addAlert]);
  const warning = useCallback((msg) => addAlert('warning', msg), [addAlert]);

  return { alerts, removeAlert, success, error, warning };
}
