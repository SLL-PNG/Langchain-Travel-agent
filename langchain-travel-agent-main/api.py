"""FastAPI 入口：REST API + 原生 HTML/CSS/JS 前端。"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import agent

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户旅游规划需求")
    history: list[dict[str, Any]] = Field(default_factory=list, description="历史对话")


class ChatResponse(BaseModel):
    answer: str
    plan: list[dict[str, Any]] = Field(default_factory=list)
    observations: dict[str, str] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    missing_tasks: list[dict[str, Any]] = Field(default_factory=list)
    failed_tasks: list[str] = Field(default_factory=list)
    iterations: int = 0


def create_fastapi_app() -> FastAPI:
    app = FastAPI(
        title="智能旅游规划 Agent 助手",
        description="基于 FastAPI + LangGraph + LangChain + MCP + LLM 的多 Agent 旅游规划系统",
        version="2.1.0",
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def root():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/ui")
    async def legacy_ui_redirect():
        return RedirectResponse(url="/")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "travel-agent"}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        result = agent.invoke({"query": req.query, "history": req.history})
        state = result.get("state", {})
        messages = result.get("messages", [])
        answer = messages[-1].content if messages else state.get("final_answer", "")
        return ChatResponse(
            answer=answer,
            plan=state.get("plan", []),
            observations=state.get("observations", {}),
            events=state.get("events", []),
            missing_tasks=state.get("missing_tasks", []),
            failed_tasks=state.get("failed_tasks", []),
            iterations=state.get("iterations", 0),
        )

    return app


api_app = create_fastapi_app()
