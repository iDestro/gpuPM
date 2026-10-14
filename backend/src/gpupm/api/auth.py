import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, text

from gpupm.db.models import Admin, LoginAttempt, WebSession
from gpupm.errors import DomainError

HASHER = PasswordHasher()


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


class Auth:
    def __init__(self, sessions):
        self.sessions = sessions
        self.dummy_hash = HASHER.hash(secrets.token_urlsafe(32))

    def create_admin(self, username, password):
        if not username or len(username) > 64 or len(password) < 12:
            raise ValueError("管理员名称不能为空，密码至少 12 位")
        with self.sessions.begin() as session:
            if session.get(Admin, username):
                raise ValueError("管理员已存在")
            session.add(Admin(username=username, password_hash=HASHER.hash(password)))

    def login(self, username, password, ip):
        now = time.time()
        key = digest(ip)
        with self.sessions.begin() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            attempt = session.get(LoginAttempt, key)
            if attempt is None:
                attempt = LoginAttempt(key=key, count=0, window=now)
                session.add(attempt)
            if now - attempt.window > 60:
                attempt.count, attempt.window = 0, now
            if attempt.count >= 5:
                raise DomainError("rate_limited", "登录尝试过多，请稍后重试", 429)
            attempt.count += 1
            session.commit()
        with self.sessions.begin() as session:
            admin = session.get(Admin, username)
            try:
                valid = HASHER.verify(admin.password_hash if admin else self.dummy_hash, password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid or admin is None or not admin.enabled:
                raise DomainError("invalid_credentials", "用户名或密码错误", 401)
            session.execute(delete(WebSession).where(WebSession.expires <= now))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            session.add(
                WebSession(token_hash=digest(token), username=username, csrf=csrf, expires=now + 28800)
            )
            return token, {"username": username, "csrf_token": csrf}

    def identity(self, token):
        if not token:
            raise DomainError("unauthorized", "请先登录", 401)
        with self.sessions() as session:
            item = session.get(WebSession, digest(token))
            if item is None or item.expires <= time.time():
                raise DomainError("unauthorized", "会话已失效", 401)
            admin = session.get(Admin, item.username)
            if admin is None or not admin.enabled:
                raise DomainError("unauthorized", "管理员已停用", 401)
            return {"username": item.username, "csrf_token": item.csrf}

    def logout(self, token):
        with self.sessions.begin() as session:
            session.execute(delete(WebSession).where(WebSession.token_hash == digest(token)))
