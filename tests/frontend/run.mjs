import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const directory = dirname(fileURLToPath(import.meta.url));
const tests = readdirSync(directory)
  .filter((name) => name.endsWith(".test.mjs"))
  .sort()
  .map((name) => join(directory, name));

const result = spawnSync(process.execPath, ["--test", ...tests], {
  stdio: "inherit",
});

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
