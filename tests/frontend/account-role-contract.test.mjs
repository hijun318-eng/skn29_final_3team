import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { createAdminClient } from "../../app/frontend/src/api/adminClient.ts";
import { createHttpAnalysisClient } from "../../app/frontend/src/api/analysisClient.ts";
import {
  AUTH_ACCOUNT_ROLE_OPTIONS,
  roleLabel,
} from "../../app/frontend/src/authorization.ts";


const directory = dirname(fileURLToPath(import.meta.url));
const frontend = join(directory, "../../app/frontend/src");

assert.deepEqual(AUTH_ACCOUNT_ROLE_OPTIONS, [
  { value: "analyst", label: "분석 사용자" },
  { value: "admin", label: "관리자" },
]);
assert.equal(roleLabel("analyst"), "분석 사용자");
assert.equal(roleLabel("admin"), "관리자");
assert.equal(roleLabel("platform_admin"), "알 수 없는 역할");

for (const role of ["report_admin", "data_admin", "platform_admin"]) {
  const sessionClient = createHttpAnalysisClient(
    "http://backend.test",
    async () => new Response(JSON.stringify({
      data: { status: "authenticated", role, capabilities: [] },
    }), { status: 200 }),
  );
  await assert.rejects(
    () => sessionClient.validateSession(),
    /인증 API가 올바르지 않은 응답을 반환했습니다/,
  );
}

const account = {
  subject: "00000000-0000-0000-0000-000000000001",
  username: "admin-user",
  role: "admin",
  active: true,
  created_at: "2026-08-31T00:00:00Z",
  updated_at: "2026-08-31T00:00:00Z",
  deactivated_at: null,
  deleted_at: null,
};
const publicClient = createAdminClient(
  "http://backend.test",
  async () => new Response(JSON.stringify({
    data: { items: [account], page: 1, page_size: 50, total: 1 },
  }), { status: 200 }),
);
assert.equal((await publicClient.listAccounts()).items[0].role, "admin");

for (const role of ["report_admin", "data_admin", "platform_admin"]) {
  const responseClient = createAdminClient(
    "http://backend.test",
    async () => new Response(JSON.stringify({
      data: { items: [{ ...account, role }], page: 1, page_size: 50, total: 1 },
    }), { status: 200 }),
  );
  await assert.rejects(
    () => responseClient.listAccounts(),
    /관리자 계정 API가 올바르지 않은 응답/,
  );
}

let requestCount = 0;
const requestClient = createAdminClient("http://backend.test", async () => {
  requestCount += 1;
  return new Response(JSON.stringify({ data: account }), { status: 201 });
});
for (const role of ["report_admin", "data_admin", "platform_admin"]) {
  await assert.rejects(
    () => requestClient.createAccount({
      username: "legacy",
      password: "temporary-password",
      role,
    }),
    /analyst 또는 admin/,
  );
}
assert.equal(requestCount, 0);

for (const relativePath of [
  "authorization.ts",
  "api/analysisClient.ts",
  "api/adminClient.ts",
  "pages/AdminPage.jsx",
]) {
  const source = readFileSync(join(frontend, relativePath), "utf-8");
  assert.doesNotMatch(source, /\b(?:report_admin|data_admin|platform_admin)\b/);
}
