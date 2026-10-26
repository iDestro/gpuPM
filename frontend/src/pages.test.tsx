import { UserTaskPolicy } from "./user-groups";
import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { queryClient, setSession } from "./api";
import { Accounts, Storage, Tasks, SystemGroups } from "./pages";
import App from "./App";
const account = {
  id: "alice",
  username: "alice",
  uid: 1001,
  gid: 1001,
  managed: true,
  protected: false,
  is_human: true,
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
    else if (path === "/api/health") data = { mode: "demo", status: "ok", mutations: true };
    else if (path === "/api/system-users" && options?.method === "GET")
      data = [account];
    else if (path === "/api/system-groups")
      data = [{ id: "research", name: "research", protected: false, assignable: true }];
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
  await screen.findByLabelText("用户名");
  await userEvent.type(screen.getByLabelText("用户名"), "alice");
  await userEvent.type(screen.getByLabelText("来源 IP"), "192.0.2.1");
  await userEvent.click(screen.getByText("操作审计"));
  await screen.findByLabelText("操作人");
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
  await screen.findByLabelText("用户名");
  expect(screen.getByLabelText("用户名")).toHaveValue("");
  expect(screen.getByLabelText("来源 IP")).toHaveValue("");
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
  await screen.findByText("共享权限工具不可用");
  await userEvent.click(screen.getByText("存储诊断详情"));
  expect(
    screen.getByText(/目标数据卷未验证 ACL，需宿主机检查挂载与实际访问/),
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
  expect(body.groups).toEqual([]);
}, 10000);

test("storage cold cache shows collecting state", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({status:"pending",collected_at:null,stale:true,filesystems:[],users:[],shares:[],alerts:[]}))));
  renderPage(<Storage />);
  expect(await screen.findByText("正在统计存储用量，完成后自动更新。")).toBeInTheDocument();
});

test("accounts default to human scope and other accounts remain readonly", async () => {
  const request = vi.fn(async (url: string) => new Response(JSON.stringify(url === '/api/health' ? {mutations:true,mode:'demo'} : url.startsWith("/api/system-users") ? [{...account,is_human:false}] : [])));
  vi.stubGlobal("fetch", request);
  renderPage(<Accounts />);
  expect(await screen.findByRole("button", {name:/编\s*辑/})).toBeDisabled();
  expect(screen.getByRole("button", {name:/停\s*用/})).toBeDisabled();
  expect(request.mock.calls.find(([url])=>url.includes("scope=human"))?.[0]).toContain("scope=human");
  await userEvent.click(screen.getByRole("combobox", {name:"账号范围"}));
  await userEvent.click(screen.getByText("其他账号（只读）", {exact:true}));
  await waitFor(()=>expect(request.mock.calls.some(([url])=>url.includes("scope=other"))).toBe(true));
  await userEvent.click(screen.getByRole("combobox", {name:"账号范围"}));
  await userEvent.click(screen.getByText("全部账号", {exact:true}));
  await waitFor(()=>expect(request.mock.calls.some(([url])=>url.includes("scope=all"))).toBe(true));
}, 10000);
test("task list defaults to human and opens existing termination preview", async () => {
  const request = vi.fn(async (url: string) => new Response(JSON.stringify(url === '/api/health' ? {mutations:true,mode:'demo'} : url.startsWith("/api/tasks?") ? {items:[{id:"task",name:"training",is_human:true,protected:false},{id:"service",name:"service",is_human:false}],total:2} : url.endsWith("termination-preview") ? {token:"kill-token",expires_at:"2099-01-01T00:00:00Z",members:[]} : [])));
  vi.stubGlobal("fetch", request);
  renderPage(<Tasks />, "/tasks");
  const buttons = await screen.findAllByRole("button", {name:"终止任务"});
  expect(buttons[0]).toBeEnabled();
  expect(buttons[1]).toBeDisabled();
  expect(request.mock.calls.find(([url])=>url.includes("scope=human"))?.[0]).toContain("scope=human");
  expect(request.mock.calls.find(([url])=>url.startsWith("/api/tasks?"))?.[0]).toContain("status=active");
  expect(screen.getByText("全部进行中任务", {exact:true})).toBeVisible();
  expect(request.mock.calls.some(([url]) => url === "/api/users?scope=human")).toBe(true);
  await userEvent.click(buttons[0]);
  await screen.findByText("终止范围预览");
  await waitFor(()=>expect(request.mock.calls.some(([url])=>url.endsWith("/task/termination-preview"))).toBe(true));
  expect(request.mock.calls.some(([url])=>url.endsWith("/terminate"))).toBe(false);
});
test("other business users cannot edit policy", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url:string)=>new Response(JSON.stringify(url === '/api/health' ? {mutations:true,mode:'demo'} : url === "/api/users" ? [{uid:1,username:"service",is_human:false}] : []))));
  renderPage(<UserTaskPolicy account={{uid:1}}/>, "/users");
  expect(await screen.findByRole("button",{name:"配置任务策略"})).toBeDisabled();
});

test("human system group is readonly even without a protected flag", async () => {
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify([{id:"human",name:"human",managed:true,protected:false,members:[]}]))));
  renderPage(<SystemGroups />);
  await screen.findByText("human", {exact:true});
  expect(screen.queryByRole("button",{name:/编\s*辑/})).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"删除空组"})).not.toBeInTheDocument();
});
