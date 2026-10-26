import {SystemGroupMembers} from "./system-group-members";
import { UserTaskPolicy, groupLabel, PolicySummary } from "./user-groups";
import {canGrantShareAccess,ShareMemberEditor} from "./share-members";
import { creationStageLabel, errorGuidance, readonlyReason, useHostMutations } from "./readiness";
import { type ReactNode, useState } from "react";
import { translate, useI18n } from "./i18n";
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Skeleton,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
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
  TermLabel,
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
    name: "deadline_action",
    label: "到期动作",
    type: "select",
    required: true,
    options: [
      { label: "仅提醒", value: "notify" },
      { label: "自动终止", value: "terminate" },
    ],
  },
  { name: "orphan_reminder", label: "残留提醒", type: "switch", help: "主进程退出后等待提醒；残留进程仅由管理员预览确认后终止" },
  { name: "orphan_wait_seconds", label: "残留等待时间", type: "duration", required: true, min: 1, max: 86400 },
];
const preciseDuration = (seconds: number) => translate("{hours}时 {minutes}分 {seconds}秒", { hours: Math.floor(seconds / 3600), minutes: Math.floor(seconds % 3600 / 60), seconds: seconds % 60 });
const residualEligible = (task: Row, stale = false) => task.status === "awaiting_cleanup" && task.is_human && !task.protected && !task.stale && !stale && task.policy_status === "applied";
const scopeOptions = [{ label: "人员账号", value: "human" }, { label: "其他账号（只读）", value: "other" }, { label: "全部账号", value: "all" }];
const classification = () => ({ width: 145, title: translate("分类"), dataIndex: "is_human", render: (v: boolean) => <Tag>{v ? translate("人员账号") : translate("其他账号 · 只读")}</Tag> });
const label = (value: any) => (value == null ? translate("无数据") : String(value));
const compactDate = (value: string | null | undefined) => (
  <Tooltip title={`${date(value)} · Asia/Shanghai`}>
    <span className="compact-text" tabIndex={0} title={`${date(value)} · Asia/Shanghai`}>{date(value).replace(/^(\d{4})\//, "").replace(/:\d{2}$/, "")}</span>
  </Tooltip>
);
const auditActions: Record<string, string> = {
  "auth.login": "管理员登录", "group.create": "创建任务策略组", "group.update": "修改任务策略组", "group.delete": "删除任务策略组",
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
  useI18n();
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
        <Descriptions.Item key={k} label={translate(k)}>
          {typeof v === "object" ? JSON.stringify(v) : ["status", "policy_status", "result", "deadline_action", "default_deadline_action"].includes(k) ? statusLabel(v) : label(v)}
        </Descriptions.Item>
      ))}
    </Descriptions>
  );
}
export function Overview() {
  useI18n();
  const q = useData("/overview", true);
  const d = q.data;
  return (
    <>
      <PageHead
        title={translate("服务器总览")}
        description={translate("GPU 资源、运行任务与异常概况。")}
      />
      <ErrorAlert error={q.error} />
      {d ? (
        <>
          <Source data={d} />
          {d.agent_error ? (
            <Alert
              showIcon
              type="error"
              message={translate("采集服务异常")}
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
              [translate("运行任务"), d.task_count],
              [translate("超时任务"), d.overdue_count],
              [translate("异常告警"), d.anomaly_count],
              [translate("待清理任务"), d.awaiting_cleanup_count],
            ].map(([title, value]) => (
              <Col xs={24} md={6} key={title}>
                <Card>
                  <Statistic title={title} value={value ?? translate("无数据")} />
                </Card>
              </Col>
            ))}
          </GridRow>
          <Typography.Title level={4}>{translate("GPU 资源")}</Typography.Title>
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
                        title={translate("显存使用")}
                        value={bytes(gpu.memory_used)}
                      />
                      <Statistic
                        title={translate("总显存")}
                        value={bytes(gpu.memory_total)}
                      />
                      <Statistic
                        title={translate("GPU 利用率")}
                        value={gpu.utilization ?? translate("无数据")}
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
          {!q.isPending ? <Empty description={translate("未取得总览数据")} /> : null}
        </Card>
      )}
    </>
  );
}
export function Tasks() {
  useI18n();
  const host = useHostMutations();
  const defaults: Row = {
    page: 1,
    page_size: 20,
    sort: "priority",
    scope: "human",
    status: "active",
  };
  const [filter, setFilter] = useState<Row>(defaults);
  const [selected, setSelected] = useState<React.Key[]>([]);
  const changeFilter = (changes: Row) => { setFilter(current => ({ ...current, ...changes, page: 1 })); setSelected([]); };
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
        title={translate("GPU 任务")}
        description={translate("默认仅显示人员账号的进行中任务；已结束任务请切换状态查看。")}
        action={
          <Button
            disabled={selected.length < 2}
            onClick={() => setMerging(true)}
          >
            {translate("合并所选任务 (")}{selected.length})
          </Button>
        }
      />
      <Card>
        <Space wrap className="filters">
          <Select aria-label={translate("任务范围")} value={filter.scope} options={scopeOptions.map(option => ({ ...option, label: translate(option.label) }))} onChange={(scope) => { changeFilter({ scope, uid: undefined }); }} />
          <Select
            aria-label={translate("GPU 筛选")}
            value={filter.gpu}
            placeholder={translate("全部 GPU")}
            allowClear
            options={gpus.data?.items?.map((g: Row) => ({
              label: `GPU ${g.index} · ${g.name}`,
              value: g.uuid,
            }))}
            onChange={(v) => changeFilter({ gpu: v })}
          />
          <Select
            aria-label={translate("任务策略组筛选")}
            value={filter.group_id}
            placeholder={translate("全部任务策略组")}
            allowClear
            options={groups.data?.map((g: Row) => ({
              label: groupLabel(g),
              value: g.id,
            }))}
            onChange={(v) => changeFilter({ group_id: v })}
          />
          <Select
            aria-label={translate("用户筛选")}
            value={filter.uid}
            placeholder={translate("全部用户")}
            allowClear
            options={users.data?.map((u: Row) => ({
              label: u.username,
              value: u.uid,
            }))}
            onChange={(v) => changeFilter({ uid: v })}
          />
          <Select
            aria-label={translate("状态筛选")}
            value={filter.status}
            placeholder={translate("全部状态")}
            allowClear
            options={[
              { label: translate("全部进行中任务"), value: "active" },
              { label: translate("运行中"), value: "running" },
              { label: translate("收尾中"), value: "finalizing" },
              { label: translate("待清理"), value: "awaiting_cleanup" },
              { label: translate("清理中"), value: "cleaning" },
              { label: translate("已超时"), value: "overdue" },
              { label: translate("有异常"), value: "anomaly" },
              { label: translate("已结束"), value: "finished" },
            ]}
            onChange={(v) => changeFilter({ status: v })}
          />
          <Select
            aria-label={translate("排序")}
            value={filter.sort}
            options={[
              { label: translate("优先级"), value: "priority" },
              { label: translate("运行时间"), value: "runtime" },
              { label: translate("显存占用"), value: "memory" },
            ]}
            onChange={(v) => changeFilter({ sort: v })}
          />
          <Button onClick={() => { setFilter(defaults); setSelected([]); }}>{translate("重置筛选")}</Button>
        </Space>
        <Typography.Paragraph type="secondary">
          {translate("匹配 {count} 个任务", { count: data?.total ?? 0 })} · {translate("GPU 按任务曾使用的设备筛选；旧任务未保留设备信息时，仅在全部 GPU 中可见。")}
        </Typography.Paragraph>
        <ErrorAlert error={q.error || gpus.error || groups.error || users.error || save.error} />
        {data ? <Source data={data} /> : null}
        <Table<Row>
          size="small"
          tableLayout="fixed"
          loading={q.isFetching}
          locale={{ emptyText: <Empty description={translate(q.error ? "任务加载失败，请重试" : "当前筛选条件下没有任务")}>
            <Space wrap>
              {q.error ? <Button onClick={() => q.refetch()}>{translate("重试")}</Button> : <>
                {filter.status !== "finished" ? <Button onClick={() => changeFilter({ status: "finished" })}>{translate("查看已结束任务")}</Button> : null}
                <Button onClick={() => { setFilter({ ...defaults, scope: "all", status: undefined }); setSelected([]); }}>{translate("清除筛选，查看全部任务")}</Button>
              </>}
            </Space>
          </Empty> }}
          rowKey="id"
          dataSource={data?.items || []}
          rowSelection={{
            selectedRowKeys: selected,
            preserveSelectedRowKeys: false,
            onChange: setSelected,
            getCheckboxProps: (r) => ({ disabled: !r.is_human || r.protected || r.status === "finished" }),
          }}
          scroll={{ x: 1540 }}
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
              title: translate("任务"),
              width: 210,
              dataIndex: "name",
              render: (v, r) => <Link to={`/tasks/${r.id}`}><CompactText value={v || r.id} tooltip={translate("原始名称：{name}", { name: r.original_name || translate("未知（旧记录未保留）") })} /></Link>,
            },
            { title: translate("用户"), dataIndex: "username", width: 120, render: (v, r) => <div className="table-identity"><CompactText value={v} />{!r.is_human ? <Tag>{translate("只读")}</Tag> : null}</div> },
            {
              title: translate("优先级"),
              width: 120,
              dataIndex: "priority",
              render: (v, r) => <Tooltip title={r.priority_tuple?.some((n:number)=>n !== v) ? translate("历史三级排序已保留；新任务使用单一优先级。") : translate("有效优先级")}><Tag>{r.priority_tuple?.some((n:number)=>n !== v) ? r.priority_tuple.join(" / ") : v ?? "—"}</Tag></Tooltip>,
            },
            {
              title: translate("运行时间"),
              width: 110,
              dataIndex: "runtime_seconds",
              render: duration,
            },
            {
              title: translate("剩余时间"),
              width: 110,
              dataIndex: "remaining_seconds",
              render: (v, r) => (
                <span className={r.overdue ? "danger" : ""}>{duration(v)}</span>
              ),
            },
            { title: translate("使用过的 GPU"), width: 140, render: (_, r) => {
              const uuids: string[] = [...new Set<string>([...(r.gpu_uuids || []), ...(r.members || []).flatMap((m: Row) => Object.keys(m.gpu_memory || {}))])];
              return uuids.length ? uuids.map(uuid => { const device = gpus.data?.items?.find((g: Row) => g.uuid === uuid); return <Tooltip key={uuid} title={uuid}><Tag>{device ? `GPU ${device.index}` : translate("离线 GPU")}</Tag></Tooltip>; }) : <Tooltip title={translate("旧记录未保留 GPU 信息")}><span>—</span></Tooltip>;
            } },
            { title: translate("显存"), dataIndex: "memory_used", width: 100, render: bytes },
            {
              title: translate("状态"),
              width: 150,
              dataIndex: "status",
              render: (v, r) => (
                <Space wrap>
                  <Status value={v} />
                  {r.protected ? <Tag>{translate("保护")}</Tag> : null}
                  {r.overdue ? <Tag color="red">{translate("超时")}</Tag> : null}
                </Space>
              ),
            },
            { title: <TermLabel label="残留提醒" />, width: 190, render: (_, r) => <Space direction="vertical" size={0}>
              <span>{translate(r.orphan_reminder ? "已启用" : "已关闭")} · {translate("等待 {duration}", { duration: preciseDuration(r.orphan_wait_seconds ?? 300) })}</span>
              {r.orphan_remaining_seconds != null ? <span>{translate("提醒剩余 {duration}", { duration: preciseDuration(r.orphan_remaining_seconds) })}</span> : null}
              {r.status === "awaiting_cleanup" ? <Typography.Text type="warning">{translate("主进程已退出，残留进程等待人工处理")}</Typography.Text> : null}
            </Space> },
            {
              title: translate("操作"),
              width: 160,
              render: (_, r) => <Space direction="vertical" size={4}>
                {residualEligible(r, data?.stale) ? <Button danger size="small" disabled={!host.writable} onClick={() => setTermination({ ...r, residualOnly: true })}>{translate("终止残留进程")}</Button> : null}
                <Button danger size="small" disabled={!host.writable || !r.is_human || r.protected || r.status === "finished"} onClick={() => setTermination(r)}>{translate("终止任务")}</Button>
              </Space>,
            },
            {
              title: translate("异常"),
              width: 60,
              dataIndex: "anomalies",
              render: (v) =>
                v?.length ? <Tag color="orange">{v.length} {translate("项")}</Tag> : "—",
            },
          ]}
        />
      </Card>
      {termination ? <TerminationDialog task={termination} residualOnly={termination.residualOnly} onClose={() => setTermination(null)} /> : null}
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
    <Card className="inline-dialog" title={translate("确认合并任务")}>
      <Alert
        type="warning"
        message={translate("只合并同一用户的相关任务；服务器会重新核验进程归属和版本。")}
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
          {translate("确认合并")}
        </Button>
        <Button onClick={onClose}>{translate("取消")}</Button>
      </Space>
    </Card>
  );
}
export function TaskDetail() {
  useI18n();
  const host = useHostMutations();
  const { id } = useParams();
  const q = useData(`/tasks/${encodeURIComponent(id!)}`, true);
  const gpuDevices = useData("/gpus");
  const gpuText = (p: Row) => Object.entries(p.gpu_memory || {}).length ? Object.entries(p.gpu_memory).map(([uuid, value]) => { const device = gpuDevices.data?.items?.find((g: Row) => g.uuid === uuid); return `GPU ${device?.index ?? "?"} (${uuid}) · ${bytes(value as number | null)}`; }).join("；") : translate("非 GPU 辅助进程");
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
      <Space wrap>
        <Tag>PID {p.pid}</Tag>
        <Status value={p.status} />
        {p.uninterruptible_seconds != null ? <Tag color="orange">{translate("D 状态持续 {duration}", { duration: duration(p.uninterruptible_seconds) })}</Tag> : null}
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
        title={d?.name || translate("任务详情")}
        description={translate("身份以启动标识、PID 与启动时钟核验。父级 shell / SSH 只作为上下文展示。")}
        action={
          <Space wrap>
            <Link to="/tasks">{translate("返回列表")}</Link>
            <Button title={d?.policy_editable === false ? translate("仅正常启用的纳管人员账号可修改任务策略") : undefined} onClick={() => setEditing(true)} disabled={!d || !d.is_human || d.policy_editable === false}>
              {translate("编辑策略")}
            </Button>
            {d && residualEligible(d) ? <Button danger disabled={!host.writable} onClick={() => setTermination({ residualOnly: true })}>{translate("终止残留进程")}</Button> : null}
            <Button
              danger
              disabled={!host.writable || !d || !d.is_human || d.protected || d.status === "finished"}
              onClick={() => setTermination({})}
            >
              {translate("终止整个任务")}
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
                原始名称: d.original_name || translate("未知（旧记录未保留）"),
                用户名: d.username,
                分类: d.is_human ? translate("人员账号") : translate("其他账号 · 只读"),
                任务策略组: d.policy_assignment?.group_name || d.group_name || d.group_id,
                有效优先级: d.priority,
                保护状态: d.protected ? translate("已保护") : translate("未保护"),
                状态: statusLabel(d.status),
                残留提醒: translate(d.orphan_reminder ? "已启用" : "已关闭"),
                残留等待时间: preciseDuration(d.orphan_wait_seconds),
                收尾开始时间: date(d.finalizing_since),
                提醒剩余时间: d.orphan_remaining_seconds == null ? "—" : preciseDuration(d.orphan_remaining_seconds),
                "结束时间（采集确认）": date(d.finished_at),
                运行时间: duration(d.runtime_seconds),
                剩余时间: duration(d.remaining_seconds),
                预计结束时间: date(d.deadline_at),
                到期策略: statusLabel(d.deadline_action),
                策略执行状态: statusLabel(d.policy_status),
                版本: d.revision,
                备注: d.notes,
              }}
            />
            {d.status === "awaiting_cleanup" ? <Alert type="warning" showIcon message={translate("主进程已退出，残留进程等待人工处理")} description={translate("预览并填写原因后才能终止；也可以等待进程自然退出。不会自动清理。")} /> : null}
            {d.overdue ? (
              <Alert
                type="warning"
                showIcon
                message={translate("任务已超时；高优先级不会自动豁免期限，保护任务只提醒。")}
              />
            ) : null}
            {d.anomalies?.length ? <JsonView value={d.anomalies} /> : null}
          </Card>
          <Card title={translate("任务策略快照")} className="section-card">
            <PolicySummary policy={d} sources={d.policy_sources}/>
            <Typography.Paragraph type="secondary">{translate("来源记录任务纳入管理时的配置；后续分组变化不会覆盖此快照。")}</Typography.Paragraph>
          </Card>
          <Card title={translate("进程关系与范围")} className="section-card">
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
                  title: translate("状态"),
                  width: 190,
                  dataIndex: "status",
                  render: (v) => <Status value={v} />,
                },
                { title: translate("GPU / 显存"), width: 190, render: (_, p) => <CompactText value={gpuText(p)} /> },
                { title: translate("命令"), dataIndex: "command", width: 280, render: (v) => <CompactText value={v} /> },
                { title: translate("启动时间"), dataIndex: "create_time", width: 140, render: compactDate },
                {
                  title: translate("关联依据"),
                  width: 200,
                  dataIndex: "evidence",
                  render: (v) => <CompactText value={v} />,
                },
                {
                  title: translate("操作"),
                  width: 130,
                  render: (_, p) => (
                    <Button
                      danger
                      size="small"
                      disabled={!host.writable || !d.is_human || d.protected || p.status === "Z"}
                      onClick={() => setTermination(p.identity)}
                    >
                      {translate("终止进程")}
                    </Button>
                  ),
                },
              ]}
            />
            <Space wrap>
              <Button
                disabled={!d.is_human || d.protected || !chosen.length}
                onClick={() => setMembership("split")}
              >
                {translate("拆分所选进程")}
              </Button>
              <Button
                disabled={!d.is_human || d.protected || !chosen.length}
                onClick={() => setMembership("exclude")}
              >
                {translate("排除所选归属")}
              </Button>
            </Space>
          </Card>
        </>
      ) : (
        <Card loading={q.isPending} />
      )}{" "}
      {editing && d ? (
        <EditDialog
          title={translate("编辑任务")}
          fields={taskFields.map(field => ({ ...field, options: field.options?.map(option => ({ ...option, label: translate(option.label) })) }))}
          initial={d}
          onClose={() => setEditing(false)}
          onSave={(v) => save.mutateAsync({ path: `/tasks/${id}`, body: { ...v, expires_at: null } })}
        />
      ) : null}
      {termination && d ? (
        <TerminationDialog
          task={d}
          residualOnly={termination.residualOnly}
          identity={!termination.residualOnly && Object.keys(termination).length ? termination : undefined}
          onClose={() => setTermination(null)}
        />
      ) : null}
      {membership && d ? (
        <EditDialog
          title={
            membership === "split" ? translate("确认拆分所选进程") : translate("确认排除进程归属")
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
  useI18n();
  const host = useHostMutations();
  const [state, setState] = useState("active");
  const [scope, setScope] = useState("human");
  const { id } = useParams();
  const q = useData(id ? `/system-users/${encodeURIComponent(id)}` : `/system-users${params({ state, scope })}`);
  const systemGroups = useData("/system-groups?scope=all");
  const [edit, setEdit] = useState<Row | null>(null);
  const [action, setAction] = useState<{ row: Row; action: string; changes?: Row } | null>(
    null,
  );
  const [resume, setResume] = useState<Row | null>(null);
  const save = useSave();
  const assignableGroups = (systemGroups.data || []).filter((g: Row) => g.assignable === true);
  const editableGroups = (edit?.groups || []).filter((name: string) => assignableGroups.some((g: Row) => g.name === name));
  const readonlyGroups = (edit?.groups || []).filter((name: string) => !assignableGroups.some((g: Row) => g.name === name));
  const baseFields = [
    ...accountFields.map(field => field.name === "groups" ? {
      ...field, type: "multiple" as const,
      options: assignableGroups.map((g: Row) => ({ label: groupLabel(g), value: g.name })),
      help: translate("仅可选择受管普通权限组；human 仅用于人员分类，不授予项目权限。只读组由服务器保留。") + (readonlyGroups.length ? " " + translate("只读附属组：{groups}", { groups: readonlyGroups.join(", ") }) : ""),
    } : field),
    ...(edit?.id ? [{name:"primary_group",label:translate("普通主系统组"),type:"select" as const,
      options:systemGroups.data?.filter((g:Row)=>g.assignable === true || g.name === edit.primary_group || (g.name === edit.private_group && g.gid === edit.private_gid && !g.identity_conflict)).map((g:Row)=>({label:g.name,value:g.name})),
      help:translate("按 Linux 原生规则修改；主目录内旧组文件可能同步改变组归属，其他路径保留原归属。")}] : []),
  ];
  const accountActions = (r: Row) => (
    <Space wrap>
      {r.creation?.status === "incomplete" ? <Button size="small" disabled={!host.writable || r.protected || !r.is_human || r.readonly_reasons?.some((reason:string) => reason !== "creation_incomplete")} onClick={() => setResume(r)}>{translate("继续创建")}</Button> : null}
      {readonlyReason(r) ? <Typography.Text type="secondary">{readonlyReason(r)}</Typography.Text> : null}
      <Button
        size="small"
        disabled={!host.writable || systemGroups.isPending || !!systemGroups.error || !r.is_human || r.protected || !r.managed || !!r.deleted_at || r.recovery_required || !!r.readonly_reasons?.length}
        onClick={() => setEdit(r)}
      >
        {translate("编辑")}
      </Button>
      {r.is_human && !r.managed && !r.protected ? (
        <Button
          size="small"
          disabled={!host.writable || r.readonly_reasons?.some((reason:string)=>reason !== "unmanaged_account")}
          onClick={() => setAction({ row: r, action: "update" })}
        >
          {translate("启用管理")}
        </Button>
      ) : null}
      <Button
        size="small"
        disabled={!host.writable || !r.is_human || r.protected || !r.managed || !!r.deleted_at || r.recovery_required || !!r.readonly_reasons?.length}
        onClick={() =>
          setAction({
            row: r,
            action: r.disabled ? "enable" : "disable",
          })
        }
      >
        {r.disabled ? translate("启用") : translate("停用")}
      </Button>
      <Button
        size="small"
        danger
        disabled={!host.writable || !r.is_human || r.protected || !r.managed || r.recovery_required || r.readonly_reasons?.some((reason:string)=>reason !== "account_deleted")}
        onClick={() =>
          setAction({
            row: r,
            action: r.deleted_at ? "restore" : "delete",
          })
        }
      >
        {r.deleted_at ? translate("恢复") : translate("软删除")}
      </Button>
    </Space>
  );
  return (
    <>
      {!host.writable ? <Alert showIcon type="warning" message={host.reason}/> : null}
      {host.health?.root_readiness?.ready === false ? <Alert showIcon type="warning" message={translate(errorGuidance.initialization_unverified)}/> : null}
      {id ? (
        <>
          <Link className="account-back" to="/accounts"><span aria-hidden="true">← </span>{translate("返回账号列表")}</Link>
      <ErrorAlert error={q.error} />
          {q.isPending ? <Card><Skeleton active /></Card> : q.data && !q.error ? <AccountDetail key={id} account={q.data} actions={accountActions(q.data)} /> : null}
        </>
      ) : <>
      <PageHead
        title={translate("本地账号")}
        description={translate("默认展示人员账号；其他与保护账号只读。账号软删除保留全部文件与进程，已有账号需先启用管理，平台新建账号自动管理。")}
        action={
          <Button
            type="primary"
            disabled={!host.writable || host.health?.root_readiness?.ready === false || systemGroups.isPending || !!systemGroups.error}
            onClick={() =>
              setEdit({

                require_password_change: true,
                public_keys: [],
                groups: [],
              })
            }
          >
            {translate("创建账号")}
          </Button>
        }
      />
      <Card>
        <Space wrap className="filters">
          <Select aria-label={translate("账号范围")} value={scope} options={scopeOptions.map(option => ({ ...option, label: translate(option.label) }))} onChange={setScope} />
          <Select
            aria-label={translate("账号状态")}
            value={state}
            onChange={setState}
            options={[
              { label: translate("正常账号"), value: "active" },
              { label: translate("已停用"), value: "disabled" },
              { label: translate("已到期"), value: "expired" },
              { label: translate("已软删除"), value: "deleted" },
              { label: translate("全部账号"), value: "all" },
            ]}
          />
          <Tag>{translate("日期与采样时间：Asia/Shanghai")}</Tag>
        </Space>
        <ErrorAlert error={q.error || systemGroups.error || save.error} />
        <Table<Row>
          size="small"
          tableLayout="fixed"
          loading={q.isPending}
          rowKey="id"
          dataSource={q.data || []}
          scroll={{ x: 1100 }}
          columns={[
            {
              title: translate("账号"),
              width: 180,
              dataIndex: "username",
              render: (v, r) => (
                <div>
                  <Link className="account-link" to={`/accounts/${encodeURIComponent(r.id)}`}><CompactText value={v} /></Link>
                  <small className="account-id">UID {r.uid} · GID {r.gid}</small>
                </div>
              ),
            },
            classification(),
            {
              title: translate("状态"),
              width: 190,
              dataIndex: "status",
              render: (v, r) => (
                <Space wrap>
                  <Status value={v} />
                  {r.protected ? <Tag>{translate("保护")}</Tag> : null}
                  {!r.managed ? <Tag>{translate("未启用管理")}</Tag> : null}
                  {r.disabled && v !== "disabled" ? <Tag color="orange">{translate("停用限制")}</Tag> : null}
                  {r.deleted_at && v !== "deleted" ? <Tag color="red">{translate("软删除限制")}</Tag> : null}
                </Space>
              ),
            },
            { title: translate("有效期"), width: 120, render: (_, r) => <span title={r.expires_effective_at ? `${date(r.expires_effective_at)} · Asia/Shanghai` : translate("生效时间以宿主机核验为准")}>{r.expires_effective_at?.slice(0, 10) || r.expires_on || translate("不限期")}</span> },
            {
              title: translate("目录"),
              width: 160,
              render: (_, r) => (
                <CompactText value={[r.home, r.data_dir].filter(Boolean).join(" · ")} />
              ),
            },
            {
              title: translate("操作"),
              width: 270,
              fixed: "right",
              render: (_, r) => (
                accountActions(r)
              ),
            },
          ]}
        />
      </Card>
      </>}
      {edit ? (
        <EditDialog
          disabledReason={!host.writable ? host.reason : undefined}
          title={edit.id ? translate("编辑 {name}", { name: edit.username }) : translate("创建账号")}
          initial={{ ...edit, groups: editableGroups }}
          fields={
            edit.id
              ? [{name: "username", label: translate("用户名"), required: true, help: translate("仅允许空闲账号改名：没有运行进程、登录会话或定时任务；提交前由服务器核验。")}, ...baseFields]
              : [
                  { name: "username", label: translate("用户名"), required: true },
                  { name: "password", label: translate("初始密码"), type: "password" },
                  ...baseFields.filter((f) => f.name !== "shell"),
                ]
          }
          onClose={() => setEdit(null)}
          onSave={async (v) => {
            if (edit.id) {
              setAction({ row: edit, action: "update", changes: v });
            } else
              await save.mutateAsync({
                path: "/system-users",
                method: "POST",
                body: v,
              });
          }}
        >{edit._review ? <Alert type="warning" showIcon message={translate("已刷新账号状态并保留草稿，请核对后再保存。")}/> : null}</EditDialog>
      ) : null}
      {resume ? <EditDialog disabledReason={!host.writable ? host.reason : undefined} title={translate("继续创建账号")} initial={{require_password_change:true,...resume._draft}} fields={[
        {name:"password",label:translate("新密码"),type:"password"},
        {name:"public_keys",label:translate("SSH 公钥（一行一个，输入后回车添加）"),type:"tags"},
        {name:"require_password_change",label:translate("首次登录要求修改密码"),type:"switch"},
      ]} onClose={()=>setResume(null)} onSave={async values=>{if(!values.password && !values.public_keys?.length) throw new Error(translate("请重新提供密码或 SSH 公钥以继续创建。"));setAction({row:resume,action:"resume",changes:values});setResume(null);}}/> : null}
      {action ? (
        <PreviewDialog
          title={translate("账号操作预览 · {action}", { action: ({ resume: translate("继续创建"), disable: translate("停用"), enable: translate("启用"), delete: translate("软删除"), restore: translate("恢复"), update: action.row.managed ? translate("修改") : translate("启用管理") } as Record<string, string>)[action.action] })}
          previewPath={`/system-users/${action.row.id}/change-preview`}
          previewBody={{
            action: action.action,
            revision: action.row.revision,
            changes:
              action.action === "update"
                ? action.changes || { managed: true }
                : {},
          }}
          executePath={`/system-users/${action.row.id}${["disable", "enable", "restore", "resume"].includes(action.action) ? `/${action.action}` : ""}`}
          method={
            action.action === "delete"
              ? "DELETE"
              : action.action === "update"
                ? "PATCH"
                : "POST"
          }
          executeBody={{
            revision: action.row.revision,
            ...(["update", "resume"].includes(action.action)
              ? action.changes || { managed: true }
              : {}),
          }}
          onEdit={async () => {
            const current = await api(`/system-users/${encodeURIComponent(action.row.id)}`);
            await systemGroups.refetch({throwOnError:true});
            if (action.action === "update" && action.changes) setEdit({...current,...action.changes,revision:current.revision,_review:true});
            else if (action.action === "resume") setResume({...current,_draft:action.changes});
            else await q.refetch({throwOnError:true});
            setAction(null);
          }}
          onClose={() => {
            setAction(null);
          }}
          warning={translate("只更改后续登录和账号配置，不结束已有进程、会话、定时任务或用户服务。软删除保留目录与文件；恢复/启用不会绕过其他登录限制。")}
        />
      ) : null}
    </>
  );
}
export function AccountDetail({
  account: initialAccount,
  actions,
}: {
  account: Row;
  actions?: ReactNode;
}) {
  useI18n();
  const host = useHostMutations();
  const detail = useData(`/system-users/${initialAccount.id}`);
  const account = detail.data || initialAccount;
  const immutable = !host.writable || !!account.readonly_reasons?.length || detail.isPending || !!detail.error || !account.is_human || !account.managed || account.protected || !!account.deleted_at || account.recovery_required;
  const [policyDraft, setPolicyDraft] = useState<Row | null>(null);
  const [policyChange, setPolicyChange] = useState<{kind: string, values: Row} | null>(null);
  const activity = useData(`/system-users/${account.id}/activity`);
  const storage = useData("/storage", true);
  const [editing, setEditing] = useState<
    "password" | "expiry" | "password-policy" | null
  >(null);
  const save = useSave();
  return (
    <div className="account-management">
      <PageHead title={account.username} description={`UID ${account.uid} · GID ${account.gid}`} action={actions} />
      <Space wrap className="account-status">
        <Status value={account.status} />
        <Tag color={account.managed ? "blue" : undefined}>{translate(account.managed ? "受管" : "未启用管理")}</Tag>
        {account.protected ? <Tag>{translate("保护")}</Tag> : null}
        {account.disabled && account.status !== "disabled" ? <Tag color="orange">{translate("停用限制")}</Tag> : null}
        {account.deleted_at && account.status !== "deleted" ? <Tag color="red">{translate("软删除限制")}</Tag> : null}
      </Space>
      <ErrorAlert error={detail.error} />
      {immutable && !detail.isPending ? <Alert showIcon type="info" message={translate("此账号当前只读")} description={readonlyReason(account) || (!host.writable ? host.reason : translate("受保护、未启用管理、非人员、已软删除或待恢复的账号不能直接修改。可用操作以页面按钮为准。"))} /> : null}
      <div className="account-profile-grid">
        <Card title={translate("基本资料")}>
          <Descriptions column={1} size="small" items={[
            {key:"username",label:translate("用户名"),children:account.username},
            {key:"shell",label:translate("登录 Shell"),children:<Typography.Text code>{account.shell || "—"}</Typography.Text>},
            {key:"expiry",label:translate("有效期"),children:account.expires_effective_at ? `${date(account.expires_effective_at)} · Asia/Shanghai` : account.expires_on || translate("不限期")},

            {key:"notes",label:translate("备注"),children:account.notes || "—"},
          ]} />
        </Card>
        <Card title={translate("权限与目录")} extra={<Link to="/system-groups">{translate("系统用户组")}</Link>}>
          <Descriptions column={1} size="small" items={[
            {key:"primary",label:translate("主组"),children:account.primary_group || "—"},
            {key:"groups",label:translate("附属组"),children:<Space size={[0,4]} wrap>{(account.groups || []).map((name:string)=><Tag key={name}>{name}</Tag>)}</Space>},
            {key:"home",label:translate("主目录"),children:<Typography.Text code copyable={!!account.home}>{account.home || "—"}</Typography.Text>},
            {key:"data",label:translate("数据目录"),children:<Typography.Text code copyable={!!account.data_dir}>{account.data_dir || "—"}</Typography.Text>},
          ]} />
        </Card>
      </div>
      <Alert type="info" showIcon message={translate("私有主组：{name} · GID {gid}", { name: account.private_group || "—", gid: account.private_gid ?? "—" })} description={translate("私有主组只读，随账号生命周期保留；修改主组后原私有组仍保留。human 仅用于人员分类，不授予项目权限。")} />
      {account.recovery_required && account.creation?.status !== "incomplete" ? <Alert type="error" showIcon message={translate("账号变更尚未完成，请由服务器管理员核对目录和登录状态后恢复管理。")} /> : null}
      {account.status !== "active" && ((activity.data?.processes?.length || 0) + (activity.data?.sessions?.length || 0) + (activity.data?.scheduled?.length || 0) > 0) ? <Alert type="warning" showIcon message={translate("账号已限制新登录，但仍有活动；现有进程、会话和定时任务不会自动结束。")} /> : null}
      <UserTaskPolicy account={account}/>
      <Card title={translate("账号限制记录")}>
        {Object.keys(account.lifecycle || {}).length ? <Table<Row> size="small" pagination={false} rowKey="kind" scroll={{x:560}} dataSource={Object.entries(account.lifecycle || {}).map(([kind,entry])=>({kind,...entry as Row}))} columns={[
          {title:translate("限制"),dataIndex:"kind",render:v=>translate(({disabled:"停用",deleted:"软删除",expiry:"有效期"} as Row)[v] || v)},
          {title:translate("状态"),dataIndex:"active",render:v=>translate(v?"已生效":"未生效")},
          {title:translate("时间"),dataIndex:"at",render:v=>v?date(v):translate("历史记录未知")},
          {title:translate("操作原因"),dataIndex:"reason",render:v=>v || translate("历史记录未知")},
        ]}/> : <Typography.Text type="secondary">{translate("历史记录未知")}</Typography.Text>}
        {account.creation ? <Descriptions size="small" column={1} items={[
          {key:"stage",label:translate("创建阶段"),children:<span title={account.creation.stage}>{creationStageLabel(account.creation.stage)}</span>},
          {key:"error",label:translate("最近错误代码"),children:account.creation.error_code || "—"},
        ]}/> : null}
      </Card>
      <Card title={translate("登录安全")}>
      <Descriptions column={{xs:1,sm:2}} size="small" items={[
        {key:"password",label:translate("首次登录改密"),children:translate(account.require_password_change ? "是" : "否")},
        {key:"keys",label:translate("SSH 公钥数量"),children:account.public_keys?.length ?? "—"},
        {key:"policy",label:translate("登录策略生效状态"),children:<Status value={account.login_policy_status}/>},
        {key:"lastlogin",label:translate("最近确认登录"),children:account.last_success_login ? <><span>{date(account.last_success_login.time)}</span> · <span>{account.last_success_login.ip}</span> · {account.last_success_login.method}</> : translate("暂无已确认的登录记录")},
        {key:"coverage",label:translate("登录记录覆盖"),children:translate(account.login_coverage || "仅覆盖已采集的 SSH 日志，未记录不代表从未登录。")},
      ]} />
      <Space wrap className="filters">
        <Button
          disabled={!host.writable || immutable}
          onClick={() => setEditing("password")}
        >
          {translate("重置密码")}
        </Button>
        <Button
          disabled={!host.writable || immutable}
          onClick={() => setEditing("expiry")}
        >
          {translate("有效期")}
        </Button>
        <Button
          disabled={!host.writable || immutable}
          onClick={() => setEditing("password-policy")}
        >
          {translate("密码策略")}
        </Button>
        <Link
          to={`/login-events?username=${encodeURIComponent(account.username)}`}
        >
          {translate("登录历史")}
        </Link>
      </Space>
      </Card>
      <Card title={translate("活动与存储")}>
      <Tabs
        items={[
          {
            key: "activity",
            label: translate("活动与扫描覆盖"),
            children: (
              <>
                <ErrorAlert error={activity.error} />
                <div className="account-activity-stats">
                  <Statistic title={translate("进程")} value={activity.data?.processes?.length ?? "—"} />
                  <Statistic title={translate("登录会话")} value={activity.data?.sessions?.length ?? "—"} />
                  <Statistic title={translate("定时任务")} value={activity.data?.scheduled?.length ?? "—"} />
                </div>
                {([['processes','进程'],['sessions','登录会话'],['scheduled','定时任务']] as const).map(([kind,title])=><div key={kind}>
                  <Typography.Title level={5}>{translate(title)}</Typography.Title>
                  {activity.data?.[kind]?.length ? <Table<Row> size="small" pagination={{pageSize:5,hideOnSinglePage:true}} rowKey="_key" scroll={{x:560}} dataSource={(activity.data?.[kind] || []).map((row:Row,index:number)=>({...row,_key:String(row.pid ?? row.id ?? index)}))} columns={kind === 'processes' ? [
                    {title:'PID',dataIndex:'pid',width:100},{title:translate('命令'),render:(_,r)=><CompactText value={r.command || r.name || r.cmdline}/>},{title:translate('状态'),dataIndex:'status',render:v=><Status value={v}/>},
                  ] : kind === 'sessions' ? [
                    {title:translate('终端'),render:(_,r)=><CompactText value={r.terminal || r.tty}/>},{title:translate('来源'),render:(_,r)=><CompactText value={r.host || r.ip}/>},{title:translate('时间'),render:(_,r)=>date(typeof r.started === "number" ? new Date(r.started * 1000).toISOString() : r.started || r.time)},
                  ] : [{title:translate('类型'),dataIndex:'kind'},{title:translate('内容'),dataIndex:'line',render:v=><CompactText value={v}/>}]} /> : <Typography.Text type="secondary">{activity.isPending ? translate('等待中') : translate('暂无记录')}</Typography.Text>}
                </div>)}
                <Descriptions title={translate("扫描覆盖")} size="small" column={1} items={Object.entries(typeof activity.data?.coverage === 'object' ? activity.data.coverage : {coverage:activity.data?.coverage}).map(([key,value])=>({key,label:translate(key),children:<CompactText value={value}/>}))}/>
                <Collapse ghost items={[{key:"activity",label:translate("查看活动与扫描详情"),children:<JsonView value={activity.data} />}]} />
              </>
            ),
          },
          {
            key: "storage",
            label: translate("个人目录用量"),
            children: (
              <>
                <ErrorAlert error={storage.error} />
                <DirectoryRefresh/>
                <Descriptions title={translate("个人目录用量")} size="small" column={{xs:1,sm:2}} items={(() => { const usage=(storage.data?.users || []).find((r:Row)=>r.account_id===account.id) || {};return [
                  {key:"home",label:translate("主目录"),children:bytes(usage.home_bytes)}, {key:"data",label:translate("数据目录"),children:bytes(usage.data_bytes)},
                  {key:"time",label:translate("采样时间"),children:date(usage.collected_at)},
                ];})()}/>

              </>
            ),
          },
        ]}
      />
      </Card>
      <Collapse items={[{key:"raw",label:translate("原始账号信息"),children:<RecordDetail row={account} />}]} />
      {editing ? (
        <EditDialog
          disabledReason={!host.writable ? host.reason : undefined}
          title={
            editing === "password"
                ? translate("重置账号密码")
                : editing === "expiry"
                  ? translate("账号有效期")
                  : translate("密码策略")
          }
          fields={
            editing === "password"
                ? [
                    {
                      name: "password",
                      label: translate("新密码"),
                      type: "password",
                      required: true,
                    },
                    {
                      name: "require_password_change",
                      label: translate("首次登录改密"),
                      type: "switch",
                    },
                  ]
                : editing === "expiry"
                  ? [
                      {
                        name: "expires_on",
                        label: translate("到期日期 · Asia/Shanghai（留空取消）"),
                        type: "date",
                      },
                    ]
                  : [
                      {
                        name: "require_password_change",
                        label: translate("首次登录要求修改密码"),
                        type: "switch",
                      },
                    ]
          }
          initial={
            policyDraft || (editing === "password"
              ? { require_password_change: true, revision: account.revision }
              : account)
          }
          onClose={() => {setEditing(null);setPolicyDraft(null);}}
          onSave={async (v) => {
            setPolicyChange({kind: editing!, values: v});
          }}
        />
      ) : null}
      {policyChange ? <PreviewDialog title={translate("账号登录策略变更预览")} previewPath={`/system-users/${account.id}/change-preview`} previewBody={{action:"update", revision:policyChange.values.revision, changes:Object.fromEntries(Object.entries(policyChange.values).filter(([k]) => !["password","revision","token"].includes(k)))}} executePath={`/system-users/${account.id}/${policyChange.kind}`} executeBody={policyChange.values} method={policyChange.kind === "password" ? "POST" : "PATCH"} warning={translate("密码仅用于本次提交，不保存在预览或审计中。账号限制独立生效；请核对改密与有效期影响。")} onEdit={async()=>{const fresh=await detail.refetch({throwOnError:true});if(!fresh.data) throw new Error(translate("目标已不存在，请关闭窗口并刷新列表。"));setPolicyDraft({...policyChange.values,revision:fresh.data.revision});setEditing(policyChange.kind as "password" | "expiry" | "password-policy");setPolicyChange(null);}} onClose={() => setPolicyChange(null)} /> : null}
      <ErrorAlert error={save.error} />
    </div>
  );
}
export function SystemGroups() {
  useI18n();
  const host = useHostMutations();
  const [scope, setScope] = useState("managed");
  const [search, setSearch] = useState("");
  const q = useData(`/system-groups?scope=${scope}`);
  const users = useData("/system-users?state=active&scope=human");
  const [edit, setEdit] = useState<Row | null>(null);
  const [detail,setDetail] = useState<Row | null>(null);
  const [action, setAction] = useState<Row | null>(null);
  const save = useSave();
  const fields: Field[] = [
    { name: "name", label: translate("权限组名"), required: true },
    ...(!edit?.id || edit?._reviewMembers ? [{
      name: "members",
      label: translate("附属组成员"),
      type: "multiple" as const,
      options: [...new Set([...(users.data || []).filter((u: Row) => u.managed && u.is_human && !u.protected && u.status === "active").map((u: Row) => u.username), ...(edit?.members || [])])].map(name => ({ label: String(name), value: name })),
      disabled: users.isPending || !!users.error,
      help: translate("仅可添加正常受管人员账号；保留已有成员。不改变用户主组，权限变更后需要重新登录。"),
    }] : []),
  ];
  return (
    <>
      <PageHead
        title={translate("系统用户组")}
        description={translate("受管普通权限组用于文件与项目授权。human 仅用于人员分类，不授予项目权限；私有主组在账号详情中只读展示并随账号生命周期保留。移除成员后需要重新登录。")}
        action={
          <Button disabled={!host.writable} type="primary" onClick={() => setEdit({ members: [] })}>
            {translate("创建普通权限组")}
          </Button>
        }
      />
      {!host.writable ? <Alert showIcon type="warning" message={host.reason}/> : null}
      {host.health?.root_readiness?.ready === false ? <Alert showIcon type="warning" message={translate(errorGuidance.initialization_unverified)}/> : null}
      <ErrorAlert error={q.error || users.error || save.error} />
      <Alert type="info" showIcon message={<>{translate("共享目录内部组由共享授权维护，请前往团队共享目录修改成员权限。")} <Link to="/shares">{translate("团队共享目录")}</Link></>} />
      <Alert type="info" showIcon message={translate(scope === "managed" ? "可创建普通权限组，或在其他组中启用已有普通组的管理。" : "启用管理仅登记普通权限组，不自动修改原生成员或权限。受管但只读的组需先在账号页面启用相关人员账号管理。")} />
      <Card>
        <Space wrap className="filters">
          <Select aria-label={translate("权限组范围")} value={scope} onChange={setScope} options={[{label:translate("受管权限组"),value:"managed"},{label:translate("其他组（只读）"),value:"other"}]} />
          <Input aria-label={translate("搜索权限组")} placeholder={translate("搜索权限组")} value={search} onChange={event => setSearch(event.target.value)} allowClear />
        </Space>
        <Table<Row>
          scroll={{ x: 1330 }}
          size="small"
          tableLayout="fixed"
          rowKey="id"
          loading={q.isPending}
          dataSource={(q.data || []).filter((r: Row) => r.name.toLowerCase().includes(search.toLowerCase()))}
          columns={[
            { title: translate("组名"), dataIndex: "name", width: 150, render: (v,r) => <Button type="link" className="table-link" onClick={()=>setDetail(r)}><CompactText value={v}/></Button> },
            { title: "GID", dataIndex: "gid", width: 100 },
            { title: translate("类型"), width: 150, render: (_, r) => <Tag><TermLabel label={({share_internal:"共享目录内部授权",permission:"普通权限组",private:"私有主组",system:"系统组",platform:"人员分类组"} as Record<string,string>)[r.kind] || "系统组"} /></Tag> },
            {
              title: translate("附属组成员"),
              width: 240,
              dataIndex: "members",
              render: (v) => <CompactText value={v?.join(", ")} />,
            },
            { title: translate("主组账号"), width: 160, render: (_, r) => <CompactText value={r.primary_users?.join(", ")} /> },
            { title: translate("共享项目引用"), width: 160, render: (_, r) => <CompactText value={r.share_refs?.join(", ")} /> },
            {
              title: translate("管理状态"),
              width: 140,
              render: (_, r) => (
                <Space wrap>
                  {r.protected ? <Tag>{translate("保护")}</Tag> : null}
                  {r.managed ? <Tag>{translate("受管")}</Tag> : null}
                  {r.assignable !== true ? <Tag>{translate("只读")}</Tag> : null}
                </Space>
              ),
            },
            {
              title: translate("操作"),
              width: 230,
              fixed: "right",
              render: (_, r) => r.assignable !== true ? (
                r.can_adopt ? <Button disabled={!host.writable} size="small" onClick={() => setAction({ ...r, action: "update", changes: { managed: true } })}>{translate("启用管理")}</Button> : <Typography.Text type="secondary">{translate("只读")}</Typography.Text>
              ) : (
                <Space>
                  <Button size="small" onClick={()=>setDetail(r)}>{translate("成员")}</Button>
                  <Button
                    size="small"
                    disabled={!host.writable || r.assignable !== true || r.recovery_required || !!r.readonly_reasons?.length}
                    onClick={() => setEdit(r)}
                  >
                    {translate("编辑")}
                  </Button>
                  <Tooltip title={r.members?.length || r.primary_users?.length || r.share_refs?.length ? translate("仍有成员、主组账号或共享项目引用，无法删除。") : r.assignable !== true ? translate("只读组不可删除。") : undefined}>
                  <Button
                    size="small"
                    danger
                    disabled={!host.writable || r.assignable !== true || r.recovery_required || !!r.members?.length || !!r.primary_users?.length || !!r.share_refs?.length}
                    onClick={() =>
                      setAction({ ...r, action: "delete", changes: {} })
                    }
                  >
                    {translate("删除空组")}
                  </Button>
                  </Tooltip>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      {detail && !action ? <SystemGroupMembers group={q.data?.find((g:Row)=>g.id===detail.id) || detail} accounts={users.data || []} writable={host.writable && !q.isPending && !q.error && !users.isPending && !users.error} onClose={()=>setDetail(null)} onChange={setAction}/> : null}
      {edit ? (
        <EditDialog
          disabledReason={!host.writable ? host.reason : edit.id && (edit.assignable !== true || edit.recovery_required || edit.readonly_reasons?.length) ? translate("当前组只读，无法修改成员。") : undefined}
          title={edit.id ? translate("修改权限组") : translate("创建普通权限组")}
          initial={edit}
          fields={edit._reviewMembers ? fields.filter(f=>f.name === "members") : fields}
          onClose={() => setEdit(null)}
          onSave={async (v) => {
            if (edit.id) setAction({ ...edit, action: "update", changes: edit._reviewMembers ? {members:v.members} : { name: v.name } });
            else
              await save.mutateAsync({
                path: "/system-groups",
                method: "POST",
                body: v,
              });
          }}
        >{edit._review ? <Alert showIcon type="warning" message={translate("已刷新服务器状态并保留草稿，请核对当前成员与拟保存成员后再预览。")} description={<>{translate("当前成员")}：{(edit._currentMembers || []).join(", ") || "—"}</>} /> : null}</EditDialog>
      ) : null}
      {action ? (
        <PreviewDialog
          title={translate(action.changes.managed ? "启用权限组管理" : "权限组变更预览")}
          previewPath={`/system-groups/${action.id}/change-preview`}
          previewBody={{
            action: action.action,
            revision: action.revision,
            changes: action.changes,
          }}
          executePath={`/system-groups/${action.id}`}
          method={action.action === "delete" ? "DELETE" : "PATCH"}
          executeBody={{ ...action.changes, revision: action.revision }}
          onEdit={async () => {
            const refreshed = await q.refetch({throwOnError:true});
            await users.refetch({throwOnError:true});
            const current = refreshed.data?.find((g:Row)=>g.id === action.id);
            if (!current) throw new Error(translate("目标已不存在，请关闭窗口并刷新列表。"));
            if (action.action === "update" && !action.changes.managed) {
              setDetail(null);
              setEdit({...current,...action.changes,_review:true,_reviewMembers:action.changes.members !== undefined,_currentMembers:current.members});
            } else setDetail(current);
            setAction(null);
          }}
          onClose={() => setAction(null)}
          warning={translate(action.action === "delete" ? "删除组不会删除文件，但遗留文件可能仍引用此 GID。请先核对目录权限；平台不扫描全部文件。" : "服务器检查保护状态、成员及主组引用。权限撤销不会自动结束已有会话。")}
        />
      ) : null}
    </>
  );
}
function DirectoryRefresh() {
  const q = useData("/storage", true);
  const refresh = useSave();
  const scanning = q.data?.scanning || refresh.isPending;
  return <div className="storage-toolbar" style={{marginTop:16}}>
    <Space wrap><Button loading={scanning} disabled={scanning || !q.data} onClick={()=>refresh.mutate({path:"/storage/refresh",method:"POST"})}>{translate(scanning ? "正在统计目录用量" : "刷新目录用量")}</Button>
      <Typography.Text type="secondary" role="status">{translate("上次目录统计：")}{date(q.data?.directory_collected_at)}</Typography.Text>
    </Space>
    <div><Typography.Text type="secondary">{translate("仅手动统计目录用量；小文件较多时可能耗时并增加磁盘 I/O，建议空闲时刷新。")} {translate("显示实际磁盘占用，硬链接不重复计算；已有缓存需手动刷新后更新。")}</Typography.Text></div>
    <ErrorAlert error={refresh.error || q.error || q.data?.scan_error}/>
  </div>;
}
export function Storage() {
  useI18n();
  const q = useData("/storage", true);
  const d = q.data;
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("current");
  const users = (d?.users || []).filter((r: Row) => r.username?.toLowerCase().includes(search.trim().toLowerCase()) && (scope === "all" || (scope === "deleted" ? !!r.deleted_at || r.account_status === "deleted" : !r.deleted_at && r.account_status !== "deleted")));
  const percent = (used: number, total: number) => total > 0 ? Math.max(0, Math.min(100, Math.round(used / total * 1000) / 10)) : 0;
  const acl = d?.capabilities?.acl;
  const freshness = d?.status === "pending" ? translate("正在统计存储用量，完成后自动更新。") : `${translate("采样：")}${date(d?.collected_at)}${d?.stale ? translate(" · 数据已过期") : ""}`;
  const alertTarget = (r: Row) => r.scope === "user_directory" ? `${d?.users?.find((u: Row) => String(u.account_id) === r.target.split(":")[0])?.username || r.target} · ${translate(r.target.endsWith(":home") ? "主目录" : "数据目录")}` : r.scope === "share" ? d?.shares?.find((s:Row)=>s.id===r.target)?.name || r.target : r.target;
  return <>
    <PageHead title={translate("存储与容量")} description={translate("容量告警只提醒，不限制写入。个人与共享目录用量分别统计，请勿重复相加。")}/>
    <ErrorAlert error={q.error}/>
    {!d ? <Card loading={q.isPending}/> : <>
      <Space wrap className="storage-toolbar"><Typography.Text type={d.stale ? "warning" : "secondary"} role="status">{freshness}</Typography.Text><Tag color={acl?.status === 'verified' ? 'green' : 'gold'}>{translate(acl?.status === 'verified' ? '共享权限已验证' : acl?.status === 'requires_attention' ? '共享权限需检查' : acl?.status === 'unavailable' ? '共享权限工具不可用' : '共享权限尚未验证')}</Tag></Space>
      <GridRow gutter={[16,16]} className="storage-capacity">
        {(d.filesystems || []).map((fs:Row)=><Col xs={24} xl={d.filesystems.length === 1 ? 24 : 12} key={fs.id}><Card title={<Space><CompactText value={fs.path}/><Tag>{fs.fstype}</Tag></Space>}>
          <GridRow gutter={16}><Col span={12}><Statistic title={translate("可用空间")} value={bytes(fs.available)}/></Col><Col span={12}><Statistic title={translate("总容量")} value={bytes(fs.total)}/></Col></GridRow>
          <div className="storage-meter"><Typography.Text>{translate("空间使用率")}</Typography.Text>{typeof fs.available === 'number' && fs.total > 0 ? <Progress percent={percent(fs.total-fs.available,fs.total)} status={d.alerts?.some((a:Row)=>a.scope==='filesystem' && a.target===fs.id && a.metric==='bytes' && a.severity==='critical')?'exception':'normal'}/> : <Typography.Text type="secondary">{translate("尚无统计数据")}</Typography.Text>}</div>
          <Typography.Text type="secondary">{translate("inode 使用率")}：{typeof fs.available_inodes==='number' && fs.total_inodes > 0 ? `${percent(fs.total_inodes-fs.available_inodes,fs.total_inodes)}%` : '—'}</Typography.Text>
          {fs.error ? <ErrorAlert error={fs.error}/> : null}
        </Card></Col>)}
      </GridRow>
      {!d.filesystems?.length && d.status !== 'pending' ? <Card className="section-card"><Empty description={translate("尚无文件系统统计，请检查服务器采样状态。")}/></Card> : null}
      {d.alerts?.length ? <Card className="section-card" title={translate("容量告警")}><Table<Row> size="small" rowKey="id" dataSource={d.alerts} pagination={{pageSize:5,hideOnSinglePage:true}} scroll={{x:560}} columns={[
        {title:translate("级别"),dataIndex:"severity",width:90,render:v=><Tag color={v==='critical'?'red':'gold'}>{translate(v==='critical'?'严重':'提醒')}</Tag>},
        {title:translate("对象"),render:(_,r)=><CompactText value={alertTarget(r)}/>},
        {title:translate("指标"),dataIndex:"metric",width:100,render:v=>translate(v==='inodes'?'文件数 / inode':'存储空间')},
        {title:translate("占所在文件系统比例"),dataIndex:"percent",width:170,render:v=>`${v}%`},
      ]}/><Typography.Text type="secondary">{translate("请检查占用较高的目录，按需归档或清理；平台不会自动删除文件。")}</Typography.Text></Card> : null}
      <DirectoryRefresh/>
      <Card title={translate("个人目录用量")} className="section-card">
        <Space wrap className="filters"><Input allowClear aria-label={translate("搜索用户")} placeholder={translate("搜索用户")} value={search} onChange={e=>setSearch(e.target.value)} style={{width:220}}/><Select aria-label={translate("账号范围")} value={scope} onChange={setScope} options={[{value:'all',label:translate('全部账号（含保留数据）')},{value:'current',label:translate('未软删除账号')},{value:'deleted',label:translate('已软删除账号')}]} style={{minWidth:200}}/></Space>
        <Table<Row> size="small" rowKey="account_id" dataSource={users} scroll={{x:850}} pagination={{pageSize:10,hideOnSinglePage:true}} columns={[
          {title:translate("用户"),dataIndex:"username",width:190,sorter:(a,b)=>String(a.username).localeCompare(String(b.username)),render:(v,r)=><Link to={`/accounts/${encodeURIComponent(r.account_id)}`}><CompactText value={v}/></Link>},
          {title:translate("账号状态"),width:120,render:(_,r)=><Status value={r.deleted_at?'deleted':r.account_status || 'unknown'}/>},
          {title:translate("主目录"),dataIndex:"home_bytes",width:120,render:bytes,sorter:(a,b)=>(a.home_bytes??-1)-(b.home_bytes??-1)},
          {title:translate("数据目录"),dataIndex:"data_bytes",width:120,defaultSortOrder:'descend',render:bytes,sorter:(a,b)=>(a.data_bytes??-1)-(b.data_bytes??-1)},
          {title:translate("统计状态"),dataIndex:"status",width:120,render:v=><Status value={v}/>},
          {title:translate("采样时间"),dataIndex:"collected_at",width:150,render:compactDate},
        ]}/>
      </Card>
      <Card title={translate("共享目录用量")} className="section-card"><Table<Row> size="small" rowKey="id" dataSource={d.shares || []} scroll={{x:650}} pagination={{pageSize:10,hideOnSinglePage:true}} columns={[
        {title:translate("项目"),dataIndex:"name",render:v=><Link to="/shares"><CompactText value={v}/></Link>},
        {title:translate("用量"),dataIndex:"usage_bytes",width:120,render:bytes,sorter:(a,b)=>(a.usage_bytes??-1)-(b.usage_bytes??-1)},
        {title:translate("统计状态"),dataIndex:"usage_status",width:120,render:v=><Status value={v||'pending'}/>},
        {title:translate("采样时间"),render:(_,r)=>date(r.collected_at)},
      ]}/></Card>
      <Collapse ghost items={[{key:'diagnostics',label:translate('存储诊断详情'),children:<JsonView value={{capabilities:d.capabilities,filesystems:d.filesystems}}/>}]}/>
    </>}
  </>;
}
export function Shares() {
  useI18n();
  const host = useHostMutations();
  const q = useData("/shares", true);
  const accounts = useData("/system-users?scope=human&state=all");
  const settings = useData("/settings");
  const [search, setSearch] = useState("");
  const [viewId, setViewId] = useState<string | null>(null);
  const viewing = q.data?.find((r: Row) => r.id === viewId);
  const [edit, setEdit] = useState<Row | null>(null);
  const [action, setAction] = useState<Row | null>(null);
  const save = useSave();
  const accessMembers = (r: Row) => <div aria-label={translate("项目访问成员")}>
    {r.status === "access_recheck_required" ? <Alert type="warning" showIcon message={translate("授权变更未完成，请重新预览并应用成员权限。")}/> : null}
    {r.members == null ? <Alert type="error" showIcon message={translate("成员信息不可用")}/> : <Table<Row> size="small" rowKey="username" dataSource={r.members} pagination={{pageSize:10,hideOnSinglePage:true}} columns={[
      {title:translate("用户"),dataIndex:"username",render:v=><CompactText value={v}/>},
      {title:translate("权限"),dataIndex:"permission",render:v=><Tag color={v==='write'?'blue':undefined}>{translate(v==='write'?'读写':'只读')}</Tag>},
    ]}/>}
    <Descriptions size="small" column={1} items={[
      {key:'path',label:translate('共享路径'),children:<Typography.Text copyable>{r.path}</Typography.Text>},
      {key:'notes',label:translate('备注'),children:r.notes || '—'},
    ]}/>
    {r.access_mode !== 'members' ? <Typography.Paragraph type="secondary">{translate("旧授权已按成员展示；首次修改成员时切换为独立授权，确认前可预览变化。")}</Typography.Paragraph> : null}
  </div>;
  return (
    <>
      <PageHead
        title={translate("团队共享目录")}
        description={translate("直接为成员设置只读或读写权限，共享目录与个人私有目录隔离。")}
        action={
          <Button disabled={!host.writable || host.health?.root_readiness?.ready === false || accounts.isPending || !!accounts.error} type="primary" onClick={() => setEdit({})}>
            {translate("创建共享项目")}
          </Button>
        }
      />
      <Alert
        type="warning"
        showIcon
        message={translate("成员权限对新登录生效，已有会话可能保留访问能力。权限用于共享入口及新建内容，已有文件的单独权限保持不变。")}
      />
      {!host.writable ? <Alert showIcon type="warning" message={host.reason}/> : null}
      {host.health?.root_readiness?.ready === false ? <Alert showIcon type="warning" message={translate(errorGuidance.initialization_unverified)}/> : null}
      <ErrorAlert error={q.error || accounts.error || save.error} />
      <DirectoryRefresh/>
      <Card className="section-card">
        <Space wrap className="filters"><Input aria-label={translate("搜索共享项目")} placeholder={translate("搜索项目、路径或成员")} allowClear value={search} onChange={e=>setSearch(e.target.value)} style={{width:280,maxWidth:'100%'}}/><Typography.Text type="secondary">{translate("共享根目录")}：{settings.data?.share_base || '—'}</Typography.Text></Space>
        <Table<Row>
          scroll={{ x: 950 }}
          size="small"
          tableLayout="fixed"
          rowKey="id"
          loading={q.isPending}
          dataSource={(q.data || []).filter((r:Row)=>[r.name,r.path,...(r.members || []).map((m:Row)=>m.username)].some(v=>String(v || '').toLowerCase().includes(search.trim().toLowerCase())))}
          pagination={{pageSize:10,hideOnSinglePage:true}}
          columns={[
            { title: translate("项目"), dataIndex: "name", width: 140, render: (v,r) => <Button type="link" size="small" style={{width:"100%",minWidth:0,paddingInline:0,justifyContent:"flex-start"}} onClick={()=>setViewId(r.id)}><CompactText value={v}/></Button> },
            { title: translate("路径"), dataIndex: "path", width: 220, render: (v) => <CompactText value={v} /> },
            {title:translate("成员权限"),width:180,render:(_,r)=>r.members == null ? translate("成员信息不可用") : <Space wrap><Tag>{translate("只读")} {r.members.filter((m:Row)=>m.permission==='read').length}</Tag><Tag color="blue">{translate("读写")} {r.members.filter((m:Row)=>m.permission==='write').length}</Tag></Space>},
            { title: translate("用量"), dataIndex: "usage_bytes", width: 120, render: (v,r)=><Space direction="vertical" size={0}><span>{bytes(r.collected_at ? v : null)}</span><Typography.Text type="secondary">{r.collected_at ? <>{compactDate(r.collected_at)}{r.usage_stale ? ` · ${translate("数据已过期")}` : ""}</> : translate("尚无采样时间")}</Typography.Text></Space> },
            {
              title: translate("权限 / 统计"),
              width: 120,
              dataIndex: "usage_status",
              render: (v,r) => <Space direction="vertical" size={0}><Status value={r.status}/><Status value={v || "pending"}/></Space>,
            },
            {
              title: translate("操作"),
              width: 170,
              fixed: "right",
              render: (_, r) => (
                <Space direction="vertical" size={4}><Button size="small" onClick={()=>setViewId(r.id)}>{translate("查看访问成员")}</Button><Button disabled={!host.writable || r.members == null} size="small" onClick={() => setEdit(r)}>
                  {translate("编辑授权")}
                </Button></Space>
              ),
            },
          ]}
        />
      </Card>
      {viewing ? <Modal open title={<Space wrap><span>{translate("项目访问成员")}</span><Typography.Text type="secondary">{viewing.name}</Typography.Text></Space>} width={650} centered onCancel={()=>setViewId(null)} footer={<Button onClick={()=>setViewId(null)}>{translate("关闭")}</Button>} styles={{body:{maxHeight:"calc(100dvh - 160px)",overflowY:"auto"}}} destroyOnHidden>
        {accessMembers(viewing)}
      </Modal> : null}
      {edit ? (
        <EditDialog
          disabledReason={!host.writable ? host.reason : undefined}
          title={edit.id ? translate("修改共享授权") : translate("创建共享项目")}
          initial={{...edit,members:edit.members || []}}
          fields={[
            { name: "name", label: translate("项目名"), required: true, disabled: !!edit.id, help: `${translate("创建位置")}：${settings.data?.share_base || "—"}/<${translate("项目名")}>` },
            notes,
          ]}
          onClose={() => setEdit(null)}
          onSave={async (v) => {
            const sameMembers = JSON.stringify(v.members) === JSON.stringify(edit._baselineMembers ?? edit.members);
            if (!sameMembers) {
              const invalid = (v.members || []).filter((m:Row)=>!canGrantShareAccess(accounts.data?.find((a:Row)=>a.username===m.username)));
              if (invalid.length) throw new Error(translate('以下成员不可授权：{names}。请移除这些成员后再保存。',{names:invalid.map((m:Row)=>m.username).join(', ')}));
            }
            const changes = edit.id ? {notes:v.notes, ...(sameMembers ? {} : {members:v.members})} : {name:v.name,notes:v.notes,members:v.members || []};
            setAction({ ...edit, changes });
            setEdit(null);
          }}
        >{edit._review ? <Alert showIcon type="warning" message={translate("已刷新服务器状态并保留草稿，请核对当前成员与拟保存成员后再预览。")} description={<>{translate("当前成员")}：{(edit._baselineMembers || []).map((m:Row)=>`${m.username} (${translate(m.permission === "write" ? "读写" : "只读")})`).join(", ") || "—"}</>} /> : null}<Form.Item name="members" label={translate("成员权限")}><ShareMemberEditor accounts={accounts.data || []}/></Form.Item></EditDialog>
      ) : null}
      {action ? (
        <PreviewDialog
          title={translate("共享授权变更预览")}
          previewPath={action.id ? `/shares/${action.id}/change-preview` : "/shares/change-preview"}
          previewBody={action.id ? { revision: action.revision, changes: action.changes } : {action:"create",changes:action.changes}}
          executePath={action.id ? `/shares/${action.id}` : "/shares"}
          executeBody={action.id ? {...action.changes, revision:action.revision} : action.changes}
          method={action.id ? "PATCH" : "POST"}
          onEdit={async () => {
            const refreshed = await q.refetch({throwOnError:true});
            await accounts.refetch({throwOnError:true});
            const current = action.id ? refreshed.data?.find((r:Row)=>r.id === action.id) : {};
            if (!current) throw new Error(translate("目标已不存在，请关闭窗口并刷新列表。"));
            if (action.id && current.members == null) throw new Error(translate("成员信息不可用"));
            setEdit({...current,...action.changes,_baselineMembers:current.members || [],_review:true});
            setAction(null);
          }}
          onClose={() => setAction(null)}
        />
      ) : null}
    </>
  );
}
export function Settings() {
  useI18n();
  const host = useHostMutations();
  const q = useData("/settings");
  const save = useSave();
  const [edit, setEdit] = useState(false);
  const labels: Record<string, string> = {
    default_max_runtime_seconds: "默认最大运行时间",
    default_task_protected: "默认任务保护",
    default_task_priority: "默认任务优先级",
    default_deadline_action: "默认到期动作",
    default_orphan_reminder: "默认残留提醒",
    default_orphan_wait_seconds: "默认残留等待时间",
    scan_interval_seconds: "GPU 扫描周期",
    term_grace_seconds: "终止等待时间",
    storage_scan_interval_seconds: "磁盘容量采集周期",
    warning_percent: "容量提醒阈值",
    critical_percent: "容量严重阈值",
    ignored_task_executables: "忽略程序路径",
  };
  const groups = [
    { title: "新任务默认策略", names: ["default_max_runtime_seconds", "default_task_protected", "default_task_priority", "default_deadline_action", "default_orphan_reminder", "default_orphan_wait_seconds"] },
    { title: "扫描与运行策略", names: ["scan_interval_seconds", "term_grace_seconds", "storage_scan_interval_seconds"] },
    { title: "存储告警阈值", names: ["warning_percent", "critical_percent"] },
    { title: "任务监控白名单", names: ["ignored_task_executables"] },
  ];
  const roots = [
    { name: "home_base", label: "主目录根路径", description: "新账号的主目录根路径，由宿主机初始化配置。" },
    { name: "data_base", label: "数据目录根路径", description: "个人数据目录根路径，由宿主机初始化配置。" },
    { name: "share_base", label: "共享目录根路径", description: "团队共享目录根路径，由宿主机初始化配置。" },
    { name: "mode", label: "运行模式", description: "宿主机模式操作真实系统；演示模式使用模拟数据。" },
  ];
  const fields: Field[] = Object.entries(labels).map(([name, label]) => ({
    name,
    label,
    type: name === "ignored_task_executables" ? "tags" : ["default_task_protected", "default_orphan_reminder"].includes(name) ? "switch" : name === "default_deadline_action" ? "select" : ["default_max_runtime_seconds", "default_orphan_wait_seconds"].includes(name) ? "duration" : "number",
    required: !["ignored_task_executables", "default_max_runtime_seconds", "default_task_protected", "default_orphan_reminder"].includes(name),
    min: name === "default_task_priority" ? 0 : name === "storage_scan_interval_seconds" ? 60 : name === "critical_percent" ? 2 : 1,
    max: ({ default_orphan_wait_seconds: 86400, default_task_priority: 100, scan_interval_seconds: 300, term_grace_seconds: 120, storage_scan_interval_seconds: 86400 } as Record<string, number>)[name] ?? (name === "warning_percent" ? 99 : name === "critical_percent" ? 100 : undefined),
    help: name === "ignored_task_executables" ? "按完整程序路径精确匹配，立即用于已有和新任务；不监控或终止匹配程序，GPU总占用仍统计。留空表示不排除。" : name === "default_max_runtime_seconds" ? "从任务启动时刻计算；留空或点击“不限时”可取消时限" : name === "default_task_protected" ? "保护任务超时只提醒，不自动终止；系统与维护任务的保护仍生效。" : name === "default_orphan_reminder" ? "主进程退出后等待提醒；残留进程仅由管理员预览确认后终止" : ["scan_interval_seconds", "term_grace_seconds", "storage_scan_interval_seconds"].includes(name) ? "单位：秒" : name.endsWith("percent") ? "单位：百分比" : undefined,
    options: name === "default_deadline_action" ? [
      { label: translate("仅提醒"), value: "notify" },
      { label: translate("自动终止"), value: "terminate" },
    ] : undefined,
  }));
  return (
    <>
      <PageHead
        title={translate("策略与初始化配置")}
        description={translate("目录根与运行模式只读。路径、挂载、权限和密码/PAM 能力由宿主机服务验证。")}
        action={
          <Button
            type="primary"
            disabled={!q.data}
            onClick={() => setEdit(true)}
          >
            {translate("编辑策略")}
          </Button>
        }
      />
      {!host.writable ? <Alert showIcon type="warning" message={host.reason}/> : null}
      {host.health?.root_readiness?.ready === false ? <Alert showIcon type="warning" message={translate(errorGuidance.initialization_unverified)}/> : null}
      <ErrorAlert error={q.error || save.error} />
      <Card loading={q.isPending}>
        {q.data ? (
          <Space direction="vertical" size="large" style={{ width: "100%" }}>
            <Typography.Text type="secondary">{translate("默认策略仅用于新发现的任务，时限从进程启动时刻计算。修改不覆盖现有任务策略；系统与维护任务的保护仍生效。")}</Typography.Text>
            {groups.map(({ title, names }) => (
              <Descriptions key={title} title={translate(title)} className="record-detail" layout="vertical" column={{ xs: 1, sm: 2, lg: 3 }} size="small">
                {names.map((name) => (
                  <Descriptions.Item key={name} label={<TermLabel label={labels[name]} />}>
                    {name === "ignored_task_executables" ? <Space direction="vertical" size={4}><Space wrap>{q.data[name]?.length ? q.data[name].map((path: string) => <Tag key={path}><CompactText value={path} /></Tag>) : translate("未配置")}</Space><Typography.Text type="secondary">{translate("按完整程序路径精确匹配，立即用于已有和新任务；不监控或终止匹配程序，GPU总占用仍统计。留空表示不排除。")}</Typography.Text></Space> : name === "default_task_protected" ? translate(q.data[name] ? "已保护" : "未保护")
                      : name === "default_orphan_reminder" ? translate(q.data[name] ? "已启用" : "已关闭")
                      : name === "default_deadline_action" ? statusLabel(q.data[name])
                      : ["default_max_runtime_seconds", "default_orphan_wait_seconds"].includes(name) ? q.data[name] == null ? translate("不限时") : preciseDuration(q.data[name])
                      : name.endsWith("seconds") ? translate("{seconds} 秒", { seconds: q.data[name] ?? "—" })
                      : name.endsWith("percent") ? `${q.data[name] ?? "—"}%` : q.data[name] ?? "—"}
                  </Descriptions.Item>
                ))}
              </Descriptions>
            ))}
            <Descriptions title={translate("初始化配置（只读）")} className="record-detail" layout="vertical" column={{ xs: 1, sm: 2, lg: 3 }} size="small">
              {roots.map(({ name, label, description }) => (
                <Descriptions.Item key={name} label={<TermLabel label={label} />}>
                  <Space direction="vertical" size={4} style={{ width: "100%" }}>
                    {name === "mode" ? statusLabel(q.data[name]) : <CompactText value={q.data[name]} />}
                    <Typography.Text type="secondary">{translate(description)} · {translate("只读")}</Typography.Text>
                  </Space>
                </Descriptions.Item>
              ))}
            </Descriptions>
          </Space>
        ) : null}
      </Card>
      <Alert
        className="section-card"
        type="info"
        showIcon
        message={translate("首次改密与 SSH/PAM 限制按账号管理。共享目录通过系统用户组和 ACL 控制访问，平台不设置磁盘容量限制。")}
      />
      {edit ? (
        <EditDialog
          title={translate("编辑全局策略")}
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
  useI18n();
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
        title={login ? translate("SSH 登录记录") : translate("操作审计")}
        description={
          login
            ? translate("只展示可确认的日志事实。缺失历史表示无覆盖，不代表没有登录。")
            : translate("记录管理员与自动策略操作、变更前后值及失败原因。")
        }
      />
      <Card>
        <Space wrap className="filters">
          {(login ? ["username", "ip"] : ["actor", "action"]).map((name) => (
            <Input
              key={name}
              placeholder={
                name === "username"
                  ? translate("用户名")
                  : name === "ip"
                    ? translate("来源 IP")
                    : name === "actor"
                      ? translate("操作人")
                      : translate("操作类型")
              }
              aria-label={translate(({ username: "用户名", ip: "来源 IP", actor: "操作人", action: "操作类型" } as Record<string, string>)[name])}
              value={filters[name]}
              onChange={(e) => set(name, e.target.value)}
            />
          ))}
          <Select
            aria-label={translate("结果筛选")}
            placeholder={translate("全部结果")}
            allowClear
            options={(login
              ? ["success", "failure"]
              : ["succeeded", "failed", "pending", "demo"]
            ).map((value) => ({ label: statusLabel(value), value }))}
            onChange={(v) => set("result", v)}
          />
          <Input
            type="datetime-local"
            aria-label={translate("起始时间")}
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
            aria-label={translate("结束时间")}
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
            <summary><span>{translate("日志扫描覆盖")}</span><Typography.Text type="secondary">{typeof q.data.coverage === "object" ? q.data.coverage?.status ? statusLabel(q.data.coverage.status) : translate("查看来源与历史覆盖") : q.data.coverage}</Typography.Text></summary>
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
                  { title: translate("时间"), dataIndex: "time", width: 140, render: compactDate },
                  { title: translate("用户名"), dataIndex: "username", width: 150, render: (v) => <CompactText value={v} /> },
                  { title: translate("来源 IP"), dataIndex: "ip", width: 150, render: (v) => <CompactText value={v} /> },
                  { title: translate("登录方式"), dataIndex: "method", width: 150, render: (v) => <CompactText value={v} /> },
                  {
                    title: translate("结果"),
                    width: 100,
                    dataIndex: "result",
                    render: (v) => <Status value={v} />,
                  },
                  { title: translate("公钥指纹"), dataIndex: "fingerprint", width: 240, render: (v) => <CompactText value={v} /> },
                ]
              : [
                  { title: translate("时间"), dataIndex: "time", width: 140, render: compactDate },
                  { title: translate("操作人"), dataIndex: "actor", width: 150, render: (v) => <CompactText value={v} /> },
                  { title: translate("操作"), dataIndex: "action", width: 180, render: (v) => <CompactText value={auditActions[v] ? translate(auditActions[v]) : v} /> },
                  {
                    title: translate("目标"),
                    width: 260,
                    dataIndex: "target",
                    render: (v) => <CompactText value={v} />,
                  },
                  {
                    title: translate("结果"),
                    width: 100,
                    dataIndex: "result",
                    render: (v) => <Status value={v} />,
                  },
                  { title: translate("原因"), dataIndex: "reason", width: 240, render: (v) => <CompactText value={v} /> },
                ]
          }
        />
      </Card>
    </>
  );
}
