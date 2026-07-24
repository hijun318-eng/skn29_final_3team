import { publishOperationAlerts } from "./operationAlerts";

const STORAGE_KEY = "senseplace.live.voc";
const UPDATE_EVENT = "senseplace:voc-updated";

export function getLiveVocEvents() {
  try {
    const events = JSON.parse(window.localStorage.getItem(STORAGE_KEY));
    return Array.isArray(events) ? events : [];
  } catch {
    return [];
  }
}

export function publishLiveVoc({ facilityId, facilityName, rating, comment, reasons = [], photos = [], source }) {
  const event = {
    id: `voc-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    facilityId,
    facilityName,
    rating,
    comment: comment.trim() || `${facilityName} 이용 경험 ${rating}점`,
    reasons,
    photos: photos.map((photo) => ({ name: photo.name, type: photo.type, size: photo.size })),
    source,
    createdAt: new Date().toISOString(),
  };
  const events = [event, ...getLiveVocEvents()].slice(0, 50);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(events));
  window.dispatchEvent(new CustomEvent(UPDATE_EVENT, { detail: events }));

  if (rating <= 3) {
    publishOperationAlerts([{
      id: `guest-voc-${event.id}`,
      facilityId,
      severity: rating <= 2 ? "danger" : "warning",
      title: `${facilityName} 고객 VOC 접수`,
      message: `${rating}점 · ${event.comment}`,
      source: "guest-voc",
    }]);
  }
  return event;
}

export const liveVocStorageKey = STORAGE_KEY;
export const liveVocEvent = UPDATE_EVENT;
