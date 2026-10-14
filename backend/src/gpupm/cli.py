import argparse
import getpass
import json
import os
from pathlib import Path

from gpupm.api.auth import Auth
from gpupm.config import Config
from gpupm.db.session import database


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gpupm")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser(
        "admin-add", help="Create Web administrator; password is prompted, never an argv option"
    )
    admin.add_argument("--username", required=True)
    admin.add_argument("--database", default=os.getenv("GPUPM_DATABASE", ".runtime/app.db"))
    serve = commands.add_parser("serve")
    serve.add_argument("--mode", choices=["host", "demo"], default=os.getenv("GPUPM_MODE", "host"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--database", default=os.getenv("GPUPM_DATABASE", ".runtime/app.db"))
    serve.add_argument("--agent-database", default=os.getenv("GPUPM_AGENT_DATABASE", ".runtime/agent.db"))
    serve.add_argument("--agent-socket", default=os.getenv("GPUPM_AGENT_SOCKET", "/run/gpupm/agent.sock"))
    init = commands.add_parser(
        "init-config", help="Write root-owned agent config; does not change users or mounts"
    )
    init.add_argument("--path", required=True)
    init.add_argument("--api-uid", type=int, required=True)
    init.add_argument("--data-base", required=True)
    init.add_argument("--home-base", default="/home")
    init.add_argument("--maintenance-user", action="append", required=True)
    args = parser.parse_args(argv)
    if args.command == "admin-add":
        password = getpass.getpass("Web 管理员密码（至少 12 位）: ")
        if password != getpass.getpass("再次输入密码: "):
            parser.error("两次密码不一致")
        _, sessions = database(Path(args.database))
        try:
            Auth(sessions).create_admin(args.username, password)
        except ValueError as exc:
            parser.error(str(exc))
        print("管理员已创建；Linux SSH 凭据与本账号独立。")
    elif args.command == "serve":
        import uvicorn
        from gpupm.api.main import create_app

        config = Config.from_env()
        config.mode = args.mode
        config.database = Path(args.database)
        config.agent_database = Path(args.agent_database)
        config.agent_socket = args.agent_socket
        config.__post_init__()
        uvicorn.run(create_app(config), host=args.host, port=args.port)
    else:
        if os.geteuid() != 0:
            parser.error("init-config 必须以 root 执行")
        home, data = Path(args.home_base), Path(args.data_base)
        if not home.is_absolute() or not data.is_absolute() or not home.is_dir() or not data.is_dir():
            parser.error("目录根必须是已存在的绝对目录；请先核验数据卷挂载")
        if home == data or home.is_relative_to(data) or data.is_relative_to(home):
            parser.error("主目录根和数据目录根不能重叠")
        if home.resolve() != home or data.resolve() != data:
            parser.error("目录根不能经过软链接")
        path = Path(args.path)
        if not path.is_absolute():
            parser.error("配置路径必须为绝对路径")
        config = dict(
            store_path="/var/lib/gpupm/agent/agent.db",
            socket_path="/run/gpupm/agent.sock",
            api_uid=args.api_uid,
            maintenance_users=args.maintenance_user,
            allow_mutations=False,
            home_base=str(home),
            home_dev_id=home.stat().st_dev,
            data_dev_id=data.stat().st_dev,
            data_base=str(data),
            share_base=str(data / "shared"),
            scan_interval_seconds=5,
            term_grace_seconds=10,
            storage_scan_interval_seconds=900,
        )
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as output:
            json.dump(config, output, indent=2)
            output.write("\n")
        print("只读 agent 配置已创建；未创建账号、目录或调整挂载。")


if __name__ == "__main__":
    main()
