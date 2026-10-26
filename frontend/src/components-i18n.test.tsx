import { afterEach, expect, test } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "./api";
import { ErrorAlert, Status, TermLabel, statusLabel } from "./components";
import { setLocale } from "./i18n";
import { termFor } from "./glossary";

afterEach(() => {
  cleanup();
  act(() => setLocale("zh-CN"));
});

test("known status labels switch language while unknown server values remain raw", () => {
  act(() => setLocale("zh-CN"));
  render(<Status value="running" />);
  expect(screen.getByText("运行中")).toBeInTheDocument();
  act(() => setLocale("en-US"));
  expect(screen.getByText("Running")).toBeInTheDocument();
  expect(statusLabel("保存")).toBe("保存");
  expect(statusLabel("__proto__")).toBe("__proto__");
});

test("unknown server errors retain the complete raw diagnostic", async () => {
  act(() => setLocale("en-US"));
  const error = new ApiError(409, "custom_conflict", "作业 custom-name 在 /mnt/custom 已改变");
  render(<ErrorAlert error={error} />);
  expect(screen.getByText("Request failed (custom_conflict)")).toBeInTheDocument();
  await userEvent.click(screen.getByText("Server diagnostic"));
  expect(screen.getByText(error.message)).toBeVisible();
  expect(error.message).toBe("作业 custom-name 在 /mnt/custom 已改变");
});

test("known errors translate without changing stored diagnostics", async () => {
  act(() => setLocale("en-US"));
  const error = new ApiError(409, "revision_conflict", "任务版本已改变");
  render(<ErrorAlert error={error} />);
  expect(screen.getByText("The account or configuration revision changed. Refresh and preview again.")).toBeInTheDocument();
  await userEvent.click(screen.getByText("Server diagnostic"));
  expect(screen.getByText("任务版本已改变")).toBeVisible();
  expect(error.message).toBe("任务版本已改变");
});

test("Chinese glossary terms are available on focus and click", async () => {
  act(() => setLocale("zh-CN"));
  render(<TermLabel label="任务优先级" />);
  const label = screen.getByText("任务优先级");
  expect(label).toHaveAttribute("tabindex", "0");
  expect(label).toHaveAttribute("title", termFor("任务优先级"));
  await userEvent.click(label);
  expect(await screen.findByRole("tooltip")).toHaveTextContent(termFor("任务优先级")!);
  act(() => setLocale("en-US"));
  expect(document.querySelector(".term-label")).toBeNull();
});

test("HTTP fallback follows later language changes without modifying the error", () => {
  const error=new ApiError(503,"http_error","请求失败 (503)");
  render(<ErrorAlert error={error}/>);
  expect(screen.getByText("请求失败 (503)")).toBeInTheDocument();
  act(()=>setLocale("en-US"));
  expect(screen.getByText("Request failed (503)")).toBeInTheDocument();
  act(()=>setLocale("zh-CN"));
  expect(screen.getByText("请求失败 (503)")).toBeInTheDocument();
  expect(error.message).toBe("请求失败 (503)");
});
