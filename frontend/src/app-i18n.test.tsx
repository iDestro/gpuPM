import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { api, bytes, date, duration, queryClient, setSession } from "./api";
import { setLocale, translate } from "./i18n";
import { ChangePreview, creationStageLabel, errorGuidance, readonlyReason } from "./readiness";

vi.mock("./pages", () => Object.fromEntries(
  ["Accounts", "BusinessGroups", "BusinessUsers", "Logs", "Overview", "Settings", "Shares", "Storage", "SystemGroups", "TaskDetail", "Tasks"].map(name => [name, () => null]),
));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  queryClient.clear();
  setSession(null);
  setLocale("zh-CN");
});

test("login language switch translates fields without discarding credentials", async () => {
  setLocale("zh-CN");
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(
    JSON.stringify(url.endsWith("/health") ? {status:"ok",mode:"demo",mutations:true,root_readiness:{ready:true,error_code:null}} : { detail: "unauthorized" }),
    { status: url.endsWith("/health") ? 200 : 401 },
  )));
  render(<AntApp><QueryClientProvider client={queryClient}><MemoryRouter><App /></MemoryRouter></QueryClientProvider></AntApp>);
  const account = await screen.findByLabelText("管理员账号");
  await userEvent.type(account, "admin-name");
  await userEvent.click(screen.getByRole("combobox", { name: "语言 / Language" }));
  await userEvent.click(screen.getByText("English", { exact: true }));
  expect(screen.getByLabelText("Administrator account")).toHaveValue("admin-name");
  expect(screen.getByRole("heading", { name: "Administrator sign-in" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("authenticated navigation updates in place and preserves account identity", async () => {
  setLocale("zh-CN");
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith("/health") ? {status:"ok",mode:"demo",mutations:true,root_readiness:{ready:true,error_code:null}} : { username: "管理员-admin", csrf_token: "token" },
  ))));
  render(<AntApp><QueryClientProvider client={queryClient}><MemoryRouter initialEntries={["/accounts"]}><App /></MemoryRouter></QueryClientProvider></AntApp>);
  await screen.findByText("管理员-admin");
  for (const name of ["本地账号", "任务策略组", "系统用户组", "团队共享目录", "操作审计"]) expect(screen.getByRole("menuitem", {name})).toBeVisible();
  await userEvent.click(screen.getByRole("combobox", { name: "语言 / Language" }));
  await userEvent.click(screen.getByText("English", { exact: true }));
  expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  expect(screen.getAllByText("Local accounts")).toHaveLength(2);
  expect(screen.getByText("管理员-admin")).toBeVisible();
  expect(screen.getByRole("button", { name: "Sign out" })).toBeVisible();
});

test("format helpers follow locale and API server reasons remain raw", async () => {
  setLocale("en-US");
  expect(bytes(null)).toBe("No data");
  expect(bytes(1024)).toBe("1.0 KiB");
  expect(duration(-3660)).toBe("Overdue 1h 1m");
  expect(date("2026-10-14T00:00:00Z")).toBe(new Date("2026-10-14T00:00:00Z").toLocaleString("en-US", { timeZone: "Asia/Shanghai", hour12: false }));
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { code: "protected", message: "受保护任务" } }), { status: 409 })));
  await expect(api("/tasks/one")).rejects.toThrow("受保护任务");
  setLocale("zh-CN");
  expect(bytes(null)).toBe("无数据");
  expect(duration(-3660)).toBe("超时 1时 1分");
});


test("recovery and capability error codes have actionable translated guidance", () => {
  const codes = ["creation_not_pending", "invalid_profile", "external_policy_changed", "login_policy_unverified", "credentials_in_preview", "capability_unavailable", "device_mismatch", "device_unavailable", "unsafe_path", "uid_lifecycle_conflict"];
  setLocale("en-US");
  for (const code of codes) {
    expect(errorGuidance[code], code).toBeTruthy();
    expect(translate(errorGuidance[code]), code).not.toMatch(/[\u3400-\u9fff]/);
  }
  expect(readonlyReason({readonly_reasons:["protected_account"]})).toBe("Protected account");
});


test("account preview retains requested fields absent from the proposed summary", () => {
  setLocale("en-US");
  render(<AntApp><ChangePreview data={{kind:"account",action:"update",id:"1001",current:{username:"alice"},proposed:{username:"alice"},changes:{notes:"review this requested note",public_keys:["ssh-ed25519 public-key-to-review"]}}}/></AntApp>);
  expect(screen.getByText("review this requested note")).toBeVisible();
  expect(screen.getByText("ssh-ed25519 public-key-to-review")).toBeVisible();
});

test("adoption manual instructions and creation stages have Chinese and English labels", () => {
 const steps=[
  "Root must inspect the existing home and data paths and prepare account-owned private directories.",
  "Existing home paths outside configured roots require a separately approved migration; this operation never moves data.",
  "Repeat the preview after resolving every failed check.",
 ];
 setLocale("zh-CN");
 const view=render(<ChangePreview data={{kind:"account",adoption:{checks:[],manual_steps:steps}}}/>);
 expect(screen.getByText("管理员需检查已有主目录和数据目录，并准备由该账号所有的私有目录。")).toBeVisible();
 expect(screen.getByText("已有主目录位于配置根目录之外时，必须另行批准迁移；本操作不会移动数据。")).toBeVisible();
 expect(screen.getByText("修复全部未通过的检查项后，请重新预览。")).toBeVisible();
 expect(creationStageLabel("directories")).toBe("准备私有目录");
 expect(creationStageLabel("initialized")).toBe("初始化完成");
 expect(creationStageLabel("future_stage")).toBe("future_stage");
 setLocale("en-US");view.rerender(<ChangePreview data={{kind:"account",adoption:{checks:[],manual_steps:steps}}}/>);
 for(const step of steps) expect(screen.getByText(step)).toBeVisible();
 expect(creationStageLabel("directories")).toBe("Preparing private directories");
 expect(creationStageLabel("login_pending")).toBe("Login policy pending");
});
