import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const directory = dirname(fileURLToPath(import.meta.url));
const tests = readdirSync(directory)
  .filter((name) => name.endsWith(".test.mjs"))
  .sort()
  .map((name) => join(directory, name));

// Vite middleware 인스턴스들이 공용 HMR port를 동시에 점유해 성공 실행에도 충돌
// 경고를 남기지 않도록 파일 단위 실행을 직렬화한다.
const result = spawnSync(process.execPath, ["--test", "--test-concurrency=1", ...tests], {
  stdio: "inherit",
});

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
