import assert from "node:assert/strict";
import test from "node:test";

import { nextTheme, readTheme, saveTheme, THEME_STORAGE_KEY } from "../../app/frontend/src/themePreference.js";

test("theme defaults to light and restores only an explicit dark preference", () => {
  assert.equal(readTheme({ getItem: () => null }), "light");
  assert.equal(readTheme({ getItem: () => "system" }), "light");
  assert.equal(readTheme({ getItem: (key) => key === THEME_STORAGE_KEY ? "dark" : null }), "dark");
  assert.equal(readTheme({ getItem: () => { throw new Error("storage blocked"); } }), "light");
});

test("theme toggle switches between the two supported modes", () => {
  assert.equal(nextTheme("light"), "dark");
  assert.equal(nextTheme("dark"), "light");
});

test("theme preference writes through the dedicated non-sensitive storage boundary", () => {
  const written = [];
  saveTheme("dark", { setItem: (...entry) => written.push(entry) });
  assert.deepEqual(written, [[THEME_STORAGE_KEY, "dark"]]);
  assert.doesNotThrow(() => saveTheme("light", { setItem: () => { throw new Error("storage blocked"); } }));
});
