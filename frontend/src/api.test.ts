import { afterEach, expect, test, vi } from "vitest";
import { api, setSession, queryClient } from "./api";
afterEach(() => {
  vi.unstubAllGlobals();
  setSession(null);
  queryClient.clear();
});
test("authenticated mutations send CSRF and cookie credentials exactly once", async () => {
  setSession({ username: "admin", csrf_token: "safe-token" });
  const fetch = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  await api("/tasks/one", "PATCH", { revision: 4, priority: 80 });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/api/tasks/one");
  expect(fetch.mock.calls[0][1]).toMatchObject({
    credentials: "same-origin",
    headers: { "X-CSRF-Token": "safe-token" },
    body: JSON.stringify({ revision: 4, priority: 80 }),
  });
  expect(queryClient.getDefaultOptions().mutations?.retry).toBe(false);
});
test("failed dangerous mutation reports server reason without retry", async () => {
  setSession({ username: "admin", csrf_token: "token" });
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "protected", message: "受保护任务" },
        }),
        { status: 409 },
      ),
    );
  vi.stubGlobal("fetch", fetch);
  await expect(api("/tasks/one/terminate", "POST", {})).rejects.toThrow(
    "受保护任务",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
});
