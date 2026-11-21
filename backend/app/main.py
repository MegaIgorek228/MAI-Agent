from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.mcp_tools import mcp
from app.routers import applicants, auth, chat, knowledge, users
from app.telegram_service import telegram_service

settings = get_settings()
mcp_app = mcp.http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env == "test":
        yield
        return
    async with mcp_app.lifespan(app):
        await telegram_service.start()
        yield
        await telegram_service.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(applicants.router)
app.include_router(knowledge.router)
app.include_router(chat.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


try:
    app.mount("/", mcp_app)
except AttributeError:
    # FastMCP versions without HTTP mounting can still run the registered tools separately.
    pass
