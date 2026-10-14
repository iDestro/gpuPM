import { useEffect, useRef, useState } from "react";
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Layout,
  Menu,
  Space,
  Select,
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
  FileSearchOutlined,
  HddOutlined,
  ShareAltOutlined,
  HistoryOutlined,
  OrderedListOutlined,
  SolutionOutlined,
  LogoutOutlined,
  MenuOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { api, queryClient, Session, setSession } from "./api";
import { useI18n } from "./i18n";
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
  { key: "/groups", label: "业务优先级组", icon: <OrderedListOutlined /> },
  { key: "/users", label: "用户业务策略", icon: <SolutionOutlined /> },
  { key: "/accounts", label: "Linux 本地账号", icon: <UserOutlined /> },
  { key: "/system-groups", label: "Linux 系统组", icon: <TeamOutlined /> },
  { key: "/storage", label: "存储与容量", icon: <HddOutlined /> },
  { key: "/shares", label: "团队共享目录", icon: <ShareAltOutlined /> },
  { key: "/login-events", label: "SSH 登录记录", icon: <HistoryOutlined /> },
  { key: "/settings", label: "策略配置", icon: <SettingOutlined /> },
  { key: "/audit", label: "操作审计", icon: <FileSearchOutlined /> },
];
export default function App() {
  const { locale, t, setLocale } = useI18n();
  const languageSelect = <Select className="language-select" size="small" aria-label="语言 / Language" value={locale} onChange={setLocale} options={[{ value: "zh-CN", label: "中文" }, { value: "en-US", label: "English" }]} style={{ width: 88 }} />;
  const [user, setUser] = useState<Session | null>(null);
  const [mode, setMode] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>();
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem("gpupm.sidebar.collapsed") === "true"; }
    catch { return false; }
  });
  const toggleSidebar = () => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    try { localStorage.setItem("gpupm.sidebar.collapsed", String(next)); }
    catch { /* Keep navigation usable when browser storage is unavailable. */ }
  };
  const contentRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    if (contentRef.current) contentRef.current.scrollTop = 0;
  }, [location.pathname]);
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
        <Spin size="large" tip={t("连接管理服务…")} />
      </div>
    );
  if (!user)
    return (
      <div className="login-page">
        <div className="login-story">
          <span className="brand-mark">G</span>
          <Typography.Title>gpuPM</Typography.Title>
          <Typography.Title level={2}>
            {t("训练照常运行，")}
            <br />
            {t("管理清晰有序。")}
          </Typography.Title>
          <p>{t("GPU 任务、业务优先级、账号与存储，在同一个管理入口。")}</p>
          <Space wrap>
            <Tag>{t("进程身份核验")}</Tag>
            <Tag>{t("操作范围预览")}</Tag>
            <Tag>{t("审计留痕")}</Tag>
          </Space>
        </div>
        <Card className="login-card">
          <div className="login-language">{languageSelect}</div>
          <Typography.Title level={3}>{t("管理员登录")}</Typography.Title>
          <Typography.Paragraph type="secondary">
            {t("使用平台管理员凭据登录。Linux 账号密码与此独立。")}
          </Typography.Paragraph>
          <ErrorAlert error={error} />
          <Form layout="vertical" onFinish={login}>
            <Form.Item
              label={t("管理员账号")}
              name="username"
              rules={[{ required: true, message: t("请输入管理员账号") }]}
            >
              <Input autoComplete="username" size="large" />
            </Form.Item>
            <Form.Item
              label={t("密码")}
              name="password"
              rules={[{ required: true, message: t("请输入密码") }]}
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
              {t("登录管理平台")}
            </Button>
          </Form>
          <p className="login-foot">{t("安全会话 · 服务端 CSRF 校验")}</p>
        </Card>
      </div>
    );
  const selected = location.pathname.startsWith("/tasks/")
    ? "/tasks"
    : location.pathname;
  const localizedMenu = menu.map(item => ({ ...item, label: t(item.label), title: t(item.label), "aria-label": t(item.label) }));
  const navigationItems = [
    { type: "group" as const, label: t("资源监控"), children: localizedMenu.slice(0, 2) },
    { type: "group" as const, label: t("账号与权限"), children: [localizedMenu[4], localizedMenu[5], localizedMenu[2], localizedMenu[3]] },
    { type: "group" as const, label: t("存储协作"), children: localizedMenu.slice(6, 8) },
    { type: "group" as const, label: t("记录与设置"), children: [localizedMenu[8], localizedMenu[10], localizedMenu[9]] },
  ];
  const navigation = (collapsed = false, id = "drawer-navigation") => <>
    <div className="brand">
      <span className="brand-mark">G</span>
      {!collapsed ? <div>gpuPM<small>{t("服务器管理")}</small></div> : null}
    </div>
    <nav id={id} className="sidebar-menu" aria-label={t("主导航")}>
      <Menu mode="inline" inlineCollapsed={collapsed} selectedKeys={[selected]} items={collapsed ? navigationItems.flatMap(group => group.children) : navigationItems} onClick={({ key }) => {
        navigate(key);
        setNavigationOpen(false);
      }} />
    </nav>
    <div className="sidebar-footer">{!collapsed ? t("单机控制台") : null}<span>UTC+8</span></div>
  </>;
  return (
    <Layout className="app-layout">
      <a href="#main-content" className="skip-link">{t("跳转到内容")}</a>
      <Layout.Sider width={224} collapsedWidth={64} collapsed={sidebarCollapsed} trigger={null} theme="light" className="sidebar">{navigation(sidebarCollapsed, "desktop-navigation")}</Layout.Sider>
      <Drawer title={t("导航")} open={navigationOpen} onClose={() => setNavigationOpen(false)} placement="left" width={264} className="navigation-drawer" destroyOnHidden>
        {navigation()}
      </Drawer>
      <Layout className="app-main">
        <Layout.Header className="topbar">
          <div className="topbar-context">
            <Button className="sidebar-toggle" aria-controls="desktop-navigation" aria-expanded={!sidebarCollapsed} aria-label={t(sidebarCollapsed ? "展开侧栏" : "折叠侧栏")} title={t(sidebarCollapsed ? "展开侧栏" : "折叠侧栏")} icon={sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={toggleSidebar} />
            <Button className="navigation-toggle" aria-label={t("打开导航")} aria-expanded={navigationOpen} icon={<MenuOutlined />} onClick={() => setNavigationOpen(true)} />
            <span className="header-context">{localizedMenu.find(item => item.key === selected)?.label || t("管理控制台")}</span>
          </div>
          <div className="topbar-actions">
            {languageSelect}
            <Tag color={mode === "demo" ? "orange" : "blue"}>{mode === "demo" ? t("演示模式 · 不操作宿主机") : mode === "host" ? t("真实服务器") : t("模式待核验")}</Tag>
            <Typography.Text className="header-user">{user.username}</Typography.Text>
            <Button type="text" aria-label={t("退出")} icon={<LogoutOutlined />} loading={logoutBusy} onClick={logout}><span className="logout-label">{t("退出")}</span></Button>
          </div>
        </Layout.Header>
        <div className="content-scroll" role="main" id="main-content" tabIndex={-1} ref={contentRef}>
          <div className="content">
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
          </div>
          <Layout.Footer className="footer">{t("gpuPM · 时间显示为 Asia/Shanghai")}</Layout.Footer>
        </div>
      </Layout>
    </Layout>
  );
}
