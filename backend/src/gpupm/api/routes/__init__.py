from fastapi import APIRouter
from . import auth, management, system, tasks

router = APIRouter()
for module in (auth, management, tasks, system):
    router.include_router(module.router)
