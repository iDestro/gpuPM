import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, date, queryClient } from "./api";
export type Row = Record<string, any>;
export type Field = {
  name: string;
  label: string;
  type?:
    | "number"
    | "textarea"
    | "password"
    | "switch"
    | "select"
    | "tags"
    | "date"
    | "datetime";
  required?: boolean;
  options?: { label: string; value: any }[];
  min?: number;
  max?: number;
  help?: string;
  disabled?: boolean;
};
export function ErrorAlert({ error }: { error: unknown }) {
  return error ? (
    <Alert
      showIcon
      type="error"
      message={error instanceof Error ? error.message : String(error)}
      style={{ marginBottom: 16 }}
    />
  ) : null;
}
export function JsonView({ value }: { value: unknown }) {
  return <pre className="json-view">{JSON.stringify(value, null, 2)}</pre>;
}
export function Status({ value }: { value: any }) {
  const colors: Record<string, string> = {
    running: "green",
    active: "green",
    succeeded: "green",
    completed: "green",
    success: "green",
    pending: "blue",
    disabled: "orange",
    expired: "orange",
    failed: "red",
    deleted: "red",
    error: "red",
  };
  return <Tag color={colors[value]}>{value ?? "未知"}</Tag>;
}
export function Source({ data }: { data: any }) {
  return (
    <Space wrap>
      <Tag color={data?.source === "demo" ? "orange" : "blue"}>
        {data?.source === "demo"
          ? "演示数据 · 不修改宿主机"
          : data?.source === "host"
            ? "宿主机数据"
            : "来源待确认"}
      </Tag>
      {data?.stale ? <Tag color="red">数据已过期</Tag> : null}
      <Typography.Text type="secondary">
        采样：{date(data?.collected_at)} · Asia/Shanghai
      </Typography.Text>
    </Space>
  );
}
export function useData(path: string, poll = false) {
  return useQuery({
    queryKey: [path],
    queryFn: () => api(path),
    refetchInterval: poll ? 5000 : false,
    refetchIntervalInBackground: false,
  });
}
export function useSave() {
  return useMutation({
    mutationFn: ({
      path,
      method = "PATCH",
      body,
    }: {
      path: string;
      method?: string;
      body?: unknown;
    }) => api(path, method, body),
    onSuccess: () => queryClient.invalidateQueries(),
    retry: false,
  });
}
export function EditDialog({
  title,
  fields,
  initial = {},
  onSave,
  onClose,
}: {
  title: string;
  fields: Field[];
  initial?: Row;
  onSave: (values: Row) => Promise<unknown>;
  onClose: () => void;
}) {
  const [snapshot] = useState(() => ({ ...initial }));
  const [form] = Form.useForm();
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const close = () => {
    if (dirty)
      Modal.confirm({
        title: "放弃尚未保存的修改？",
        okText: "放弃修改",
        cancelText: "继续编辑",
        onOk: onClose,
      });
    else onClose();
  };
  const finish = async (values: Row) => {
    setSaving(true);
    setError(null);
    try {
      const payload = { ...values };
      for (const f of fields) {
        if (f.type === "datetime")
          payload[f.name] = values[f.name]
            ? new Date(`${values[f.name]}+08:00`).toISOString()
            : null;
        if (f.type === "date" && !values[f.name]) payload[f.name] = null;
      }
      if (snapshot.revision !== undefined) payload.revision = snapshot.revision;
      await onSave(payload);
      setDirty(false);
      onClose();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };
  const defaults = { ...snapshot };
  for (const f of fields)
    if (f.type === "datetime" && defaults[f.name])
      defaults[f.name] = new Date(
        new Date(defaults[f.name]).getTime() + 8 * 3600000,
      )
        .toISOString()
        .slice(0, 16);
  return (
    <Modal
      open
      title={title}
      onCancel={close}
      footer={null}
      maskClosable={!dirty}
      width={650}
      destroyOnHidden
    >
      <ErrorAlert error={error} />
      <Form
        form={form}
        layout="vertical"
        initialValues={defaults}
        onValuesChange={() => setDirty(true)}
        onFinish={finish}
      >
        {fields.map((f) => (
          <Form.Item
            key={f.name}
            name={f.name}
            label={f.label}
            help={f.help}
            valuePropName={f.type === "switch" ? "checked" : "value"}
            rules={
              f.required
                ? [{ required: true, message: `请填写${f.label}` }]
                : []
            }
          >
            {f.type === "number" ? (
              <InputNumber
                min={f.min}
                max={f.max}
                style={{ width: "100%" }}
                disabled={f.disabled}
              />
            ) : f.type === "switch" ? (
              <Switch disabled={f.disabled} />
            ) : f.type === "select" || f.type === "tags" ? (
              <Select
                allowClear
                mode={f.type === "tags" ? "tags" : undefined}
                options={f.options}
                disabled={f.disabled}
              />
            ) : f.type === "textarea" ? (
              <Input.TextArea rows={3} disabled={f.disabled} />
            ) : f.type === "password" ? (
              <Input.Password autoComplete="new-password" />
            ) : (
              <Input
                type={
                  f.type === "datetime"
                    ? "datetime-local"
                    : f.type === "date"
                      ? "date"
                      : "text"
                }
                disabled={f.disabled}
              />
            )}
          </Form.Item>
        ))}
        <Space>
          <Button type="primary" htmlType="submit" loading={saving}>
            保存
          </Button>
          <Button onClick={close}>取消</Button>
        </Space>
      </Form>
    </Modal>
  );
}
export function PreviewDialog({
  title,
  previewPath,
  executePath,
  previewBody = {},
  executeBody = {},
  method = "POST",
  onClose,
  onDone,
  warning,
}: {
  title: string;
  previewPath: string;
  executePath: string;
  previewBody?: Row;
  executeBody?: Row;
  method?: string;
  onClose: () => void;
  onDone?: (result: Row) => void;
  warning?: string;
}) {
  const [nonce] = useState(() => crypto.randomUUID());
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<Row | null>(null);
  const [expired, setExpired] = useState(false);
  const preview = useQuery({
    queryKey: ["preview", previewPath, previewBody, nonce],
    queryFn: () => api(previewPath, "POST", previewBody),
    retry: false,
    staleTime: Infinity,
    refetchOnMount: "always",
  });
  const mutation = useSave();
  useEffect(() => {
    if (!preview.data?.expires_at) return;
    const delay = new Date(preview.data.expires_at).getTime() - Date.now();
    if (delay <= 0) {
      setExpired(true);
      return;
    }
    const timer = setInterval(
      () =>
        setExpired(Date.now() >= new Date(preview.data.expires_at).getTime()),
      1000,
    );
    return () => clearInterval(timer);
  }, [preview.data]);
  const execute = async () => {
    try {
      const data = await mutation.mutateAsync({
        path: executePath,
        method,
        body: {
          ...executeBody,
          token: preview.data.token,
          reason: reason.trim(),
        },
      });
      setResult(data);
      onDone?.(data);
    } catch {
      /* error remains visible */
    }
  };
  return (
    <Modal
      open
      title={title}
      width={760}
      onCancel={onClose}
      footer={
        result ? (
          <Button onClick={onClose}>关闭</Button>
        ) : (
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button
              danger
              type="primary"
              disabled={!preview.data?.token || !reason.trim() || expired}
              loading={mutation.isPending}
              onClick={execute}
            >
              {title === "终止范围预览" ? "确认终止" : "确认执行"}
            </Button>
          </Space>
        )
      }
    >
      <ErrorAlert error={preview.error || mutation.error} />
      {warning ? (
        <Alert
          type="warning"
          showIcon
          message={warning}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {preview.isPending ? <Spin /> : null}
      {expired ? (
        <Alert type="error" message="预览已过期，请关闭后重新预览" />
      ) : null}
      {preview.data ? (
        <>
          <Typography.Paragraph type="secondary">
            范围由服务器核验。预览有效期：{date(preview.data.expires_at)}
          </Typography.Paragraph>
          {preview.data.targets ? (
            <Table<Row>
              size="small"
              pagination={false}
              rowKey={(r: Row) =>
                String(r.pid ?? r.id ?? JSON.stringify(r.identity))
              }
              dataSource={preview.data.targets}
              columns={[
                { title: "PID", dataIndex: "pid" },
                { title: "命令", dataIndex: "command" },
                {
                  title: "身份",
                  dataIndex: "identity",
                  render: (v) => JSON.stringify(v),
                },
              ]}
            />
          ) : (
            <JsonView value={preview.data} />
          )}{" "}
          {preview.data.excluded?.length ? (
            <>
              <Typography.Title level={5}>排除的进程</Typography.Title>
              <JsonView value={preview.data.excluded} />
            </>
          ) : null}
        </>
      ) : null}
      {result ? (
        <>
          <Alert
            showIcon
            type="info"
            message="请求已提交，以下为服务器返回结果"
          />
          <JsonView value={result} />
          {result.id && previewPath.startsWith("/tasks/") ? (
            <Operation id={result.id} />
          ) : null}
        </>
      ) : (
        <Form layout="vertical">
          <Form.Item label="操作原因" required>
            <Input.TextArea
              aria-label={title === "终止范围预览" ? "终止原因" : "操作原因"}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
            />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}
export function TerminationDialog({
  task,
  identity,
  onClose,
}: {
  task: Row;
  identity?: Row;
  onClose: () => void;
}) {
  const [key] = useState(() => crypto.randomUUID());
  return (
    <PreviewDialog
      title="终止范围预览"
      previewPath={`/tasks/${encodeURIComponent(task.id)}/termination-preview`}
      executePath={`/tasks/${encodeURIComponent(task.id)}/terminate`}
      previewBody={identity ? { identity } : {}}
      executeBody={{ idempotency_key: key }}
      onClose={onClose}
      warning="SIGTERM 后等待正常退出，必要时 SIGKILL。只处理预览范围，受保护与身份变化由服务端阻止。僵尸进程需要父进程回收。"
    />
  );
}
export function Operation({ id }: { id: string }) {
  const q = useQuery({
    queryKey: ["operation", id],
    queryFn: () => api(`/operations/${encodeURIComponent(id)}`),
    refetchInterval: (query) =>
      ["pending", "running"].includes(query.state.data?.status) ? 1000 : false,
    refetchIntervalInBackground: false,
    retry: false,
  });
  return (
    <>
      <ErrorAlert error={q.error} />
      {q.data ? (
        <Descriptions title="操作进度" column={1}>
          <Descriptions.Item label="状态">
            <Status value={q.data.status} />
          </Descriptions.Item>
          <Descriptions.Item label="来源">{q.data.source}</Descriptions.Item>
          <Descriptions.Item label="逐项结果">
            <JsonView value={q.data.results} />
          </Descriptions.Item>
        </Descriptions>
      ) : (
        <Spin />
      )}
    </>
  );
}
