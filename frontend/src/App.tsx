import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Layout,
  Menu,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import {
  DashboardOutlined,
  ClusterOutlined,
  TeamOutlined,
  UserOutlined,
  SettingOutlined,
  AuditOutlined,
  DatabaseOutlined,
  FolderOpenOutlined,
  LoginOutlined,
  LogoutOutlined,
} from "@ant-design/icons";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { api, queryClient, Session, setSession } from "./api";
import { ErrorAlert } from "./components";
import {
  Accounts,
  BusinessGroups,
  BusinessUsers,
  Logs,
  Overview,
  Settings,
  Shares,
  Storage,
  SystemGroups,
  TaskDetail,
  Tasks,
} from "./pages";
const menu = [
  { key: "/", label: "服务器总览", icon: <DashboardOutlined /> },
  { key: "/tasks", label: "GPU 任务", icon: <ClusterOutlined /> },
  { key: "/groups", label: "业务优先级组", icon: <TeamOutlined /> },
  { key: "/users", label: "用户业务策略", icon: <UserOutlined /> },
  { key: "/accounts", label: "Linux 本地账号", icon: <UserOutlined /> },
  { key: "/system-groups", label: "Linux 系统组", icon: <TeamOutlined /> },
  { key: "/storage", label: "存储与容量", icon: <DatabaseOutlined /> },
  { key: "/shares", label: "团队共享目录", icon: <FolderOpenOutlined /> },
  { key: "/login-events", label: "SSH 登录记录", icon: <LoginOutlined /> },
  { key: "/settings", label: "策略配置", icon: <SettingOutlined /> },
  { key: "/audit", label: "操作审计", icon: <AuditOutlined /> },
];
export default function App() {
  const [user, setUser] = useState<Session | null>(null);
  const [mode, setMode] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>();
  const [logoutBusy, setLogoutBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    let active = true;
    api<{mode:string}>("/health").then(value => { if (active) setMode(value.mode); }).catch(() => {});
    api<Session>("/auth/me")
      .then((value) => {
        if (active) {
          setSession(value);
          setUser(value);
        }
      })
      .catch((e) => {
        if (active && e.status !== 401) setError(e);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    const unauthorized = () => {
      setUser(null);
      setSession(null);
      queryClient.clear();
    };
    window.addEventListener("gpupm:unauthorized", unauthorized);
    return () => {
      active = false;
      window.removeEventListener("gpupm:unauthorized", unauthorized);
    };
  }, []);
  const login = async (values: { username: string; password: string }) => {
    setLoading(true);
    setError(undefined);
    try {
      const session = await api<Session>("/auth/login", "POST", values);
      setSession(session);
      setUser(session);
      queryClient.clear();
      navigate("/");
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  };
  const logout = async () => {
    setLogoutBusy(true);
    try {
      await api("/auth/logout", "POST", {});
      setSession(null);
      setUser(null);
      queryClient.clear();
      navigate("/");
    } catch (e) {
      setError(e);
    } finally {
      setLogoutBusy(false);
    }
  };
  if (loading && !user)
    return (
      <div className="screen-loading">
        <Spin size="large" tip="连接管理服务…" />
      </div>
    );
  if (!user)
    return (
      <div className="login-page">
        <div className="login-story">
          <span className="brand-mark">G</span>
          <Typography.Title>gpuPM</Typography.Title>
          <Typography.Title level={2}>
            训练照常运行，
            <br />
            管理清晰有序。
          </Typography.Title>
          <p>GPU 任务、业务优先级、账号与存储，在同一个管理入口。</p>
          <Space wrap>
            <Tag>进程身份核验</Tag>
            <Tag>操作范围预览</Tag>
            <Tag>审计留痕</Tag>
          </Space>
        </div>
        <Card className="login-card">
          <Typography.Title level={3}>管理员登录</Typography.Title>
          <Typography.Paragraph type="secondary">
            使用平台管理员凭据登录。Linux 账号密码与此独立。
          </Typography.Paragraph>
          <ErrorAlert error={error} />
          <Form layout="vertical" onFinish={login}>
            <Form.Item
              label="管理员账号"
              name="username"
              rules={[{ required: true, message: "请输入管理员账号" }]}
            >
              <Input autoComplete="username" size="large" />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password autoComplete="current-password" size="large" />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              block
              size="large"
              loading={loading}
            >
              登录管理平台
            </Button>
          </Form>
          <p className="login-foot">安全会话 · 服务端 CSRF 校验</p>
        </Card>
      </div>
    );
  const selected = location.pathname.startsWith("/tasks/")
    ? "/tasks"
    : location.pathname;
  return (
    <Layout className="app-layout">
      <Layout.Sider
        breakpoint="lg"
        collapsedWidth={64}
        width={238}
        className="sidebar"
      >
        <div className="brand">
          <span className="brand-mark">G</span>
          <div>
            gpuPM<small>SERVER CONTROL</small>
          </div>
        </div>
        <div className="sidebar-caption">服务器管理工作台</div>
        <Menu
          theme="dark"
          selectedKeys={[selected]}
          items={menu}
          onClick={({ key }) => navigate(key)}
        />
        <div className="sidebar-footer">
          业务优先级 ≠ 系统权限
          <br />
          单机管理 · 管理员入口
        </div>
      </Layout.Sider>
      <Layout>
        <Layout.Header className="topbar">
          <Space>
            <span className="status-dot" />
            管理控制台<Tag>Asia/Shanghai</Tag>
            <Tag color={mode === "demo" ? "orange" : "blue"}>{mode === "demo" ? "演示模式 · 不操作宿主机" : mode === "host" ? "宿主机模式" : "模式待核验"}</Tag>
          </Space>
          <Space>
            <Typography.Text>{user.username}</Typography.Text>
            <Button
              icon={<LogoutOutlined />}
              loading={logoutBusy}
              onClick={logout}
            >
              退出
            </Button>
          </Space>
        </Layout.Header>
        <Layout.Content className="content">
          <ErrorAlert error={error} />
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/tasks/:id" element={<TaskDetail />} />
            <Route path="/groups" element={<BusinessGroups />} />
            <Route path="/users" element={<BusinessUsers />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/system-groups" element={<SystemGroups />} />
            <Route path="/storage" element={<Storage />} />
            <Route path="/shares" element={<Shares />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/audit" element={<Logs key="audit" kind="audit" />} />
            <Route path="/login-events" element={<Logs key="login" kind="login" />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Layout.Content>
        <Layout.Footer className="footer">
          gpuPM · GPU 服务器运维 · 时间统一显示为 Asia/Shanghai
        </Layout.Footer>
      </Layout>
    </Layout>
  );
}
