import assert from "node:assert/strict";
import { test } from "node:test";

import {
  clearAuthenticatedBrowserState,
} from "../../app/frontend/src/authenticatedBrowserState.js";

function storageFixture(entries) {
  const values = new Map(entries);
  return {
    get length() { return values.size; },
    key(index) { return [...values.keys()][index] ?? null; },
    removeItem(key) { values.delete(key); },
    entries() { return [...values.entries()]; },
  };
}

test("logout cleanup removes all Answervice user state and preserves foreign keys", () => {
  const storage = storageFixture([
    ["answervice.activeConversationId", "conversation-a"],
    ["answervice.questionDraft", "question-a"],
    ["answervice:report-draft:v2:def:1", "draft-a"],
    ["another-application.preference", "keep"],
  ]);

  clearAuthenticatedBrowserState(storage);

  assert.deepEqual(storage.entries(), [["another-application.preference", "keep"]]);
});

test("cleanup tolerates an empty storage", () => {
  const storage = storageFixture([]);

  clearAuthenticatedBrowserState(storage);

  assert.deepEqual(storage.entries(), []);
});
