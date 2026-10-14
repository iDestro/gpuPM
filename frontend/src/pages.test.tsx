import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { queryClient, setSession } from "./api";
import { Accounts, Storage } from "./pages";
import App from "./App";
const account = {
  id: "alice",
  username: "alice",
  uid: 1001,
  gid: 1001,
  managed: true,
  protected: false,
  status: "active",
  revision: 7,
  priority: 50,
  shell: "/bin/bash",
  public_keys: [],
  groups: [],
};
function renderPage(page: React.ReactNode, path = "/accounts") {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>{page}</MemoryRouter>
    </QueryClientProvider>,
  );
}
function mockServer() {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => {
    const path = url.split("?")[0];
    let data: unknown = [];
    if (path === "/api/auth/me")
      data = { username: "admin", csrf_token: "csrf" };
    else if (path === "/api/health") data = { mode: "demo", status: "ok" };
    else if (path === "/api/system-users" && options?.method === "GET")
      data = [account];
    else if (path === "/api/system-groups")
      data = [{ id: "research", name: "research", protected: false }];
    else if (path.endsWith("/change-preview"))
      data = {
        token: "rename-scope",
        expires_at: "2099-01-01T00:00:00Z",
        changes: { username: "alicia" },
      };
    else if (path === "/api/system-users/alice")
      data = { ...account, username: "alicia", revision: 8 };
    else if (path === "/api/groups")
      data = [{ id: "default", name: "默认", priority: 50 }];
    else if (path === "/api/login-events" || path === "/api/audit-logs")
      data = { items: [], total: 0, coverage: "日志可用" };
    return new Response(JSON.stringify(data));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  queryClient.clear();
  setSession(null);
});
test("rename edit submits new username through revision-bound preview before PATCH", async () => {
  const fetch = mockServer();
  renderPage(<Accounts />);
  await userEvent.click(await screen.findByRole("button", { name: /编\s*辑/ }));
  expect(screen.getByLabelText("普通主系统组")).toBeInTheDocument();
  const username = screen.getByLabelText("用户名");
  await userEvent.clear(username);
  await userEvent.type(username, "alicia");
  expect(
    screen.getByText(/没有运行进程、登录会话或定时任务/),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
  await screen.findByText(/范围由服务器核验/);
  const preview = fetch.mock.calls.find(([url]) =>
    url.endsWith("/change-preview"),
  );
  expect(JSON.parse(String(preview?.[1]?.body))).toMatchObject({
    action: "update",
    revision: 7,
    changes: { username: "alicia" },
  });
  expect(
    fetch.mock.calls.some(([, options]) => options?.method === "PATCH"),
  ).toBe(false);
  await userEvent.type(screen.getByLabelText("操作原因"), "空闲账号改名");
  await userEvent.click(screen.getByRole("button", { name: "确认执行" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(([, options]) => options?.method === "PATCH"),
    ).toBe(true),
  );
  const patch = fetch.mock.calls.find(
    ([, options]) => options?.method === "PATCH",
  );
  expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
    username: "alicia",
    revision: 7,
    token: "rename-scope",
  });
  expect(screen.queryByLabelText("普通主系统组")).not.toBeInTheDocument();
}, 10000);
test("login filters never leak into audit filters when navigating the actual app", async () => {
  const fetch = mockServer();
  renderPage(<App />, "/login-events");
  await screen.findByLabelText("username");
  await userEvent.type(screen.getByLabelText("username"), "alice");
  await userEvent.type(screen.getByLabelText("ip"), "192.0.2.1");
  await userEvent.click(screen.getByText("操作审计"));
  await screen.findByLabelText("actor");
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(([url]) => url.startsWith("/api/audit-logs")),
    ).toBe(true),
  );
  const requests = fetch.mock.calls.filter(([url]) =>
    url.startsWith("/api/audit-logs"),
  );
  for (const [url] of requests) {
    expect(url).not.toContain("username=");
    expect(url).not.toContain("ip=");
  }
  await userEvent.click(screen.getByText("SSH 登录记录"));
  await screen.findByLabelText("username");
  expect(screen.getByLabelText("username")).toHaveValue("");
  expect(screen.getByLabelText("ip")).toHaveValue("");
});
test("storage displays server ACL diagnosis without claiming tool presence means working ACL", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            filesystems: [],
            users: [],
            shares: [],
            alerts: [],
            capabilities: {
              acl: {
                status: "unavailable",
                message: "目标数据卷未验证 ACL，需宿主机检查挂载与实际访问",
              },
            },
          }),
        ),
    ),
  );
  renderPage(<Storage />);
  await screen.findByText("ACL 能力：unavailable");
  expect(
    screen.getByText("目标数据卷未验证 ACL，需宿主机检查挂载与实际访问"),
  ).toBeInTheDocument();
});
test("account creation supports SSH public key without requiring an initial password", async () => {
  const fetch = mockServer();
  const user = userEvent.setup();
  renderPage(<Accounts />);
  await user.click(screen.getByRole("button", { name: "创建账号" }));
  await user.type(screen.getByLabelText("用户名"), "keyuser");
  await user.click(screen.getByLabelText("SSH 公钥（一行一个，输入后回车添加）"));
  await user.paste("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICQ2fxiSTULMprkrEkYnUDOgIpIu3RrxpsXAOk9MZWzg keyuser");
  await user.keyboard("{Enter}");
  await user.click(screen.getByRole("button", { name: /保\s*存/ }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([url, options]) =>
          url === "/api/system-users" && options?.method === "POST",
      ),
    ).toBe(true),
  );
  const create = fetch.mock.calls.find(
    ([url, options]) =>
      url === "/api/system-users" && options?.method === "POST",
  );
  const body = JSON.parse(String(create?.[1]?.body));
  expect(body.username).toBe("keyuser");
  expect(body.public_keys).toHaveLength(1);
  expect(body.password).toBeUndefined();
  expect(body.require_password_change).toBe(true);
});

test("storage cold cache shows collecting state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({status:"pending",collected_at:null,stale:true,filesystems:[],users:[],shares:[],alerts:[]}))));
  renderPage(<Storage />);
  expect(await screen.findByText("正在统计存储用量，完成后自动更新。")).toBeInTheDocument();
});
