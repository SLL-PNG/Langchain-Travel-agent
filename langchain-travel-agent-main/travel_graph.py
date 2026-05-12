"""LangGraph 多 Agent 旅游规划工作流。

父 Agent 负责 Plan-Execute-Replan 编排；地图、交通、搜索 3 个子 Agent
分别绑定对应 MCP 工具，在 Execute 阶段用 ReAct 工具循环完成专业任务。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from config import Config, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from tools import get_global_tools, load_tools

logger = logging.getLogger(__name__)


class TravelGraphState(TypedDict, total=False):
    query: str
    history: list[Any]
    compressed_messages: list[BaseMessage]
    previous_answer: str
    feedback: str
    plan: list[dict[str, Any]]
    observations: dict[str, str]
    completed_tasks: list[str]
    failed_tasks: list[str]
    missing_tasks: list[dict[str, Any]]
    iterations: int
    final_answer: str
    events: list[dict[str, Any]]


def _make_model(streaming: bool = False) -> ChatOpenAI:
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置，请检查 .env 或环境变量")

    return ChatOpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        model=DEEPSEEK_MODEL,
        streaming=streaming,
        temperature=0.3,
        top_p=0.8,
        max_tokens=Config.MAX_OUTPUT_TOKENS,
    )


def _message_text(m: Any) -> str:
    if isinstance(m, BaseMessage):
        return str(getattr(m, "content", "") or "")
    if isinstance(m, dict):
        return str(m.get("content", "") or "")
    return str(m or "")


def _history_to_messages(history: list[Any] | None) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in history or []:
        if isinstance(item, BaseMessage):
            messages.append(item)
            continue
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content") or ""
        if not content:
            continue
        if role in ("user", "human"):
            messages.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            messages.append(AIMessage(content=content))
    return messages


def compress_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """保留全部 ToolMessage 和最近 N 条普通消息，控制上下文长度。"""
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    normal_messages = [m for m in messages if not isinstance(m, ToolMessage)]
    return tool_messages + normal_messages[-Config.RECENT_MESSAGE_KEEP :]


def _last_assistant(history: list[Any] | None) -> str:
    for item in reversed(history or []):
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        if role == "assistant" and content:
            return str(content)
    return ""


def _looks_like_feedback(query: str, previous_answer: str) -> bool:
    if not previous_answer:
        return False
    return bool(re.search(r"(调整|修改|改成|不要|删掉|增加|保留|换成|重新安排|太赶)", query))


def _extract_json(text: str) -> Any | None:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            return None
    return None


def _tool_names(tools: list[Any]) -> list[str]:
    return [getattr(t, "name", "") for t in tools if getattr(t, "name", "")]


def _preview(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _domain_tools(tools: list[Any]) -> dict[str, list[Any]]:
    domains = {"map": [], "train": [], "search": []}
    for tool in tools:
        name = getattr(tool, "name", "").lower()
        if name.startswith("maps_") or any(
            key in name
            for key in (
                "amap",
                "weather",
                "geo",
                "route",
                "direction",
                "distance",
                "around",
            )
        ):
            domains["map"].append(tool)
        elif any(
            key in name
            for key in (
                "ticket",
                "train",
                "station",
                "transfer",
                "12306",
            )
        ):
            domains["train"].append(tool)
        elif any(key in name for key in ("bing", "search", "crawl", "webpage")):
            domains["search"].append(tool)
    return domains


def _fallback_plan(query: str, available_domains: set[str]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []

    def add(domain: str, objective: str, required_info: list[str]):
        if domain in available_domains:
            plan.append(
                {
                    "id": f"{domain}-{len(plan) + 1}",
                    "domain": domain,
                    "objective": objective,
                    "required_info": required_info,
                }
            )

    needs_train = bool(re.search(r"(火车|高铁|动车|车票|12306|车站|换乘|出发|到达)", query))
    needs_search = bool(re.search(r"(攻略|最新|热门|推荐|评价|开放|门票|避坑|搜索|网页)", query))
    needs_map = bool(re.search(r"(景点|路线|美食|天气|地图|距离|地铁|打车|步行|周边|地址|行程)", query))

    if not any((needs_train, needs_search, needs_map)):
        needs_search = "search" in available_domains
        needs_map = "map" in available_domains

    if needs_search:
        add("search", "检索实时攻略、开放信息、用户评价和补充背景", ["网页搜索结果", "关键来源摘要"])
    if needs_map:
        add("map", "查询目的地 POI、天气、位置和路线距离", ["POI", "天气", "路线或距离"])
    if needs_train:
        add("train", "查询铁路出行、车站、车次、余票或换乘方案", ["车站", "车次", "余票/换乘"])

    return plan


class DomainAgent:
    def __init__(self, name: str, tools: list[Any], system_prompt: str):
        self.name = name
        self.tools = tools
        self.tool_names = _tool_names(tools)
        self.agent = create_agent(
            model=_make_model(streaming=False),
            tools=tools,
            system_prompt=system_prompt,
            name=f"{name}_agent",
        )

    def run(self, query: str, task: dict[str, Any], context: str) -> str:
        tool_hint = ", ".join(self.tool_names) if self.tool_names else "无可用工具"
        prompt = (
            f"用户原始需求：{query}\n\n"
            f"当前任务：{json.dumps(task, ensure_ascii=False)}\n\n"
            f"已知上下文：\n{context or '暂无'}\n\n"
            f"你可用的工具：{tool_hint}\n"
            "执行协议：\n"
            "1. 先判断本任务缺什么信息，再选择最少必要工具。\n"
            "2. 最多调用 3 次工具；拿到可用证据、工具无结果或工具失败后必须停止。\n"
            "3. 对比当前任务 required_info，判断完成度。\n"
            "4. 最终输出四段：任务结论、关键证据、完成度、仍缺信息。\n"
            "禁止继续追问式调用，禁止编造工具没有返回的信息。"
        )
        result = self.agent.invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": Config.SUBAGENT_RECURSION_LIMIT},
        )
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                return str(msg.content)
        return str(result)


class TravelGraphAgent:
    def __init__(self):
        tools = load_tools()
        self.tools = tools
        self.domains = _domain_tools(tools)
        self.available_domains = {k for k, v in self.domains.items() if v}
        self.planner_model = _make_model(streaming=False)
        self.synth_model = _make_model(streaming=False)
        self.subagents = self._build_subagents()
        self.graph = self._build_graph()
        logger.info(
            "[TravelGraph] 已创建父 Agent + %d 个子 Agent：%s",
            len(self.subagents),
            ", ".join(sorted(self.subagents)),
        )

    def _build_subagents(self) -> dict[str, DomainAgent]:
        prompts = {
            "map": (
                "你是地图与本地生活子 Agent，负责高德地图 MCP 工具。"
                "重点查询 POI、天气、地址、路线、距离、周边搜索。"
                "优先给出可验证的地点名、路线段、天气要点和距离信息。"
            ),
            "train": (
                "你是铁路交通子 Agent，负责 12306 MCP 工具。"
                "重点查询车站、车次、余票、票价、经停站和换乘。"
                "日期不明确时先用时间工具判断相对日期，再查询车票。"
            ),
            "search": (
                "你是实时搜索子 Agent，负责 Bing 搜索 MCP 工具。"
                "重点查询实时网页资料、攻略、新闻、评价和网页正文。"
                "优先提炼高可信来源的共识，避免把单一网页当成事实。"
            ),
        }
        return {
            domain: DomainAgent(domain, tools, prompts[domain])
            for domain, tools in self.domains.items()
            if tools
        }

    def _build_graph(self):
        graph = StateGraph(TravelGraphState)
        graph.add_node("plan", self._plan_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("replan", self._replan_node)
        graph.add_node("synthesize", self._synthesize_node)

        graph.set_entry_point("plan")
        graph.add_edge("plan", "execute")
        graph.add_edge("execute", "replan")
        graph.add_conditional_edges(
            "replan",
            self._route_after_replan,
            {"execute": "execute", "synthesize": "synthesize"},
        )
        graph.add_edge("synthesize", END)
        return graph.compile()

    def _plan_node(self, state: TravelGraphState) -> dict[str, Any]:
        query = state["query"]
        history_messages = _history_to_messages(state.get("history"))
        compressed = compress_messages(history_messages)
        previous_answer = _last_assistant(state.get("history"))
        feedback = query if _looks_like_feedback(query, previous_answer) else ""

        available = ", ".join(sorted(self.available_domains)) or "无"
        prompt = (
            "你是父 Agent，负责把旅游需求拆成专业子 Agent 任务。"
            "你的目标是生成最少但充分的执行计划，让子 Agent 能并行收集信息。"
            "只返回 JSON 数组，每项包含 id/domain/objective/required_info。"
            "domain 只能从可用域中选择；不要拆出没有工具支撑的任务。"
            "如果用户是基于上一版反馈修改，只规划需要重新验证或补充的部分。\n\n"
            f"可用域：{available}\n"
            "domain 含义：search=实时网页搜索，map=地图/天气/POI/路线，train=12306铁路。\n"
            f"用户需求：{query}\n"
            f"上一版答案：{previous_answer[:1200] if previous_answer else '无'}\n"
            f"用户反馈：{feedback or '无'}"
        )

        plan = None
        try:
            resp = self.planner_model.invoke([HumanMessage(content=prompt)])
            parsed = _extract_json(str(resp.content))
            if isinstance(parsed, list):
                plan = parsed
        except Exception as e:
            logger.warning("[TravelGraph] LLM 规划失败，使用规则规划：%s", e)

        fallback_plan = _fallback_plan(query, self.available_domains)
        if not plan:
            plan = fallback_plan
        else:
            existing_domains = {task.get("domain") for task in plan if isinstance(task, dict)}
            for task in fallback_plan:
                if task.get("domain") not in existing_domains:
                    plan.append(task)
                    existing_domains.add(task.get("domain"))

        plan = [
            task
            for task in plan
            if isinstance(task, dict) and task.get("domain") in self.available_domains
        ]
        if not plan:
            plan = _fallback_plan(query, self.available_domains)

        return {
            "compressed_messages": compressed,
            "previous_answer": previous_answer,
            "feedback": feedback,
            "plan": plan,
            "observations": state.get("observations", {}),
            "completed_tasks": state.get("completed_tasks", []),
            "failed_tasks": state.get("failed_tasks", []),
            "iterations": state.get("iterations", 0),
            "events": state.get("events", [])
            + [
                {
                    "stage": "plan",
                    "message": f"生成 {len(plan)} 个子任务",
                    "available_agents": sorted(self.available_domains),
                    "compressed_message_count": len(compressed),
                    "feedback_detected": bool(feedback),
                    "plan": plan,
                }
            ],
        }

    def _execute_node(self, state: TravelGraphState) -> dict[str, Any]:
        observations = dict(state.get("observations") or {})
        completed = set(state.get("completed_tasks") or [])
        failed = set(state.get("failed_tasks") or [])
        retry_ids = {str(task.get("id")) for task in state.get("missing_tasks", [])}
        events = list(state.get("events") or [])

        context = "\n\n".join(
            f"[{task_id}]\n{content}" for task_id, content in observations.items()
        )
        for task in state.get("plan", []):
            task_id = str(task.get("id") or f"{task.get('domain')}-{len(completed) + 1}")
            if task_id in failed:
                continue
            if task_id in completed and task_id not in retry_ids:
                continue

            domain = task.get("domain")
            subagent = self.subagents.get(str(domain))
            if not subagent:
                observations[task_id] = f"未配置 {domain} 子 Agent，任务无法执行。"
                completed.add(task_id)
                continue

            events.append(
                {
                    "stage": "execute",
                    "agent": domain,
                    "task_id": task_id,
                    "objective": task.get("objective", ""),
                    "required_info": task.get("required_info", []),
                    "tool_names": subagent.tool_names,
                    "message": f"{domain} 子 Agent 开始执行：{task.get('objective', '')}",
                }
            )
            try:
                observations[task_id] = subagent.run(state["query"], task, context)
                events.append(
                    {
                        "stage": "observe",
                        "agent": domain,
                        "task_id": task_id,
                        "message": f"{domain} 子 Agent 返回观察结果",
                        "observation_preview": _preview(observations[task_id]),
                    }
                )
            except Exception as e:
                logger.warning("[TravelGraph] 子 Agent 执行失败：%s", e)
                observations[task_id] = (
                    f"{domain} 子 Agent 工具调用失败：{type(e).__name__}: {e}。"
                    "最终答案需标注该部分未能实时验证，并基于已知常识给出保守建议。"
                )
                failed.add(task_id)
                events.append(
                    {
                        "stage": "observe",
                        "agent": domain,
                        "task_id": task_id,
                        "message": f"{domain} 子 Agent 执行失败",
                        "observation_preview": _preview(observations[task_id]),
                    }
                )
            completed.add(task_id)

        return {
            "observations": observations,
            "completed_tasks": sorted(completed),
            "failed_tasks": sorted(failed),
            "events": events,
        }

    def _replan_node(self, state: TravelGraphState) -> dict[str, Any]:
        iterations = int(state.get("iterations") or 0) + 1
        observations = state.get("observations") or {}
        failed = set(state.get("failed_tasks") or [])
        missing: list[dict[str, Any]] = []

        for task in state.get("plan", []):
            task_id = str(task.get("id"))
            if task_id in failed:
                continue
            obs = observations.get(task_id, "")
            if not obs or re.search(r"(失败|无法执行|error|缺少|未找到)", obs, flags=re.I):
                missing.append(task)

        events = list(state.get("events") or [])
        if missing and iterations < Config.MAX_REPLAN_LOOPS:
            events.append(
                {
                    "stage": "replan",
                    "message": f"发现 {len(missing)} 个缺口，进入补全循环",
                    "iteration": iterations,
                    "missing": missing,
                }
            )
        else:
            events.append(
                {
                    "stage": "replan",
                    "message": "信息已足够或达到补全上限，进入攻略生成",
                    "iteration": iterations,
                    "missing": missing,
                }
            )

        return {"iterations": iterations, "missing_tasks": missing, "events": events}

    def _route_after_replan(self, state: TravelGraphState) -> str:
        if state.get("missing_tasks") and int(state.get("iterations") or 0) < Config.MAX_REPLAN_LOOPS:
            return "execute"
        return "synthesize"

    def _synthesize_node(self, state: TravelGraphState) -> dict[str, Any]:
        observations_text = "\n\n".join(
            f"## {task_id}\n{content}"
            for task_id, content in (state.get("observations") or {}).items()
        )
        plan_text = json.dumps(state.get("plan", []), ensure_ascii=False, indent=2)
        feedback = state.get("feedback") or ""
        previous = state.get("previous_answer") or ""

        prompt = (
            "你是父 Agent，负责整合所有子 Agent 观察结果，生成最终旅行攻略。"
            "输出要求：\n"
            "1. 先给一句总体判断。\n"
            "2. 用分日/分时段行程组织内容，风格轻松不赶。\n"
            "3. 交通、天气、搜索信息分别标注来自哪个子 Agent 的观察要点。\n"
            "4. 对未实时验证的信息明确标注“需确认”。\n"
            "5. 最后给备选调整建议和仍需补充的信息。\n"
            "不要编造工具未返回的信息。"
            "如果部分工具失败，不要直接拒绝；请基于用户原始需求给出保守初版，"
            "并明确列出哪些信息未能实时验证、仍需补充。"
            "如果用户是在反馈修改上一版，尽量保留未被要求调整的内容，只增量修改相关部分。\n\n"
            f"用户需求：{state['query']}\n\n"
            f"用户反馈：{feedback or '无'}\n\n"
            f"上一版答案：{previous[:2000] if previous else '无'}\n\n"
            f"执行计划：\n{plan_text}\n\n"
            f"子 Agent 观察结果：\n{observations_text or '无'}"
        )
        try:
            resp = self.synth_model.invoke([HumanMessage(content=prompt)])
            final = str(resp.content or "")
        except Exception as e:
            final = f"生成最终攻略失败：{type(e).__name__}: {e}\n\n已获得信息：\n{observations_text}"

        return {
            "final_answer": final,
            "events": list(state.get("events") or [])
            + [
                {
                    "stage": "synthesize",
                    "message": "最终攻略生成完成",
                    "answer_preview": _preview(final),
                }
            ],
        }

    def _state_from_inputs(self, inputs: dict[str, Any]) -> TravelGraphState:
        messages = inputs.get("messages") or []
        query = inputs.get("query") or ""
        if not query and messages:
            query = _message_text(messages[-1])
        history = inputs.get("history") or []
        return {"query": str(query), "history": history}

    def invoke(self, inputs: dict[str, Any], config: dict[str, Any] | None = None):
        state = self._state_from_inputs(inputs)
        result = self.graph.invoke(state, config=config)
        return {
            "messages": [AIMessage(content=result.get("final_answer", ""))],
            "state": result,
        }

    def stream(self, inputs: dict[str, Any], config: dict[str, Any] | None = None):
        state = self._state_from_inputs(inputs)
        latest_state: dict[str, Any] = {}
        for update in self.graph.stream(state, config=config, stream_mode="updates"):
            if not isinstance(update, dict):
                continue
            for payload in update.values():
                if isinstance(payload, dict):
                    latest_state.update(payload)
            yield update

        yield {
            "messages": [AIMessage(content=latest_state.get("final_answer", ""))],
            "travel_graph": latest_state,
        }


def create_travel_graph_agent() -> TravelGraphAgent:
    return TravelGraphAgent()
