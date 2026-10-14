import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Input,
  InputNumber,
  Progress,
  Row as GridRow,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tree,
  Typography,
  Tooltip,
} from "antd";
import { Link, useParams } from "react-router-dom";
import { api, bytes, date, duration, params, queryClient } from "./api";
import {
  CompactText,
  EditDialog,
  ErrorAlert,
  Field,
  JsonView,
  PreviewDialog,
  Row,
  Source,
  Status,
  statusLabel,
  TerminationDialog,
  useData,
  useSave,
} from "./components";
const priority: Field = {
  name: "priority",
  label: "优先级 (0–100)",
  type: "number",
  min: 0,
  max: 100,
  required: true,
};
const notes: Field = { name: "notes", label: "备注", type: "textarea" };
const taskFields: Field[] = [
  { name: "name", label: "任务别名", required: true, help: "仅修改平台显示名称，不改变原始名称或进程命令" },
  priority,
  notes,
  {
    name: "protected",
    label: "保护任务（超时仍提醒，不自动终止）",
    type: "switch",
  },
  {
    name: "max_runtime_seconds",
    label: "最大运行时间",
    type: "duration",
    help: "从任务启动时刻计算；留空或点击“不限时”可取消时限",
  },
  {
    name: "expires_at",
    label: "指定到期时间 · Asia/Shanghai",
    type: "datetime",
  },
  {
    name: "deadline_action",
    label: "到期动作",
    type: "select",
    required: true,
    options: [
      { label: "仅提醒", value: "notify" },
      { label: "自动终止", value: "terminate" },
    ],
  },
  {
    name: "cleanup_orphans",
    label: "自动清理已确认残留 worker",
    type: "switch",
    help: "归属不明的进程不会自动清理",
  },
];
const scopeOptions = [{ label: "人员账号", value: "human" }, { label: "其他账号（只读）", value: "other" }, { label: "全部账号", value: "all" }];
const classification = { width: 145, title: "分类", dataIndex: "is_human", render: (v: boolean) => <Tag>{v ? "人员账号" : "其他账号 · 只读"}</Tag> };
const label = (value: any) => (value == null ? "无数据" : String(value));
const compactDate = (value: string | null | undefined) => (
  <Tooltip title={`${date(value)} · Asia/Shanghai`}>
    <span className="compact-text" tabIndex={0} title={`${date(value)} · Asia/Shanghai`}>{date(value).replace(/^(\d{4})\//, "").replace(/:\d{2}$/, "")}</span>
  </Tooltip>
);
const auditActions: Record<string, string> = {
  "auth.login": "管理员登录", "group.create": "创建业务组", "group.update": "修改业务组", "group.delete": "删除业务组",
  "user.update": "修改用户策略", "settings.update": "修改全局策略", "task.policy": "修改任务策略",
  "task.merge": "合并任务", "task.split": "拆分任务", "task.members": "修改任务成员", "task.terminate": "终止任务",
  "account.management_import": "迁移账号管理记录",
  "account.create": "创建账号", "account.update": "修改账号", "account.disable": "停用账号", "account.enable": "启用账号",
  "account.delete": "软删除账号", "account.restore": "恢复账号", "account.password": "修改账号密码",
  "system_group.create": "创建系统组", "system_group.update": "修改系统组", "system_group.delete": "删除系统组",
  "share.create": "创建共享目录", "share.update": "修改共享授权",
};
export function PageHead({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <Typography.Title level={2}>{title}</Typography.Title>
        <Typography.Text type="secondary">{description}</Typography.Text>
      </div>
      {action}
    </div>
  );
}
function RecordDetail({ row }: { row: Row }) {
  return (
    <Descriptions className="record-detail" column={{ xs: 1, sm: 2, lg: 3 }} size="small">
      {Object.entries(row).map(([k, v]) => (
        <Descriptions.Item key={k} label={k}>
          {typeof v === "object" ? JSON.stringify(v) : label(v)}
        </Descriptions.Item>
      ))}
    </Descriptions>
  );
}
export function Overview() {
  const q = useData("/overview", true);
  const d = q.data;
  return (
    <>
      <PageHead
        title="服务器总览"
        description="GPU 资源、运行任务与异常概况。"
      />
      <ErrorAlert error={q.error} />
      {d ? (
        <>
          <Source data={d} />
          {d.agent_error ? (
            <Alert
              showIcon
              type="error"
              message="采集服务异常"
              description={
                typeof d.agent_error === "string"
                  ? d.agent_error
                  : JSON.stringify(d.agent_error)
              }
              style={{ marginTop: 16 }}
            />
          ) : null}
          <GridRow gutter={[16, 16]} className="stats">
            {[
              ["运行任务", d.task_count],
              ["超时任务", d.overdue_count],
              ["异常告警", d.anomaly_count],
            ].map(([title, value]) => (
              <Col xs={24} md={8} key={title}>
                <Card>
                  <Statistic title={title} value={value ?? "无数据"} />
                </Card>
              </Col>
            ))}
          </GridRow>
          <Typography.Title level={4}>GPU 资源</Typography.Title>
          <GridRow gutter={[16, 16]}>
            {(Array.isArray(d.gpus) ? d.gpus : d.gpus?.items || []).map(
              (gpu: Row) => (
                <Col xs={24} lg={12} key={gpu.uuid}>
                  <Card
                    title={
                      <Space>
                        <Tag color="blue">GPU {gpu.index}</Tag>
                        {gpu.name}
                      </Space>
                    }
                  >
                    <Typography.Paragraph type="secondary">
                      <CompactText value={gpu.uuid} />
                    </Typography.Paragraph>
                    <ErrorAlert error={gpu.error} />
                    <Space className="gpu-values" wrap>
                      <Statistic
                        title="显存使用"
                        value={bytes(gpu.memory_used)}
                      />
                      <Statistic
                        title="总显存"
                        value={bytes(gpu.memory_total)}
                      />
                      <Statistic
                        title="GPU 利用率"
                        value={gpu.utilization ?? "无数据"}
                        suffix={gpu.utilization == null ? "" : "%"}
                      />
                    </Space>
                    {gpu.memory_total != null && gpu.memory_used != null ? (
                      <Progress
                        percent={Math.round(
                          (gpu.memory_used / gpu.memory_total) * 100,
                        )}
                        strokeColor="#176b65"
                      />
                    ) : null}
                  </Card>
                </Col>
              ),
            )}
          </GridRow>
        </>
      ) : (
        <Card loading={q.isPending}>
          {!q.isPending ? <Empty description="未取得总览数据" /> : null}
        </Card>
      )}
    </>
  );
}
export function Tasks() {
  const [filter, setFilter] = useState<Row>({
    page: 1,
    page_size: 20,
    sort: "priority",
    scope: "human",
    status: "running",
  });
  const [selected, setSelected] = useState<React.Key[]>([]);
  const [merging, setMerging] = useState(false);
  const [termination, setTermination] = useState<Row | null>(null);
  const q = useData(`/tasks${params(filter)}`, true);
  const groups = useData("/groups");
  const users = useData(`/users${params({ scope: filter.scope })}`);
  const gpus = useData("/gpus");
  const save = useSave();
  const data = q.data;
  return (
    <>
      <PageHead
        title="GPU 任务"
        description="运行中的人员任务，按业务组 → 用户 → 任务优先级排序。其他任务只读，保护任务禁止终止。"
        action={
          <Button
            disabled={selected.length < 2}
            onClick={() => setMerging(true)}
          >
            合并所选任务 ({selected.length})
          </Button>
        }
      />
      <Card>
        <Space wrap className="filters">
          <Select aria-label="任务范围" value={filter.scope} options={scopeOptions} onChange={(scope) => { setFilter({ ...filter, scope, uid: undefined, page: 1 }); setSelected([]); }} />
          <Select
            aria-label="GPU 筛选"
            placeholder="全部 GPU"
            allowClear
            options={gpus.data?.items?.map((g: Row) => ({
              label: `GPU ${g.index} · ${g.name}`,
              value: g.uuid,
            }))}
            onChange={(v) => setFilter({ ...filter, gpu: v, page: 1 })}
          />
          <Select
            aria-label="业务组筛选"
            placeholder="全部业务组"
            allowClear
            options={groups.data?.map((g: Row) => ({
              label: g.name,
              value: g.id,
            }))}
            onChange={(v) => setFilter({ ...filter, group_id: v, page: 1 })}
          />
          <Select
            aria-label="用户筛选"
            placeholder="全部用户"
            allowClear
            options={users.data?.map((u: Row) => ({
              label: u.username,
              value: u.uid,
            }))}
            onChange={(v) => setFilter({ ...filter, uid: v, page: 1 })}
          />
          <Select
            aria-label="状态筛选"
            value={filter.status}
            placeholder="全部状态"
            allowClear
            options={[
              { label: "运行中", value: "running" },
              { label: "已超时", value: "overdue" },
              { label: "有异常", value: "anomaly" },
              { label: "已结束", value: "finished" },
            ]}
            onChange={(v) => setFilter({ ...filter, status: v, page: 1 })}
          />
          <Select
            aria-label="排序"
            value={filter.sort}
            options={[
              { label: "优先级", value: "priority" },
              { label: "运行时间", value: "runtime" },
              { label: "显存占用", value: "memory" },
            ]}
            onChange={(v) => setFilter({ ...filter, sort: v })}
          />
        </Space>
        <ErrorAlert error={q.error || save.error} />
        {data ? <Source data={data} /> : null}
        <Table<Row>
          size="small"
          tableLayout="fixed"
          loading={q.isPending}
          rowKey="id"
          dataSource={data?.items || []}
          rowSelection={{
            selectedRowKeys: selected,
            preserveSelectedRowKeys: false,
            onChange: setSelected,
            getCheckboxProps: (r) => ({ disabled: !r.is_human || r.protected }),
          }}
          scroll={{ x: 1120 }}
          pagination={{
            current: filter.page,
            pageSize: filter.page_size,
            total: data?.total,
            showSizeChanger: true,
            onChange: (page, page_size) => {
              setFilter({ ...filter, page, page_size });
              setSelected([]);
            },
          }}
          columns={[
            {
              title: "任务",
              width: 210,
              dataIndex: "name",
              render: (v, r) => <Link to={`/tasks/${r.id}`}><CompactText value={v || r.id} tooltip={`原始名称：${r.original_name || "未知（旧记录未保留）"}`} /></Link>,
            },
            { title: "用户", dataIndex: "username", width: 120, render: (v, r) => <div className="table-identity"><CompactText value={v} />{!r.is_human ? <Tag>只读</Tag> : null}</div> },
            {
              title: "优先级",
              width: 120,
              dataIndex: "priority_tuple",
              render: (v) => <Tag>{v?.join(" / ") || "—"}</Tag>,
            },
            {
              title: "运行时间",
              width: 110,
              dataIndex: "runtime_seconds",
              render: duration,
            },
            {
              title: "剩余时间",
              width: 110,
              dataIndex: "remaining_seconds",
              render: (v, r) => (
                <span className={r.overdue ? "danger" : ""}>{duration(v)}</span>
              ),
            },
            { title: "显存", dataIndex: "memory_used", width: 100, render: bytes },
            {
              title: "状态",
              width: 150,
              dataIndex: "status",
              render: (v, r) => (
                <Space wrap>
                  <Status value={v} />
                  {r.protected ? <Tag>保护</Tag> : null}
                  {r.overdue ? <Tag color="red">超时</Tag> : null}
                </Space>
              ),
            },
            {
              title: "操作",
              width: 100,
              render: (_, r) => <Button danger size="small" disabled={!r.is_human || r.protected} onClick={() => setTermination(r)}>终止任务</Button>,
            },
            {
              title: "异常",
              width: 60,
              dataIndex: "anomalies",
              render: (v) =>
                v?.length ? <Tag color="orange">{v.length} 项</Tag> : "—",
            },
          ]}
        />
      </Card>
      {termination ? <TerminationDialog task={termination} onClose={() => setTermination(null)} /> : null}
      {merging ? (
        <PreviewMerge
          selected={selected}
          tasks={data?.items || []}
          onClose={() => setMerging(false)}
          onSave={async () => {
            const revisions = Object.fromEntries(
              (data?.items || [])
                .filter((t: Row) => selected.includes(t.id))
                .map((t: Row) => [t.id, t.revision]),
            );
            await save.mutateAsync({
              path: "/tasks/merge",
              method: "POST",
              body: { task_ids: selected, revisions },
            });
            setMerging(false);
            setSelected([]);
          }}
        />
      ) : null}
    </>
  );
}
function PreviewMerge({
  selected,
  tasks,
  onSave,
  onClose,
}: {
  selected: React.Key[];
  tasks: Row[];
  onSave: () => Promise<void>;
  onClose: () => void;
}) {
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  return (
    <Card className="inline-dialog" title="确认合并任务">
      <Alert
        type="warning"
        message="只合并同一用户的相关任务；服务器会重新核验进程归属和版本。"
      />
      <ErrorAlert error={error} />
      <JsonView
        value={tasks
          .filter((t) => selected.includes(t.id))
          .map((t) => ({
            id: t.id,
            name: t.name,
            username: t.username,
            revision: t.revision,
          }))}
      />
      <Space>
        <Button
          type="primary"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onSave();
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          确认合并
        </Button>
        <Button onClick={onClose}>取消</Button>
      </Space>
    </Card>
  );
}
export function TaskDetail() {
  const { id } = useParams();
  const q = useData(`/tasks/${encodeURIComponent(id!)}`, true);
  const gpuDevices = useData("/gpus");
  const gpuText = (p: Row) => Object.entries(p.gpu_memory || {}).length ? Object.entries(p.gpu_memory).map(([uuid, value]) => { const device = gpuDevices.data?.items?.find((g: Row) => g.uuid === uuid); return `GPU ${device?.index ?? "?"} (${uuid}) · ${bytes(value as number | null)}`; }).join("；") : "非 GPU 辅助进程";
  const [editing, setEditing] = useState(false);
  const [termination, setTermination] = useState<Row | null>(null);
  const [membership, setMembership] = useState<"split" | "exclude" | null>(
    null,
  );
  const [chosen, setChosen] = useState<React.Key[]>([]);
  const save = useSave();
  const d = q.data;
  const nodes = d ? [...(d.context || []), ...(d.members || [])] : [];
  const unique = [
    ...new Map(nodes.map((p: Row) => [JSON.stringify(p.identity), p])).values(),
  ];
  const build = (p: Row, visited: Set<number>): any => ({
    key: JSON.stringify(p.identity),
    title: (
      <Space>
        <Tag>PID {p.pid}</Tag>
        <Status value={p.status} />
        {p.uninterruptible_seconds != null ? <Tag color="orange">D 状态持续 {duration(p.uninterruptible_seconds)}</Tag> : null}
        <span>{p.command}</span>
        <Typography.Text type="secondary">{gpuText(p)}</Typography.Text>
      </Space>
    ),
    children: visited.has(p.pid)
      ? []
      : unique
          .filter((c: Row) => c.ppid === p.pid && c.pid !== p.pid)
          .map((c) => build(c, new Set([...visited, p.pid]))),
  });
  const roots = unique.filter(
    (p) => !unique.some((other) => other.pid === p.ppid) || p.ppid === p.pid,
  );
  return (
    <>
      <PageHead
        title={d?.name || "任务详情"}
        description="身份以启动标识、PID 与启动时钟核验。父级 shell / SSH 只作为上下文展示。"
        action={
          <Space>
            <Link to="/tasks">返回列表</Link>
            <Button onClick={() => setEditing(true)} disabled={!d || !d.is_human}>
              编辑策略
            </Button>
            <Button
              danger
              disabled={!d || !d.is_human || d.protected}
              onClick={() => setTermination({})}
            >
              终止整个任务
            </Button>
          </Space>
        }
      />
      <ErrorAlert error={q.error || save.error} />
      {d ? (
        <>
          <Card>
            <RecordDetail
              row={{
                任务别名: d.name,
                原始名称: d.original_name || "未知（旧记录未保留）",
                用户名: d.username,
                分类: d.is_human ? "人员账号" : "其他账号 · 只读",
                业务组: d.group_id,
                三级优先级: d.priority_tuple,
                保护状态: d.protected ? "已保护" : "未保护",
                运行时间: duration(d.runtime_seconds),
                剩余时间: duration(d.remaining_seconds),
                到期时间: date(d.deadline_at),
                到期策略: d.deadline_action,
                策略执行状态: d.policy_status,
                版本: d.revision,
                备注: d.notes,
              }}
            />
            {d.overdue ? (
              <Alert
                type="warning"
                showIcon
                message="任务已超时；高优先级不会自动豁免期限，保护任务只提醒。"
              />
            ) : null}
            {d.anomalies?.length ? <JsonView value={d.anomalies} /> : null}
          </Card>
          <Card title="进程关系与范围" className="section-card">
            <Tree
              treeData={roots.map((p) => build(p, new Set()))}
              defaultExpandAll
            />
            <Table<Row>
              size="small"
              tableLayout="fixed"
              rowKey={(p: Row) => JSON.stringify(p.identity)}
              dataSource={d.members || []}
              rowSelection={{ selectedRowKeys: chosen, onChange: setChosen, getCheckboxProps: () => ({ disabled: !d.is_human || d.protected }) }}
              pagination={false}
              scroll={{ x: 1500 }}
              columns={[
                {
                  title: "PID / PPID",
                  width: 140,
                  render: (_, p) => `${p.pid} / ${p.ppid}`,
                },
                {
                  title: "状态",
                  width: 190,
                  dataIndex: "status",
                  render: (v) => <Status value={v} />,
                },
                { title: "GPU / 显存", width: 190, render: (_, p) => <CompactText value={gpuText(p)} /> },
                { title: "命令", dataIndex: "command", width: 280, render: (v) => <CompactText value={v} /> },
                { title: "启动时间", dataIndex: "create_time", width: 140, render: compactDate },
                {
                  title: "关联依据",
                  width: 200,
                  dataIndex: "evidence",
                  render: (v) => <CompactText value={v} />,
                },
                {
                  title: "操作",
                  width: 130,
                  render: (_, p) => (
                    <Button
                      danger
                      size="small"
                      disabled={!d.is_human || d.protected || p.status === "Z"}
                      onClick={() => setTermination(p.identity)}
                    >
                      终止进程
                    </Button>
                  ),
                },
              ]}
            />
            <Space>
              <Button
                disabled={!d.is_human || d.protected || !chosen.length}
                onClick={() => setMembership("split")}
              >
                拆分所选进程
              </Button>
              <Button
                disabled={!d.is_human || d.protected || !chosen.length}
                onClick={() => setMembership("exclude")}
              >
                排除所选归属
              </Button>
            </Space>
          </Card>
        </>
      ) : (
        <Card loading={q.isPending} />
      )}{" "}
      {editing && d ? (
        <EditDialog
          title="编辑任务"
          fields={taskFields}
          initial={d}
          onClose={() => setEditing(false)}
          onSave={(v) => save.mutateAsync({ path: `/tasks/${id}`, body: v })}
        />
      ) : null}
      {termination && d ? (
        <TerminationDialog
          task={d}
          identity={Object.keys(termination).length ? termination : undefined}
          onClose={() => setTermination(null)}
        />
      ) : null}
      {membership && d ? (
        <EditDialog
          title={
            membership === "split" ? "确认拆分所选进程" : "确认排除进程归属"
          }
          initial={{ revision: d.revision }}
          fields={[]}
          onClose={() => setMembership(null)}
          onSave={(v) =>
            save.mutateAsync({
              path:
                membership === "split"
                  ? `/tasks/${id}/split`
                  : `/tasks/${id}/members`,
              method: membership === "split" ? "POST" : "PATCH",
              body: {
                ...v,
                [membership === "split" ? "identities" : "excluded_identities"]:
                  (d.members || [])
                    .filter((p: Row) =>
                      chosen.includes(JSON.stringify(p.identity)),
                    )
                    .map((p: Row) => p.identity),
              },
            })
          }
        />
      ) : null}
    </>
  );
}
export function BusinessGroups() {
  const q = useData("/groups");
  const save = useSave();
  const [edit, setEdit] = useState<Row | null>(null);
  const [deleting, setDeleting] = useState<Row | null>(null);
  return (
    <>
      <PageHead
        title="业务优先级组"
        description="仅决定 GPU 管理优先级，与 Linux 文件权限组独立。删除时需将用户迁移到另一业务组。"
        action={
          <Button type="primary" onClick={() => setEdit({ priority: 50 })}>
            新建业务组
          </Button>
        }
      />
      <ErrorAlert error={q.error || save.error} />
      <Card>
        <Table<Row>
          scroll={{ x: 1100 }}
          size="small"
          tableLayout="fixed"
          loading={q.isPending}
          rowKey="id"
          dataSource={q.data || []}
          columns={[
            { title: "组名", dataIndex: "name", width: 150, render: (v) => <CompactText value={v} /> },
            { title: "优先级", dataIndex: "priority", width: 140 },
            { title: "备注", dataIndex: "notes", width: 240, render: (v) => <CompactText value={v} /> },
            {
              title: "默认组",
              width: 140,
              dataIndex: "is_default",
              render: (v) => (v ? "是" : "否"),
            },
            {
              title: "操作",
              width: 190,
              render: (_, r) => (
                <Space>
                  <Button size="small" onClick={() => setEdit(r)}>
                    编辑
                  </Button>
                  <Button
                    size="small"
                    danger
                    disabled={r.is_default}
                    onClick={() => setDeleting(r)}
                  >
                    删除
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      {edit ? (
        <EditDialog
          title={edit.id ? "编辑业务组" : "新建业务组"}
          fields={[
            { name: "name", label: "组名", required: true },
            priority,
            notes,
          ]}
          initial={edit}
          onClose={() => setEdit(null)}
          onSave={(v) =>
            save.mutateAsync({
              path: edit.id ? `/groups/${edit.id}` : "/groups",
              method: edit.id ? "PATCH" : "POST",
              body: v,
            })
          }
        />
      ) : null}
      {deleting ? (
        <EditDialog
          title={`删除 ${deleting.name} 并迁移成员`}
          fields={[
            {
              name: "move_to",
              label: "迁入业务组",
              type: "select",
              required: true,
              options: (q.data || [])
                .filter((g: Row) => g.id !== deleting.id)
                .map((g: Row) => ({ label: g.name, value: g.id })),
            },
          ]}
          onClose={() => setDeleting(null)}
          onSave={(v) =>
            save.mutateAsync({
              path: `/groups/${deleting.id}`,
              method: "DELETE",
              body: v,
            })
          }
        />
      ) : null}
    </>
  );
}
export function BusinessUsers() {
  const q = useData("/users");
  const groups = useData("/groups");
  const save = useSave();
  const [edit, setEdit] = useState<Row | null>(null);
  return (
    <>
      <PageHead
        title="用户业务策略"
        description="默认展示人员账号；其他账号只读。每个用户属于一个业务组，修改后现有任务立即采用新的三级优先级。"
      />
      <ErrorAlert error={q.error || save.error} />
      <Card>
        <Table<Row>
          scroll={{ x: 1100 }}
          size="small"
          tableLayout="fixed"
          rowKey="uid"
          loading={q.isPending}
          dataSource={q.data || []}
          columns={[
            { title: "用户", dataIndex: "username", width: 150, render: (v) => <CompactText value={v} /> },
            { title: "UID", dataIndex: "uid", width: 140 },
            classification,
            {
              title: "业务组",
              width: 140,
              dataIndex: "group_id",
              render: (v) =>
                <CompactText value={groups.data?.find((g: Row) => g.id === v)?.name || v} />,
            },
            { title: "用户优先级", dataIndex: "priority", width: 140 },
            { title: "备注", dataIndex: "notes", width: 240, render: (v) => <CompactText value={v} /> },
            {
              title: "操作",
              width: 130,
              render: (_, r) => (
                <Button size="small" disabled={!r.is_human} onClick={() => setEdit(r)}>
                  编辑策略
                </Button>
              ),
            },
          ]}
        />
      </Card>
      {edit ? (
        <EditDialog
          title={`编辑 ${edit.username} 的业务策略`}
          initial={edit}
          fields={[
            {
              name: "group_id",
              label: "业务组",
              type: "select",
              required: true,
              options: groups.data?.map((g: Row) => ({
                label: g.name,
                value: g.id,
              })),
            },
            priority,
            notes,
          ]}
          onClose={() => setEdit(null)}
          onSave={(v) =>
            save.mutateAsync({ path: `/users/${edit.uid}`, body: v })
          }
        />
      ) : null}
    </>
  );
}
const accountFields: Field[] = [
  notes,
  {
    name: "shell",
    label: "登录 Shell",
    type: "select",
    options: [
      { label: "/bin/bash", value: "/bin/bash" },
      { label: "/usr/sbin/nologin", value: "/usr/sbin/nologin" },
    ],
  },
  {
    name: "public_keys",
    label: "SSH 公钥（一行一个，输入后回车添加）",
    type: "tags",
  },
  {
    name: "groups",
    label: "普通附属系统组",
    type: "tags",
    help: "human 是人员分类附属组；新账号保留私有主组。敏感组授权由服务器拒绝，组关系变更不撤销已有会话权限。",
  },
  { name: "expires_on", label: "账号到期日期 · Asia/Shanghai", type: "date" },
  {
    name: "require_password_change",
    label: "首次登录要求修改密码",
    type: "switch",
    help: "改密前 SSH/SFTP 可能受 PAM 限制；宿主机验证状态见登录策略。",
  },
];
export function Accounts() {
  const [state, setState] = useState("active");
  const [scope, setScope] = useState("human");
  const q = useData(`/system-users${params({ state, scope })}`);
  const systemGroups = useData("/system-groups");
  const groups = useData("/groups");
  const [edit, setEdit] = useState<Row | null>(null);
  const [view, setView] = useState<Row | null>(null);
  const [action, setAction] = useState<{ row: Row; action: string } | null>(
    null,
  );
  const [pendingEdit, setPendingEdit] = useState<Row | null>(null);
  const save = useSave();
  const baseFields = [
    ...accountFields,
    ...(edit?.id ? [{name:"primary_group",label:"普通主系统组",type:"select" as const,
      options:systemGroups.data?.filter((g:Row)=>!g.protected).map((g:Row)=>({label:g.name,value:g.name})),
      help:"按 Linux 原生规则修改；主目录内旧组文件可能同步改变组归属，其他路径保留原归属。"}] : []),
    {
      name: "group_id",
      label: "业务组",
      type: "select" as const,
      options: groups.data?.map((g: Row) => ({ label: g.name, value: g.id })),
    },
    priority,
  ];
  return (
    <>
      <PageHead
        title="Linux 本地账号"
        description="默认展示人员账号；其他与保护账号只读。账号软删除保留全部文件与进程，已有账号需先启用管理，平台新建账号自动管理。"
        action={
          <Button
            type="primary"
            onClick={() =>
              setEdit({
                priority: 50,
                require_password_change: true,
                public_keys: [],
                groups: ["human"],
              })
            }
          >
            创建账号
          </Button>
        }
      />
      <Card>
        <Space wrap className="filters">
          <Select aria-label="账号范围" value={scope} options={scopeOptions} onChange={setScope} />
          <Select
            aria-label="账号状态"
            value={state}
            onChange={setState}
            options={[
              { label: "正常账号", value: "active" },
              { label: "已停用", value: "disabled" },
              { label: "已到期", value: "expired" },
              { label: "已软删除", value: "deleted" },
              { label: "全部账号", value: "all" },
            ]}
          />
          <Tag>日期与采样时间：Asia/Shanghai</Tag>
        </Space>
        <ErrorAlert error={q.error || save.error} />
        <Table<Row>
          size="small"
          tableLayout="fixed"
          loading={q.isPending}
          rowKey="id"
          dataSource={q.data || []}
          scroll={{ x: 1100 }}
          columns={[
            {
              title: "账号",
              width: 180,
              dataIndex: "username",
              render: (v, r) => (
                <div>
                  <Button type="link" className="account-link" onClick={() => setView(r)}><CompactText value={v} /></Button>
                  <small className="account-id">UID {r.uid} · GID {r.gid}</small>
                </div>
              ),
            },
            classification,
            {
              title: "状态",
              width: 190,
              dataIndex: "status",
              render: (v, r) => (
                <Space wrap>
                  <Status value={v} />
                  {r.protected ? <Tag>保护</Tag> : null}
                  {!r.managed ? <Tag>未启用管理</Tag> : null}
                  {r.disabled && v !== "disabled" ? <Tag color="orange">停用限制</Tag> : null}
                  {r.deleted_at && v !== "deleted" ? <Tag color="red">软删除限制</Tag> : null}
                </Space>
              ),
            },
            { title: "有效期", width: 120, render: (_, r) => <span title={r.expires_effective_at ? `${date(r.expires_effective_at)} · Asia/Shanghai` : "生效时间以宿主机核验为准"}>{r.expires_effective_at?.slice(0, 10) || r.expires_on || "不限期"}</span> },
            {
              title: "目录",
              width: 160,
              render: (_, r) => (
                <CompactText value={[r.home, r.data_dir].filter(Boolean).join(" · ")} />
              ),
            },
            {
              title: "操作",
              width: 270,
              fixed: "right",
              render: (_, r) => (
                <Space>
                  <Button
                    size="small"
                    disabled={!r.is_human || r.protected || !r.managed || !!r.deleted_at || r.recovery_required}
                    onClick={() => setEdit(r)}
                  >
                    编辑
                  </Button>
                  {r.is_human && !r.managed && !r.protected ? (
                    <Button
                      size="small"
                      onClick={() => setAction({ row: r, action: "update" })}
                    >
                      启用管理
                    </Button>
                  ) : null}
                  <Button
                    size="small"
                    disabled={!r.is_human || r.protected || !r.managed || !!r.deleted_at || r.recovery_required}
                    onClick={() =>
                      setAction({
                        row: r,
                        action: r.disabled ? "enable" : "disable",
                      })
                    }
                  >
                    {r.disabled ? "启用" : "停用"}
                  </Button>
                  <Button
                    size="small"
                    danger
                    disabled={!r.is_human || r.protected || !r.managed || r.recovery_required}
                    onClick={() =>
                      setAction({
                        row: r,
                        action: r.deleted_at ? "restore" : "delete",
                      })
                    }
                  >
                    {r.deleted_at ? "恢复" : "软删除"}
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      {edit ? (
        <EditDialog
          title={edit.id ? `编辑 ${edit.username}` : "创建 Linux 账号"}
          initial={edit}
          fields={
            edit.id
              ? [{name: "username", label: "用户名", required: true, help: "仅允许空闲账号改名：没有运行进程、登录会话或定时任务；提交前由服务器核验。"}, ...baseFields]
              : [
                  { name: "username", label: "用户名", required: true },
                  { name: "password", label: "初始密码", type: "password" },
                  ...baseFields.filter((f) => f.name !== "shell"),
                ]
          }
          onClose={() => setEdit(null)}
          onSave={async (v) => {
            if (edit.id) {
              setPendingEdit(v);
              setAction({ row: edit, action: "update" });
            } else
              await save.mutateAsync({
                path: "/system-users",
                method: "POST",
                body: v,
              });
          }}
        />
      ) : null}
      {action ? (
        <PreviewDialog
          title={`账号操作预览 · ${{ disable: "停用", enable: "启用", delete: "软删除", restore: "恢复", update: action.row.managed ? "修改" : "启用管理" }[action.action]}`}
          previewPath={`/system-users/${action.row.id}/change-preview`}
          previewBody={{
            action: action.action,
            revision: action.row.revision,
            changes:
              action.action === "update"
                ? pendingEdit || { managed: true }
                : {},
          }}
          executePath={`/system-users/${action.row.id}${["disable", "enable", "restore"].includes(action.action) ? `/${action.action}` : ""}`}
          method={
            action.action === "delete"
              ? "DELETE"
              : action.action === "update"
                ? "PATCH"
                : "POST"
          }
          executeBody={{
            revision: action.row.revision,
            ...(action.action === "update"
              ? pendingEdit || { managed: true }
              : {}),
          }}
          onClose={() => {
            setAction(null);
            setPendingEdit(null);
          }}
          warning="只更改后续登录和账号配置，不结束已有进程、会话、定时任务或用户服务。软删除保留目录与配额；恢复/启用不会绕过其他登录限制。"
        />
      ) : null}
      {view ? (
        <AccountDetail account={view} onClose={() => setView(null)} />
      ) : null}
    </>
  );
}
export function AccountDetail({
  account: initialAccount,
  onClose,
}: {
  account: Row;
  onClose: () => void;
}) {
  const detail = useData(`/system-users/${initialAccount.id}`);
  const account = detail.data || initialAccount;
  const immutable = detail.isPending || !account.is_human || !account.managed || account.protected || !!account.deleted_at || account.recovery_required;
  const [quotaChange, setQuotaChange] = useState<Row | null>(null);
  const [policyChange, setPolicyChange] = useState<{kind: string, values: Row} | null>(null);
  const [quotaFilesystem, setQuotaFilesystem] = useState<string>();
  const activity = useData(`/system-users/${account.id}/activity`);
  const quotas = useData(`/system-users/${account.id}/quotas`);
  const storage = useData("/storage", true);
  const [editing, setEditing] = useState<
    "password" | "expiry" | "password-policy" | "quotas" | null
  >(null);
  const save = useSave();
  const filesystems = storage.data?.filesystems || [];
  const quotaTarget = quotaFilesystem || filesystems.find((f: Row) => f.quota_supported && f.quota_enabled)?.id;
  const existingQuota = quotas.data?.find((q: Row) => q.filesystem_id === quotaTarget) || {};
  const quotaReadFailed = !!quotas.error || !!existingQuota.error || (Object.keys(existingQuota).length > 0 && ["soft_bytes", "hard_bytes", "soft_inodes", "hard_inodes"].some(k => existingQuota[k] == null));
  const quotaInitial = Object.fromEntries(["filesystem_id", "soft_bytes", "hard_bytes", "soft_inodes", "hard_inodes", "grace_seconds"].map(k => [k, k === "filesystem_id" ? quotaTarget : existingQuota[k] ?? (k === "grace_seconds" ? undefined : 0)]));
  const quotaFields: Field[] = [
    {
      name: "filesystem_id",
      label: "文件系统",
      disabled: true,
      type: "select",
      required: true,
      options: filesystems
        .filter((f: Row) => f.quota_supported && f.quota_enabled)
        .map((f: Row) => ({ label: f.path, value: f.id })),
    },
    ...[
      "soft_bytes",
      "hard_bytes",
      "soft_inodes",
      "hard_inodes",
      "grace_seconds",
    ].map((name) => ({
      name,
      label: (
        {
          soft_bytes: "空间软限额 (bytes)",
          hard_bytes: "空间硬限额 (bytes)",
          soft_inodes: "inode 软限额",
          hard_inodes: "inode 硬限额",
          grace_seconds: "当前超限宽限期（秒）",
        } as Row
      )[name],
      type: "number" as const,
      min: 0,
      help: name === "grace_seconds" ? "留空保留已有宽限期；填写仅更新当前已超限的期限；未超限时，未来首次超限使用文件系统默认宽限期。" : undefined,
    })),
  ];
  return (
    <Card
      className="inline-dialog"
      title={`账号详情 · ${account.username}`}
      extra={<Button onClick={onClose}>关闭详情</Button>}
    >
      <ErrorAlert error={detail.error} />
      <RecordDetail row={account} />
      {account.recovery_required ? <Alert type="error" showIcon message="账号变更尚未完成，请由服务器管理员核对目录和登录状态后恢复管理。" /> : null}
      {account.status !== "active" && ((activity.data?.processes?.length || 0) + (activity.data?.sessions?.length || 0) + (activity.data?.scheduled?.length || 0) > 0) ? <Alert type="warning" showIcon message="账号已限制新登录，但仍有活动；现有进程、会话和定时任务不会自动结束。" /> : null}
      <Space wrap className="filters">
        <Select aria-label="配额目标文件系统" value={quotaTarget} onChange={setQuotaFilesystem} options={filesystems.filter((f: Row) => f.quota_supported && f.quota_enabled).map((f: Row) => ({label:f.path,value:f.id}))} placeholder="配额文件系统" style={{minWidth:160}} />
        <Button
          disabled={immutable}
          onClick={() => setEditing("password")}
        >
          重置密码
        </Button>
        <Button
          disabled={immutable}
          onClick={() => setEditing("expiry")}
        >
          有效期
        </Button>
        <Button
          disabled={immutable}
          onClick={() => setEditing("password-policy")}
        >
          密码策略
        </Button>
        <Button
          disabled={
            immutable ||
            quotas.isPending ||
            quotaReadFailed ||
            !quotaTarget ||
            !filesystems.some((f: Row) => f.quota_supported && f.quota_enabled)
          }
          onClick={() => setEditing("quotas")}
        >
          配置配额
        </Button>
        <Link
          to={`/login-events?username=${encodeURIComponent(account.username)}`}
        >
          登录历史
        </Link>
      </Space>
      {quotaReadFailed ? <Alert type="error" showIcon message={existingQuota.error || "配额当前限额读取失败，禁止以默认值覆盖。"} /> : null}
      <Alert
        showIcon
        type="info"
        message="配额按 UID / 文件系统计量，与个人目录扫描用量不同。降低限额可能阻止新写入，不会清理文件。配额未支持或未启用时不能提交。"
      />
      <Tabs
        items={[
          {
            key: "activity",
            label: "活动与扫描覆盖",
            children: (
              <>
                <ErrorAlert error={activity.error} />
                <JsonView value={activity.data} />
              </>
            ),
          },
          {
            key: "quotas",
            label: "配额与生效状态",
            children: (
              <>
                <ErrorAlert error={quotas.error} />
                <JsonView value={quotas.data} />
                <JsonView value={filesystems} />
              </>
            ),
          },
        ]}
      />
      {editing ? (
        <EditDialog
          title={
            editing === "quotas"
              ? "配置配额（提交前核对写入影响）"
              : editing === "password"
                ? "重置账号密码"
                : editing === "expiry"
                  ? "账号有效期"
                  : "密码策略"
          }
          fields={
            editing === "quotas"
              ? quotaFields
              : editing === "password"
                ? [
                    {
                      name: "password",
                      label: "新密码",
                      type: "password",
                      required: true,
                    },
                    {
                      name: "require_password_change",
                      label: "首次登录改密",
                      type: "switch",
                    },
                  ]
                : editing === "expiry"
                  ? [
                      {
                        name: "expires_on",
                        label: "到期日期 · Asia/Shanghai（留空取消）",
                        type: "date",
                      },
                    ]
                  : [
                      {
                        name: "require_password_change",
                        label: "首次登录要求修改密码",
                        type: "switch",
                      },
                    ]
          }
          initial={
            editing === "password"
              ? { require_password_change: true, revision: account.revision }
              : editing === "quotas"
                ? quotaInitial
                : account
          }
          onClose={() => setEditing(null)}
          onSave={async (v) => {
            if (editing === "quotas") setQuotaChange(v);
            else setPolicyChange({kind: editing!, values: v});
          }}
        />
      ) : null}
      {policyChange ? <PreviewDialog title="账号登录策略变更预览" previewPath={`/system-users/${account.id}/change-preview`} previewBody={{action:"update", revision:policyChange.values.revision, changes:Object.fromEntries(Object.entries(policyChange.values).filter(([k]) => !["password","revision","token"].includes(k)))}} executePath={`/system-users/${account.id}/${policyChange.kind}`} executeBody={policyChange.values} method={policyChange.kind === "password" ? "POST" : "PATCH"} warning="密码仅用于本次提交，不保存在预览或审计中。账号限制独立生效；请核对改密与有效期影响。" onClose={() => setPolicyChange(null)} /> : null}
      {quotaChange ? <PreviewDialog title="配额影响预览" previewPath={`/system-users/${account.id}/quotas/preview`} previewBody={quotaChange} executePath={`/system-users/${account.id}/quotas`} executeBody={quotaChange} method="PATCH" warning="请核对服务器返回的实际 UID 用量与新限额；低于用量时新写入可能失败，文件不会被删除。" onClose={() => setQuotaChange(null)} /> : null}
      <ErrorAlert error={save.error} />
    </Card>
  );
}
export function SystemGroups() {
  const q = useData("/system-groups");
  const [edit, setEdit] = useState<Row | null>(null);
  const [action, setAction] = useState<Row | null>(null);
  const save = useSave();
  const fields: Field[] = [
    { name: "name", label: "系统组名", required: true },
    {
      name: "members",
      label: "附属组成员（用户名，回车添加）",
      type: "tags",
      help: "不改变用户主组；sudo/docker 等敏感组禁止授权。",
    },
  ];
  return (
    <>
      <PageHead
        title="Linux 系统用户组"
        description="系统组决定文件访问权限，与业务优先级独立。移除成员不会撤销旧进程组身份或已打开的文件句柄，用户需要重新登录。"
        action={
          <Button type="primary" onClick={() => setEdit({ members: [] })}>
            创建普通系统组
          </Button>
        }
      />
      <ErrorAlert error={q.error || save.error} />
      <Card>
        <Table<Row>
          scroll={{ x: 1100 }}
          size="small"
          tableLayout="fixed"
          rowKey="id"
          loading={q.isPending}
          dataSource={q.data || []}
          columns={[
            { title: "组名", dataIndex: "name", width: 150, render: (v) => <CompactText value={v} /> },
            { title: "GID", dataIndex: "gid", width: 140 },
            {
              title: "附属组成员",
              width: 240,
              dataIndex: "members",
              render: (v) => <CompactText value={v?.join(", ")} />,
            },
            {
              title: "管理状态",
              width: 140,
              render: (_, r) => (
                <Space>
                  {r.protected ? <Tag>保护</Tag> : null}
                  <Tag>{r.managed ? "受管" : "只读"}</Tag>
                </Space>
              ),
            },
            {
              title: "操作",
              width: 190,
              render: (_, r) => (
                <Space>
                  <Button
                    size="small"
                    disabled={r.name === "human" || r.protected || !r.managed || r.recovery_required}
                    onClick={() => setEdit(r)}
                  >
                    编辑
                  </Button>
                  <Button
                    size="small"
                    danger
                    disabled={r.name === "human" || r.protected || !r.managed || !!r.members?.length}
                    onClick={() =>
                      setAction({ ...r, action: "delete", changes: {} })
                    }
                  >
                    删除空组
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      {edit ? (
        <EditDialog
          title={edit.id ? "修改系统组" : "创建普通系统组"}
          initial={edit}
          fields={fields}
          onClose={() => setEdit(null)}
          onSave={async (v) => {
            if (edit.id) setAction({ ...edit, action: "update", changes: v });
            else
              await save.mutateAsync({
                path: "/system-groups",
                method: "POST",
                body: v,
              });
          }}
        />
      ) : null}
      {action ? (
        <PreviewDialog
          title="系统组变更预览"
          previewPath={`/system-groups/${action.id}/change-preview`}
          previewBody={{
            action: action.action,
            revision: action.revision,
            changes: action.changes,
          }}
          executePath={`/system-groups/${action.id}`}
          method={action.action === "delete" ? "DELETE" : "PATCH"}
          executeBody={{ ...action.changes, revision: action.revision }}
          onClose={() => setAction(null)}
          warning="服务器检查保护状态、成员及主组引用。权限撤销不会自动结束已有会话。"
        />
      ) : null}
    </>
  );
}
export function Storage() {
  const q = useData("/storage", true);
  const d = q.data;
  return (
    <>
      <PageHead
        title="存储与容量"
        description="个人目录统计、UID 配额与文件系统空闲空间分别展示。软删除账号仍计入用量。"
      />
      <ErrorAlert error={q.error} />
      {d ? (
        <>
          {d.status === "pending" ? <Alert type="info" showIcon message="正在统计存储用量，完成后自动更新。" /> : <Tag>采样：{date(d.collected_at)}{d.stale ? " · 数据已过期" : ""}</Tag>}
          <Alert showIcon type={d.capabilities?.acl?.status === "unavailable" ? "warning" : "info"} message={`ACL 能力：${d.capabilities?.acl?.status || "尚未验证"}`} description={d.capabilities?.acl?.message || "工具存在不等于文件系统权限已验证；初始化和共享项目创建后需核验实际访问。"} />
          {d.alerts?.length ? (
            <Alert
              type="warning"
              showIcon
              message="容量告警"
              description={<JsonView value={d.alerts} />}
            />
          ) : null}
          <Card title="文件系统" className="section-card">
            <Table<Row>
          scroll={{ x: 1100 }}
              size="small"
              tableLayout="fixed"
              rowKey="id"
              dataSource={d.filesystems || []}
              pagination={false}
              columns={[
                { title: "路径", dataIndex: "path", width: 240, render: (v) => <CompactText value={v} /> },
                { title: "类型", dataIndex: "fstype", width: 140 },
                { title: "总容量", dataIndex: "total", width: 140, render: bytes },
                { title: "可用", dataIndex: "available", width: 140, render: bytes },
                {
                  title: "配额支持",
                  width: 140,
                  render: (_, r) =>
                    r.quota_supported
                      ? r.quota_enabled
                        ? "已启用"
                        : "尚未启用"
                      : "不支持",
                },
                { title: "检测结果", dataIndex: "error", width: 240, render: (v) => <CompactText value={v} /> },
              ]}
            />
          </Card>
          <Card title="个人目录用量" className="section-card">
            <Table<Row>
          scroll={{ x: 1100 }}
              size="small"
              tableLayout="fixed"
              rowKey="account_id"
              dataSource={d.users || []}
              columns={[
                { title: "用户", dataIndex: "username", width: 150, render: (v) => <CompactText value={v} /> },
                { title: "主目录", dataIndex: "home_bytes", width: 140, render: bytes },
                { title: "数据目录", dataIndex: "data_bytes", width: 140, render: bytes },
                { title: "文件数", dataIndex: "files", width: 140, render: label },
                { title: "采样时间", dataIndex: "collected_at", width: 140, render: compactDate },
                {
                  title: "状态",
                  width: 190,
                  dataIndex: "status",
                  render: (v) => <Status value={v} />,
                },
              ]}
            />
          </Card>
          <Card title="共享目录用量" className="section-card">
            <JsonView value={d.shares} />
          </Card>
        </>
      ) : (
        <Card loading={q.isPending} />
      )}
    </>
  );
}
export function Shares() {
  const q = useData("/shares");
  const groups = useData("/system-groups");
  const [edit, setEdit] = useState<Row | null>(null);
  const [action, setAction] = useState<Row | null>(null);
  const save = useSave();
  const options = groups.data
    ?.filter((g: Row) => !g.protected)
    .map((g: Row) => ({ label: g.name, value: g.name }));
  return (
    <>
      <PageHead
        title="团队共享目录"
        description="共享项目与个人私有目录隔离。使用组权限与继承 ACL；不自动移动或删除已有文件。"
        action={
          <Button type="primary" onClick={() => setEdit({})}>
            创建共享项目
          </Button>
        }
      />
      <Alert
        type="warning"
        showIcon
        message="授权撤销后，已有会话可能保留组权限和打开的文件句柄；请通知用户重新登录。不会自动终止会话或默认递归修改已有文件。"
      />
      <ErrorAlert error={q.error || save.error} />
      <Card className="section-card">
        <Table<Row>
          scroll={{ x: 1100 }}
          size="small"
          tableLayout="fixed"
          rowKey="id"
          loading={q.isPending}
          dataSource={q.data || []}
          columns={[
            { title: "项目", dataIndex: "name", width: 150, render: (v) => <CompactText value={v} /> },
            { title: "路径", dataIndex: "path", width: 240, render: (v) => <CompactText value={v} /> },
            { title: "只读组", dataIndex: "reader_group", width: 150, render: (v) => <CompactText value={v} /> },
            { title: "读写组", dataIndex: "writer_group", width: 150, render: (v) => <CompactText value={v} /> },
            { title: "用量", dataIndex: "usage_bytes", width: 140, render: bytes },
            {
              title: "状态",
              width: 190,
              dataIndex: "status",
              render: (v) => <Status value={v} />,
            },
            {
              title: "操作",
              width: 130,
              render: (_, r) => (
                <Button size="small" onClick={() => setEdit(r)}>
                  编辑授权
                </Button>
              ),
            },
          ]}
        />
      </Card>
      {edit ? (
        <EditDialog
          title={edit.id ? "修改共享授权" : "创建共享项目"}
          initial={edit}
          fields={[
            { name: "name", label: "项目名", required: true, disabled: !!edit.id },
            {
              name: "reader_group",
              label: "只读系统组",
              type: "select",
              options,
            },
            {
              name: "writer_group",
              label: "读写系统组",
              type: "select",
              options,
            },
            notes,
          ]}
          onClose={() => setEdit(null)}
          onSave={async (v) => {
            setAction({ ...edit, changes: v });
          }}
        />
      ) : null}
      {action ? (
        <PreviewDialog
          title="共享授权变更预览"
          previewPath={action.id ? `/shares/${action.id}/change-preview` : "/shares/change-preview"}
          previewBody={action.id ? { revision: action.revision, changes: action.changes } : {action:"create",changes:action.changes}}
          executePath={action.id ? `/shares/${action.id}` : "/shares"}
          executeBody={action.id ? {...action.changes, revision:action.revision} : action.changes}
          method={action.id ? "PATCH" : "POST"}
          onClose={() => setAction(null)}
        />
      ) : null}
    </>
  );
}
export function Settings() {
  const q = useData("/settings");
  const save = useSave();
  const [edit, setEdit] = useState(false);
  const fields: Field[] = [
    ...[
      "scan_interval_seconds",
      "term_grace_seconds",
      "default_max_runtime_seconds",
      "storage_scan_interval_seconds",
      "warning_percent",
      "critical_percent",
    ].map((name) => ({
      name,
      label: (
        {
          scan_interval_seconds: "GPU 扫描周期 (秒)",
          term_grace_seconds: "SIGTERM 退出等待 (秒)",
          default_max_runtime_seconds: "默认最大运行时间",
          storage_scan_interval_seconds: "存储扫描周期 (秒)",
          warning_percent: "容量提醒阈值 (%)",
          critical_percent: "容量严重阈值 (%)",
        } as Row
      )[name],
      type: name === "default_max_runtime_seconds" ? "duration" as const : "number" as const,
      min: 1,
      max: name.endsWith("percent") ? 100 : undefined,
    })),
    {
      name: "default_deadline_action",
      label: "默认到期动作",
      type: "select",
      options: [
        { label: "仅提醒", value: "notify" },
        { label: "自动终止", value: "terminate" },
      ],
    },
  ];
  return (
    <>
      <PageHead
        title="策略与初始化配置"
        description="目录根与运行模式只读。路径、挂载、权限和密码/PAM 能力由宿主机服务验证。"
        action={
          <Button
            type="primary"
            disabled={!q.data}
            onClick={() => setEdit(true)}
          >
            编辑策略
          </Button>
        }
      />
      <ErrorAlert error={q.error || save.error} />
      <Card loading={q.isPending}>
        {q.data ? <RecordDetail row={q.data} /> : null}
      </Card>
      <Alert
        className="section-card"
        type="info"
        showIcon
        message="首次改密与 SSH/PAM 限制按账号管理。全机密码质量、配额/ACL 启用需部署验证；平台不会格式化、重挂载或重启数据卷。"
      />
      {edit ? (
        <EditDialog
          title="编辑全局策略"
          initial={q.data}
          fields={fields}
          onClose={() => setEdit(false)}
          onSave={(v) => save.mutateAsync({ path: "/settings", body: v })}
        />
      ) : null}
    </>
  );
}
export function Logs({ kind }: { kind: "audit" | "login" }) {
  const login = kind === "login";
  const [filters, setFilters] = useState<Row>({
    page: 1,
    page_size: 20,
    username: login
      ? new URLSearchParams(window.location.search).get("username") || ""
      : "",
  });
  const q = useData(
    `${login ? "/login-events" : "/audit-logs"}${params(filters)}`,
  );
  const set = (name: string, value: any) =>
    setFilters({ ...filters, [name]: value, page: 1 });
  return (
    <>
      <PageHead
        title={login ? "SSH 登录记录" : "操作审计"}
        description={
          login
            ? "只展示可确认的日志事实。缺失历史表示无覆盖，不代表没有登录。"
            : "记录管理员与自动策略操作、变更前后值及失败原因。"
        }
      />
      <Card>
        <Space wrap className="filters">
          {(login ? ["username", "ip"] : ["actor", "action"]).map((name) => (
            <Input
              key={name}
              placeholder={
                name === "username"
                  ? "用户名"
                  : name === "ip"
                    ? "来源 IP"
                    : name === "actor"
                      ? "操作人"
                      : "操作类型"
              }
              aria-label={name}
              value={filters[name]}
              onChange={(e) => set(name, e.target.value)}
            />
          ))}
          <Select
            aria-label="结果筛选"
            placeholder="全部结果"
            allowClear
            options={(login
              ? ["success", "failure"]
              : ["succeeded", "failed", "pending", "demo"]
            ).map((value) => ({ label: statusLabel(value), value }))}
            onChange={(v) => set("result", v)}
          />
          <Input
            type="datetime-local"
            aria-label="起始时间"
            onChange={(e) =>
              set(
                "since",
                e.target.value
                  ? new Date(`${e.target.value}+08:00`).toISOString()
                  : undefined,
              )
            }
          />
          <Input
            type="datetime-local"
            aria-label="结束时间"
            onChange={(e) =>
              set(
                "until",
                e.target.value
                  ? new Date(`${e.target.value}+08:00`).toISOString()
                  : undefined,
              )
            }
          />
        </Space>
        <ErrorAlert error={q.error} />
        {login && q.data ? (
          <details className="log-coverage">
            <summary><span>日志扫描覆盖</span><Typography.Text type="secondary">{typeof q.data.coverage === "object" ? q.data.coverage?.status ? statusLabel(q.data.coverage.status) : "查看来源与历史覆盖" : q.data.coverage}</Typography.Text></summary>
            <JsonView value={q.data.coverage} />
          </details>
        ) : null}
        <Table<Row>
          size="small"
          tableLayout="fixed"
          loading={q.isPending}
          rowKey="id"
          dataSource={q.data?.items || []}
          scroll={{ x: 1100 }}
          expandable={{ expandedRowRender: (r) => <RecordDetail row={r} /> }}
          pagination={{
            current: filters.page,
            pageSize: filters.page_size,
            total: q.data?.total,
            showSizeChanger: true,
            onChange: (page, page_size) =>
              setFilters({ ...filters, page, page_size }),
          }}
          columns={
            login
              ? [
                  { title: "时间", dataIndex: "time", width: 140, render: compactDate },
                  { title: "用户名", dataIndex: "username", width: 150, render: (v) => <CompactText value={v} /> },
                  { title: "来源 IP", dataIndex: "ip", width: 150, render: (v) => <CompactText value={v} /> },
                  { title: "登录方式", dataIndex: "method", width: 150, render: (v) => <CompactText value={v} /> },
                  {
                    title: "结果",
                    width: 100,
                    dataIndex: "result",
                    render: (v) => <Status value={v} />,
                  },
                  { title: "公钥指纹", dataIndex: "fingerprint", width: 240, render: (v) => <CompactText value={v} /> },
                ]
              : [
                  { title: "时间", dataIndex: "time", width: 140, render: compactDate },
                  { title: "操作人", dataIndex: "actor", width: 150, render: (v) => <CompactText value={v} /> },
                  { title: "操作", dataIndex: "action", width: 180, render: (v) => <CompactText value={auditActions[v] || v} /> },
                  {
                    title: "目标",
                    width: 260,
                    dataIndex: "target",
                    render: (v) => <CompactText value={v} />,
                  },
                  {
                    title: "结果",
                    width: 100,
                    dataIndex: "result",
                    render: (v) => <Status value={v} />,
                  },
                  { title: "原因", dataIndex: "reason", width: 240, render: (v) => <CompactText value={v} /> },
                ]
          }
        />
      </Card>
    </>
  );
}
