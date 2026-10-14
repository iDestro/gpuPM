import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "./api";
import { CompactText, Status } from "./components";
import { Accounts, Logs } from "./pages";
afterEach(() => { cleanup(); vi.unstubAllGlobals(); queryClient.clear(); });
test("known status labels are Chinese while unknown codes remain intact", () => {
  render(<><Status value="running" /><Status value="failure" /><Status value="finished" /><Status value="future-status" /></>);
  expect(screen.getByText("运行中")).toBeInTheDocument();
  expect(screen.getByText("失败")).toBeInTheDocument();
  expect(screen.getByText("已结束")).toBeInTheDocument();
  expect(screen.getByText("future-status")).toHaveAttribute("title", "future-status");
});
function logs(kind: "audit" | "login", data: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(data))));
  return render(<QueryClientProvider client={queryClient}><MemoryRouter><Logs kind={kind} /></MemoryRouter></QueryClientProvider>);
}
test("audit keeps full long values in compact cells and raw details on expansion", async () => {
  const actor = "administrator-".repeat(30);
  const target = "/srv/research/".repeat(30);
  const before = { home: target, token: "original-record" };
  logs("audit", {items: [{id: "audit1", time: "2026-10-14T00:00:00Z", actor, action: "account.update", target, result: "success", before}], total: 1});
  const cell = await screen.findByText(actor);
  expect(cell).toHaveClass("compact-text");
  expect(cell).toHaveAttribute("title", actor);
  expect(cell).toHaveAttribute("tabindex", "0");
  expect(screen.getByText(target)).toHaveAttribute("title", target);
  expect(screen.getByText("修改账号")).toBeInTheDocument();
  expect(screen.getByText("成功")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name: /Expand row|展开行/}));
  expect(screen.getByText(JSON.stringify(before))).toBeInTheDocument();
  expect(screen.getByText("account.update")).toBeInTheDocument();
});
test("login coverage starts collapsed and exposes full raw JSON on demand", async () => {
  const coverage = { files: ["/var/log/auth.log"], warning: "历史日志不完整", nested: {raw: "retained"} };
  logs("login", {items: [], total: 0, coverage});
  const summary = await screen.findByText("日志扫描覆盖");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  await userEvent.click(summary);
  expect(summary.closest("details")).toHaveAttribute("open");
  expect(document.querySelector(".json-view")?.textContent).toBe(JSON.stringify(coverage, null, 2));
});


test("account summary shows effective expiry and explicit soft deletion with independent disable", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(url.startsWith("/api/system-users?") ? [{id:"account",username:"sample",uid:1001,gid:1001,is_human:true,managed:true,status:"deleted",deleted_at:"2026-10-14T00:00:00Z",disabled:true,expires_effective_at:"2030-01-01T00:00:00Z"}] : []))));
  render(<QueryClientProvider client={queryClient}><MemoryRouter><Accounts /></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByText("2030-01-01")).toBeInTheDocument();
  expect(screen.getByText("已软删除", {selector:".status-tag"})).toBeInTheDocument();
  expect(screen.getByText("停用限制")).toBeInTheDocument();
  expect(screen.queryByText("软删除限制")).not.toBeInTheDocument();
});

test("audit success filter submits the server's succeeded value", async () => {
  logs("audit", {items:[],total:0});
  await userEvent.click(screen.getByRole("combobox", {name:"结果筛选"}));
  await userEvent.click(screen.getByText("成功", {exact:true}));
  expect(vi.mocked(globalThis.fetch).mock.calls.some(([url])=>String(url).includes("result=succeeded"))).toBe(true);
});


test("task alias keeps its label while hover and focus expose the original name", async () => {
  render(<CompactText value="模型A训练" tooltip="原始名称：python train.py" />);
  const alias = screen.getByText("模型A训练");
  expect(alias).toHaveAttribute("title", "原始名称：python train.py");
  await userEvent.hover(alias);
  expect(await screen.findByRole("tooltip")).toHaveTextContent("原始名称：python train.py");
  await userEvent.unhover(alias);
  await userEvent.tab();
  expect(alias).toHaveFocus();
  expect(await screen.findByRole("tooltip")).toHaveTextContent("原始名称：python train.py");
});
