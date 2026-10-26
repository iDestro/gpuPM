import { ChangePreview, errorGuidance, useHostMutations } from "./readiness";
import { type ReactNode, useEffect, useState } from "react";
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
  Tooltip,
} from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError, date, duration, queryClient } from "./api";
import { translate, useI18n } from "./i18n";
import { termFor } from "./glossary";
export type Row = Record<string, any>;
export type Field = {
  name: string;
  label: string;
  type?:
    | "number"
    | "duration"
    | "textarea"
    | "password"
    | "switch"
    | "select"
    | "tags"
    | "multiple"
    | "date"
    | "datetime";
  required?: boolean;
  options?: { label: string; value: any; disabled?: boolean }[];
  min?: number;
  max?: number;
  help?: string;
  disabled?: boolean;
};
export function TermLabel({ label }: { label: string }) {
  const { locale, t } = useI18n();
  const term = locale === "zh-CN" ? termFor(label) : undefined;
  return term ? <Tooltip title={term} trigger={["hover", "focus"]}><span className="term-label" title={term} tabIndex={0} onClick={(event) => event.currentTarget.focus()}>{t(label)}</span></Tooltip> : <>{t(label)}</>;
}
export function ErrorAlert({ error }: { error: unknown }) {
  const { locale, t } = useI18n();
  if (!error) return null;
  const diagnostic = error instanceof Error ? error.message : String(error);
  const translated = error instanceof ApiError && error.code === "http_error" && diagnostic === `请求失败 (${error.status})`
    ? t("请求失败 ({status})", {status:error.status}) : t(diagnostic);
  const invalidMember = error instanceof ApiError && error.code === "invalid_share_member" ? diagnostic.match(/^Invalid shared member: ([a-z][a-z0-9_-]{0,30})$/)?.[1] : undefined;
  const unknown = locale === "en-US" && translated === diagnostic && /\p{Script=Han}/u.test(diagnostic);
  return <Alert showIcon type="error"
    message={invalidMember ? t("成员 {name} 当前不可授权，请在成员列表查看状态或将其移除。",{name:invalidMember}) : error instanceof ApiError && errorGuidance[error.code] ? t(errorGuidance[error.code]) : unknown ? t("请求失败 ({code})", { code: error instanceof ApiError ? error.code : "unknown_error" }) : translated}
    description={unknown || error instanceof ApiError && !!errorGuidance[error.code] ? <details><summary>{t("服务器诊断")}</summary><pre className="json-view">{diagnostic}</pre></details> : undefined}
    style={{ marginBottom: 16 }} />;
}
export function JsonView({ value }: { value: unknown }) {
  return <pre className="json-view">{JSON.stringify(value, null, 2)}</pre>;
}
export function CompactText({ value, tooltip }: { value: unknown; tooltip?: string }) {
  const text = value == null || value === "" ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
  return <Tooltip title={tooltip ?? text} trigger={["hover", "focus"]}><span className="compact-text" title={tooltip ?? text} tabIndex={0}>{text}</span></Tooltip>;
}
const statusLabels: Record<string, string> = {
  access_recheck_required: "权限需重新验证",
  running: "运行中", finalizing: "收尾中", awaiting_cleanup: "待清理", cleaning: "清理中", finished: "已结束", overdue: "已超时", anomaly: "有异常", active: "正常", succeeded: "成功", completed: "已完成",
  success: "成功", pending: "等待中", disabled: "已停用", expired: "已到期",
  failed: "失败", failure: "失败", deleted: "已软删除", error: "错误",
  terminated: "已终止", unavailable: "不可用", available: "可用", partial: "部分完成",
  queued: "排队中", catching_up: "补扫中", demo: "演示模式", unmanaged: "未启用管理",
  applied: "已生效", unconfirmed: "未确认", confirmed: "已确认", identity_conflict: "身份冲突",
  R: "运行中", S: "休眠", D: "等待 I/O", T: "已暂停", Z: "僵尸进程",
  notify: "仅提醒", terminate: "自动终止", host: "宿主机模式",
};
export const statusLabel = (value: any) => Object.prototype.hasOwnProperty.call(statusLabels, value)
  ? translate(statusLabels[value]) : value ?? translate("未知");
export function Status({ value }: { value: any }) {
  useI18n();
  const colors: Record<string, string> = {
    running: "green",
    finalizing: "blue", awaiting_cleanup: "orange", cleaning: "blue",
    active: "green",
    succeeded: "green",
    completed: "green",
    success: "green",
    pending: "blue",
    disabled: "orange",
    expired: "orange",
    failed: "red",
    failure: "red",
    deleted: "red",
    error: "red",
  };
  return <Tag className="status-tag" color={colors[value]} title={value == null ? undefined : String(value)}>{Object.prototype.hasOwnProperty.call(statusLabels, value) ? <TermLabel label={statusLabels[value]} /> : statusLabel(value)}</Tag>;
}
export function Source({ data }: { data: any }) {
  const { t } = useI18n();
  return (
    <Space wrap>
      <Tag color={data?.source === "demo" ? "orange" : "blue"}>
        {data?.source === "demo"
          ? t("演示数据 · 不修改宿主机")
          : data?.source === "host"
            ? t("宿主机数据")
            : t("来源待确认")}
      </Tag>
      {data?.stale ? <Tag color="red">{t("数据已过期")}</Tag> : null}
      <Typography.Text type="secondary">
        {t("采样：")}{date(data?.collected_at)} · Asia/Shanghai
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
    // A preview is a frozen scope; replaying it after a write uses the previous revision.
    onSuccess: () => queryClient.invalidateQueries({predicate: query => query.queryKey[0] !== "preview"}),
    retry: false,
  });
}
type RuntimeValue = { hours?: number | null; minutes?: number | null; seconds?: number | null };
export function runtimeSeconds(value: RuntimeValue = {}) {
  return Object.values(value).every((part) => part == null)
    ? null
    : (value.hours ?? 0) * 3600 + (value.minutes ?? 0) * 60 + (value.seconds ?? 0);
}
export function RuntimeInput({ value = {}, onChange, id, disabled, label, required, min = 1, max = 315360000 }: {
  value?: RuntimeValue; onChange?: (value: RuntimeValue) => void; id?: string; disabled?: boolean; label: string; required?: boolean; min?: number; max?: number;
}) {
  const { t } = useI18n();
  const current = runtimeSeconds(value);
  return <Space role="group" aria-label={t(label)} direction="vertical" style={{ width: "100%" }}>
    <Space wrap>
      {(["hours", "minutes", "seconds"] as const).map((unit, index) => <InputNumber
        key={unit}
        id={index === 0 ? id : `${id}-${unit}`}
        aria-label={t(["小时", "分钟", "秒"][index])}
        addonAfter={t(["时", "分", "s"][index])}
        min={0}
        max={index === 0 ? Math.floor(max / 3600) : 59}
        precision={0}
        value={value[unit] ?? null}
        onChange={(part) => onChange?.({ ...value, [unit]: part })}
        disabled={disabled}
        style={{ width: index === 0 ? 130 : 100 }}
      />)}
    </Space>
    <Space wrap size={6}>
      {([["30秒", 30], ["1分钟", 60], ["30分钟", 1800], ["1小时", 3600], ["4小时", 14400], ["24小时", 86400], ["不限时", null]] as const).filter(([, seconds]) => seconds == null ? !required : seconds >= min && seconds <= max).map(([label, seconds]) => <Button
        key={label}
        size="small"
        type={current === seconds ? "primary" : "default"}
        disabled={disabled}
        onClick={() => onChange?.(seconds == null ? {} : { hours: Math.floor(seconds / 3600), minutes: Math.floor(seconds % 3600 / 60), seconds: seconds % 60 })}
      >{t(label)}</Button>)}
    </Space>
  </Space>;
}
export function EditDialog({
  children,
  title,
  fields,
  initial = {},
  disabledReason,
  onSave,
  onClose,
}: {
  title: string;
  fields: Field[];
  children?: ReactNode;
  initial?: Row;
  disabledReason?: string;
  onSave: (values: Row) => Promise<unknown>;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [snapshot] = useState(() => ({ ...initial }));
  const [form] = Form.useForm();
  const [modal, contextHolder] = Modal.useModal();
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
    if (saving) return;
    if (dirty)
      modal.confirm({
        title: t("放弃尚未保存的修改？"),
        okText: t("放弃修改"),
        cancelText: t("继续编辑"),
        onOk: onClose,
      });
    else onClose();
  };
  const finish = async (values: Row) => {
    if (disabledReason || saving) return;
    setSaving(true);
    setError(null);
    try {
      const payload = { ...values };
      for (const f of fields) {
        if (f.type === "duration") payload[f.name] = runtimeSeconds(values[f.name]);
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
  for (const f of fields) {
    if (f.type === "duration") {
      const seconds = defaults[f.name];
      defaults[f.name] = seconds == null ? {} : {
        hours: Math.floor(seconds / 3600), minutes: Math.floor(seconds % 3600 / 60), seconds: seconds % 60,
      };
    }
    if (f.type === "datetime" && defaults[f.name])
      defaults[f.name] = new Date(
        new Date(defaults[f.name]).getTime() + 8 * 3600000,
      )
        .toISOString()
        .slice(0, 16);
  }
  return (
    <Modal
      open
      title={t(title)}
      onCancel={close}
      footer={null}
      maskClosable={!dirty && !saving}
      closable={!saving}
      keyboard={!saving}
      width={650}
      centered
      styles={{ body: { maxHeight: "calc(100dvh - 160px)", overflowY: "auto" } }}
      destroyOnHidden
    >
      {contextHolder}
      <ErrorAlert error={error} />
      <Form
        form={form}
        disabled={saving}
        layout="vertical"
        initialValues={defaults}
        onValuesChange={() => setDirty(true)}
        onFinish={finish}
      >
        {fields.map((f) => (
          <Form.Item
            key={f.name}
            name={f.name}
            label={<TermLabel label={f.label} />}
            extra={f.help ? t(f.help) : undefined}
            valuePropName={f.type === "switch" ? "checked" : "value"}
            rules={[
              ...(f.required ? [{ required: true, message: t("请填写{label}", { label: t(f.label) }) }] : []),
              ...(f.type === "duration" ? [{ validator: async (_: unknown, value: RuntimeValue = {}) => {
                const seconds = runtimeSeconds(value);
                if (Object.values(value).some((part) => part != null && (!Number.isInteger(part) || part < 0)) ||
                    (value.minutes ?? 0) > 59 || (value.seconds ?? 0) > 59 ||
                    (f.required && seconds == null) ||
                    (seconds != null && (seconds < (f.min ?? 1) || seconds > (f.max ?? 315360000)))) {
                  throw new Error(t(f.required ? "残留等待时间需为1秒至24小时" : "运行时间需为1秒至87600小时；不限时请清空"));
                }
              } }] : []),
            ]}
          >
            {f.type === "duration" ? (
              <RuntimeInput disabled={f.disabled} label={f.label} required={f.required} min={f.min} max={f.max} />
            ) : f.type === "number" ? (
              <InputNumber
                min={f.min}
                max={f.max}
                style={{ width: "100%" }}
                disabled={f.disabled}
              />
            ) : f.type === "switch" ? (
              <Switch disabled={f.disabled} />
            ) : f.type === "select" || f.type === "tags" || f.type === "multiple" ? (
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                mode={f.type === "tags" ? "tags" : f.type === "multiple" ? "multiple" : undefined}
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
        {children}
        <Space>
          <Button type="primary" htmlType="submit" disabled={!!disabledReason} title={disabledReason} loading={saving}>
            {t("保存")}
          </Button>
          <Button disabled={saving} onClick={close}>{t("取消")}</Button>
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
  onEdit,
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
  onEdit?: () => Promise<void>;
  warning?: string;
}) {
  const { t } = useI18n();
  const host = useHostMutations();
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
    refetchOnReconnect: false,
    enabled: result === null,
  });
  const mutation = useSave();
  const [returning, setReturning] = useState(false);
  const [returnError, setReturnError] = useState<unknown>(null);
  const busy = mutation.isPending || returning;
  const returnToEdit = async () => {
    setReturning(true);
    setReturnError(null);
    try { await onEdit?.(); } catch (error) { setReturnError(error); } finally { setReturning(false); }
  };
  useEffect(() => {
    if (result || !preview.data?.expires_at) return;
    const delay = new Date(preview.data.expires_at).getTime() - Date.now();
    setExpired(delay <= 0);
    if (delay <= 0) return;
    const timer = setInterval(
      () =>
        setExpired(Date.now() >= new Date(preview.data.expires_at).getTime()),
      1000,
    );
    return () => clearInterval(timer);
  }, [preview.data, result]);
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
      title={t(title)}
      width={760}
      centered
      styles={{ body: { maxHeight: "calc(100dvh - 240px)", overflowY: "auto" } }}
      onCancel={() => { if (!busy) onClose(); }}
      closable={!busy}
      maskClosable={!busy}
      keyboard={!busy}
      footer={
        result ? (
          <Button onClick={onClose}>{t("关闭")}</Button>
        ) : (
          <Space wrap>
            <Button disabled={busy} onClick={onClose}>{t("取消")}</Button>
            {onEdit ? <Button disabled={busy} loading={returning} onClick={returnToEdit}>{t("返回编辑并核对")}</Button> : null}
            {expired && !mutation.error && !preview.error ? <Button loading={preview.isFetching} disabled={busy} onClick={()=>{mutation.reset();void preview.refetch();}}>{t("重新预览")}</Button> : null}
            <Button
              danger
              type="primary"
              disabled={!host.writable || !preview.data?.token || !reason.trim() || expired || preview.isFetching || !!preview.error || busy || !!mutation.error || preview.data?.adoption?.ready === false}
              loading={mutation.isPending}
              onClick={execute}
            >
              {t(previewPath.endsWith("/termination-preview") ? "确认终止" : "确认执行")}
            </Button>
          </Space>
        )
      }
    >
      {!host.writable ? <Alert showIcon type="warning" message={host.reason}/> : null}
      <ErrorAlert error={result ? null : returnError || preview.error || mutation.error} />
      {mutation.isPending ? <Alert type="info" showIcon message={t("正在执行，请等待服务器返回结果。关闭窗口不会取消操作。")}/> : null}
      {warning ? (
        <Alert
          type="warning"
          showIcon
          message={t(warning)}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {preview.isPending ? <Spin /> : null}
      {!result && expired ? (
        <Alert type="error" message={t("预览已过期，请重新预览后再确认。")} />
      ) : null}
      {preview.data ? (
        <>
          {!result ? <Typography.Paragraph type="secondary">
            {t("范围由服务器核验。预览有效期：")}{date(preview.data.expires_at)}
          </Typography.Paragraph> : null}
          {preview.data.kind === "task" || previewPath.endsWith("/termination-preview") ? (
            <Table<Row>
              size="small"
              pagination={false}
              rowKey={(r: Row) =>
                String(r.pid ?? r.id ?? JSON.stringify(r.identity))
              }
              dataSource={preview.data.targets}
              tableLayout="fixed"
              scroll={{ x: 800 }}
              columns={[
                { title: <TermLabel label="PID" />, dataIndex: "pid", width: 90 },
                { title: <TermLabel label="命令" />, dataIndex: "command", width: 260, render: (value) => <CompactText value={value} /> },
                { title: <TermLabel label="运行时间" />, width: 150, render: (_, r) => r.create_time ? duration(Math.max(0, Math.floor((Date.now() - new Date(r.create_time).getTime()) / 1000))) : "—" },
                {
                  title: <TermLabel label="身份" />,
                  dataIndex: "identity",
                  width: 300,
                  render: (v) => <CompactText value={v} />,
                },
              ]}
            />
          ) : (
            <ChangePreview data={preview.data} />
          )}{" "}
          {preview.data.excluded?.length ? (
            <>
              <Typography.Title level={5}>{t("排除的进程")}</Typography.Title>
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
            message={t("请求已提交，以下为服务器返回结果")}
          />
          <JsonView value={result} />
          {result.id && previewPath.startsWith("/tasks/") ? (
            <Operation id={result.id} />
          ) : null}
        </>
      ) : (
        <Form layout="vertical">
          <Form.Item label={<TermLabel label="操作原因" />} required>
            <Input.TextArea
              aria-label={t(previewPath.endsWith("/termination-preview") ? "终止原因" : "操作原因")}
              value={reason}
              disabled={busy}
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
  residualOnly = false,
  onClose,
}: {
  task: Row;
  identity?: Row;
  residualOnly?: boolean;
  onClose: () => void;
}) {
  const [key] = useState(() => crypto.randomUUID());
  return (
    <PreviewDialog
      title="终止范围预览"
      previewPath={`/tasks/${encodeURIComponent(task.id)}/termination-preview`}
      executePath={`/tasks/${encodeURIComponent(task.id)}/terminate`}
      previewBody={residualOnly ? { residual_only: true } : identity ? { identity } : {}}
      executeBody={{ idempotency_key: key }}
      onClose={onClose}
      warning="SIGTERM 后等待正常退出，必要时 SIGKILL。只处理预览范围，受保护与身份变化由服务端阻止。僵尸进程需要父进程回收。"
    />
  );
}
export function Operation({ id }: { id: string }) {
  const { t } = useI18n();
  const q = useQuery({
    queryKey: ["operation", id],
    queryFn: () => api(`/operations/${encodeURIComponent(id)}`),
    refetchInterval: (query) =>
      ["pending", "queued", "running"].includes(query.state.data?.status) ? 1000 : false,
    refetchIntervalInBackground: false,
    retry: false,
  });
  return (
    <>
      <ErrorAlert error={q.error} />
      {q.data ? (
        <Descriptions title={t("操作进度")} column={1}>
          <Descriptions.Item label={t("状态")}>
            <Status value={q.data.status} />
          </Descriptions.Item>
          <Descriptions.Item label={t("来源")}>{q.data.source}</Descriptions.Item>
          <Descriptions.Item label={t("逐项结果")}>
            <JsonView value={q.data.results} />
          </Descriptions.Item>
        </Descriptions>
      ) : (
        <Spin />
      )}
    </>
  );
}
