import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    mode: str = "host"
    database: Path = Path(".runtime/app.db")
    agent_database: Path = Path(".runtime/agent.db")
    agent_socket: str = "/run/gpupm/agent.sock"
    secure_cookie: bool = False
    home_base: str = "/home"
    data_base: str = "/data"
    frontend_dist: Path = Path("../frontend/dist")

    def __post_init__(self):
        if self.mode not in {"demo", "host"}:
            raise ValueError("mode must be demo or host")

    @classmethod
    def from_env(cls):
        return cls(
            mode=os.getenv("GPUPM_MODE", "host"),
            database=Path(os.getenv("GPUPM_DATABASE", ".runtime/app.db")),
            agent_database=Path(os.getenv("GPUPM_AGENT_DATABASE", ".runtime/agent.db")),
            agent_socket=os.getenv("GPUPM_AGENT_SOCKET", "/run/gpupm/agent.sock"),
            secure_cookie=os.getenv("GPUPM_SECURE_COOKIE", "0") == "1",
            home_base=os.getenv("GPUPM_HOME_BASE", "/home"),
            data_base=os.getenv("GPUPM_DATA_BASE", "/data"),
            frontend_dist=Path(os.getenv("GPUPM_FRONTEND_DIST", "../frontend/dist")),
        )
