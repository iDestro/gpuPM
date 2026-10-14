import { afterEach, expect, test, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient, setSession } from "./api";
import { EditDialog, PreviewDialog, TerminationDialog } from "./components";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  queryClient.clear();
});
test("edit submits changed values and current revision", async () => {
  const save = vi.fn().mockResolvedValue({});
  render(
    <EditDialog
      title="编辑任务"
      fields={[{ name: "priority", label: "任务优先级", type: "number" }]}
      initial={{ revision: 9, priority: 20 }}
      onSave={save}
      onClose={() => {}}
    />,
  );
  const input = screen.getByRole("spinbutton");
  await userEvent.clear(input);
  await userEvent.type(input, "75");
  await userEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({ priority: 75, revision: 9 }),
    ),
  );
});
test("termination requires server preview then a reason; it uses the preview token", async () => {
  setSession({ username: "admin", csrf_token: "token" });
  const fetch = vi
    .fn()
    .mockImplementation(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith("termination-preview")
              ? {
                  token: "preview-token",
                  expires_at: "2099-01-01T00:00:00Z",
                  targets: [{ pid: 222, command: "python train.py" }],
                  excluded: [{ pid: 1, command: "sshd" }],
                }
              : { id: "op1", status: "pending" },
          ),
        ),
    );
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider client={queryClient}>
      <TerminationDialog
        task={{ id: "t1", name: "训练任务", is_human: true }}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
  await screen.findByText("python train.py");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "确认终止" })).toBeDisabled();
  await userEvent.type(screen.getByLabelText("终止原因"), "管理员处理超时");
  await userEvent.click(screen.getByRole("button", { name: "确认终止" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.filter((c) => String(c[0]).endsWith("/terminate")),
    ).toHaveLength(1),
  );
  const payload = JSON.parse(fetch.mock.calls[1][1].body);
  expect(payload).toMatchObject({
    token: "preview-token",
    reason: "管理员处理超时",
  });
  expect(payload.idempotency_key).toBeTruthy();
});
test("polling updates do not overwrite an unsaved form draft", async () => {
  const save = vi.fn();
  const props = {
    title: "编辑任务",
    fields: [{ name: "name", label: "任务名称" }],
    onSave: save,
    onClose: () => {},
  };
  const { rerender } = render(
    <EditDialog {...props} initial={{ name: "old", revision: 1 }} />,
  );
  await userEvent.clear(screen.getByLabelText("任务名称"));
  await userEvent.type(screen.getByLabelText("任务名称"), "draft");
  rerender(
    <EditDialog {...props} initial={{ name: "server changed", revision: 2 }} />,
  );
  expect(screen.getByLabelText("任务名称")).toHaveValue("draft");
  await userEvent.click(screen.getByRole("button", { name: /保\s*存/ }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith({ name: "draft", revision: 1 }),
  );
});
test("server preview error prevents termination and remains visible", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: { code: "protected", message: "任务保护已开启" },
          }),
          { status: 409 },
        ),
      ),
  );
  render(
    <QueryClientProvider client={queryClient}>
      <TerminationDialog task={{ id: "protected", is_human: true, protected: true }} onClose={() => {}} />
    </QueryClientProvider>,
  );
  await screen.findByText("任务保护已开启");
  await userEvent.type(screen.getByLabelText("终止原因"), "test");
  expect(screen.getByRole("button", { name: "确认终止" })).toBeDisabled();
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("account soft deletion submits preview token and revision without inventing an operation job", async () => {
  const fetch = vi
    .fn()
    .mockImplementation(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith("change-preview")
              ? {
                  token: "account-scope",
                  expires_at: "2099-01-01T00:00:00Z",
                  changes: { disabled: true },
                }
              : { id: "alice", status: "deleted", revision: 8 },
          ),
        ),
    );
  vi.stubGlobal("fetch", fetch);
  render(
    <QueryClientProvider client={queryClient}>
      <PreviewDialog
        title="账号软删除"
        previewPath="/system-users/alice/change-preview"
        previewBody={{ action: "delete", revision: 7, changes: {} }}
        executePath="/system-users/alice"
        method="DELETE"
        executeBody={{ revision: 7 }}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
  await screen.findByText(/范围由服务器核验/);
  await userEvent.type(screen.getByLabelText("操作原因"), "离职账号");
  await userEvent.click(screen.getByRole("button", { name: "确认执行" }));
  await screen.findByText("请求已提交，以下为服务器返回结果");
  expect(fetch.mock.calls[1][1]).toMatchObject({ method: "DELETE" });
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
    token: "account-scope",
    revision: 7,
    reason: "离职账号",
  });
  expect(
    fetch.mock.calls.some((c) => String(c[0]).startsWith("/api/operations/")),
  ).toBe(false);
});


test.each([/取\s*消/, "Close"])("clean edit dialog closes through %s without saving", async (name) => {
  const onClose=vi.fn(), onSave=vi.fn();
  render(<EditDialog title="编辑任务" fields={[{name:"notes",label:"备注"}]} initial={{notes:"saved"}} onClose={onClose} onSave={onSave}/>);
  await userEvent.click(screen.getByRole("button",{name}));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(onSave).not.toHaveBeenCalled();
});
test("dirty edit cancellation offers continuing or discarding without an implicit save", async () => {
  const onClose=vi.fn(), onSave=vi.fn();
  render(<EditDialog title="编辑任务" fields={[{name:"notes",label:"备注"}]} initial={{notes:"saved"}} onClose={onClose} onSave={onSave}/>);
  await userEvent.type(screen.getByLabelText("备注")," draft");
  await userEvent.click(screen.getByRole("button",{name:/取\s*消/}));
  await screen.findByRole("button",{name:"继续编辑"});
  await userEvent.click(screen.getByRole("button",{name:"继续编辑"}));
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByLabelText("备注")).toHaveValue("saved draft");
  await userEvent.click(screen.getByRole("button",{name:"Close"}));
  await screen.findByRole("button",{name:"继续编辑"});
  await userEvent.click(screen.getByRole("button",{name:"放弃修改"}));
  await waitFor(()=>expect(onClose).toHaveBeenCalledTimes(1));
  expect(onSave).not.toHaveBeenCalled();
});

function runtimeDialog(initial: number | null = null) {
  const save = vi.fn().mockResolvedValue({});
  render(<EditDialog title="编辑任务" fields={[{name:"max_runtime_seconds",label:"最大运行时间",type:"duration"}]} initial={{max_runtime_seconds:initial,revision:9}} onClose={()=>{}} onSave={save}/>);
  return save;
}
test("runtime input preserves seconds precisely and submits mixed hours minutes seconds", async () => {
  const save=runtimeDialog(3661);
  expect(screen.getByRole("spinbutton",{name:"小时"})).toHaveValue("1");
  expect(screen.getByRole("spinbutton",{name:"分钟"})).toHaveValue("1");
  expect(screen.getByRole("spinbutton",{name:"秒"})).toHaveValue("1");
  const seconds=screen.getByRole("spinbutton",{name:"秒"});
  await userEvent.clear(seconds);
  await userEvent.type(seconds,"30");
  await userEvent.click(screen.getByRole("button",{name:/保\s*存/}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith({max_runtime_seconds:3690,revision:9}));
});
test.each([["30秒",30],["24小时",86400],["不限时",null]])("runtime preset %s submits seconds or null", async (name, seconds) => {
  const save=runtimeDialog(3661);
  await userEvent.click(screen.getByRole("button",{name:String(name)}));
  await userEvent.click(screen.getByRole("button",{name:/保\s*存/}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith({max_runtime_seconds:seconds,revision:9}));
});
test("clearing all runtime parts removes the time limit", async () => {
  const save=runtimeDialog(3661);
  for(const name of ["小时","分钟","秒"]) await userEvent.clear(screen.getByRole("spinbutton",{name}));
  await userEvent.click(screen.getByRole("button",{name:/保\s*存/}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith({max_runtime_seconds:null,revision:9}));
});
test.each([0,315360060])("invalid runtime %s prevents saving", async (initial) => {
  const save=runtimeDialog(initial);
  await userEvent.click(screen.getByRole("button",{name:/保\s*存/}));
  await screen.findByText("运行时间需为1秒至87600小时；不限时请清空");
  expect(save).not.toHaveBeenCalled();
});
