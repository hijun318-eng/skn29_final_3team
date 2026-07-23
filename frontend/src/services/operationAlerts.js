const STORAGE_KEY = "senseplace.operation.alerts";
const DISMISSED_STORAGE_KEY = "senseplace.operation.alerts.dismissed";
const UPDATE_EVENT = "senseplace:alerts-updated";

export function getOperationAlerts() {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY));
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function saveOperationAlerts(alerts) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(alerts));
  window.dispatchEvent(new CustomEvent(UPDATE_EVENT, { detail: alerts }));
}

function getDismissedOperationAlertIds() {
  try {
    const value = JSON.parse(window.localStorage.getItem(DISMISSED_STORAGE_KEY));
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function saveDismissedOperationAlertIds(ids) {
  window.localStorage.setItem(DISMISSED_STORAGE_KEY, JSON.stringify([...new Set(ids)].slice(-100)));
}

export function publishOperationAlerts(nextAlerts) {
  const current = getOperationAlerts();
  const currentById = new Map(current.map((alert) => [alert.id, alert]));
  const dismissedIds = new Set(getDismissedOperationAlertIds());
  const detectedAt = new Date().toISOString();
  nextAlerts.filter((alert) => !dismissedIds.has(alert.id)).forEach((alert) => {
    const previous = currentById.get(alert.id);
    currentById.set(alert.id, { ...alert, detectedAt: previous?.detectedAt || detectedAt });
  });
  const merged = [...currentById.values()].sort((a, b) => new Date(b.detectedAt) - new Date(a.detectedAt)).slice(0, 20);
  saveOperationAlerts(merged);
  return merged;
}

export function dismissOperationAlert(alertId) {
  saveDismissedOperationAlertIds([...getDismissedOperationAlertIds(), alertId]);
  saveOperationAlerts(getOperationAlerts().filter((alert) => alert.id !== alertId));
}

export function clearOperationAlerts() {
  saveDismissedOperationAlertIds([...getDismissedOperationAlertIds(), ...getOperationAlerts().map((alert) => alert.id)]);
  saveOperationAlerts([]);
}

export const operationAlertEvent = UPDATE_EVENT;
