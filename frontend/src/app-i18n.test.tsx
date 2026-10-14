import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { api, bytes, date, duration, queryClient, setSession } from "./api";
import { setLocale } from "./i18n";

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
    JSON.stringify(url.endsWith("/health") ? { mode: "demo" } : { detail: "unauthorized" }),
    { status: url.endsWith("/health") ? 200 : 401 },
  )));
  render(<MemoryRouter><App /></MemoryRouter>);
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
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url.endsWith("/health") ? { mode: "demo" } : { username: "管理员-admin", csrf_token: "token" },
  ))));
  render(<MemoryRouter initialEntries={["/accounts"]}><App /></MemoryRouter>);
  await screen.findByText("管理员-admin");
  await userEvent.click(screen.getByRole("combobox", { name: "语言 / Language" }));
  await userEvent.click(screen.getByText("English", { exact: true }));
  expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
  expect(screen.getAllByText("Linux local accounts")).toHaveLength(2);
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
