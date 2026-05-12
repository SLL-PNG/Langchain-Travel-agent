"""Gradio 前端界面（流式输出 + 过程日志）"""

from datetime import datetime
from typing import List, Tuple, Any, Dict

import gradio as gr
from langchain_core.messages import AIMessage, HumanMessage

from agent import agent
from middleware import msg_text  # 复用工具函数


# ===== 工具小函数 =====

def _safe_trunc(v: str, maxlen=120):
    v = str(v)
    return (v[:maxlen] + "…") if len(v) > maxlen else v


def _fmt_ts():
    return datetime.now().strftime("%H:%M:%S")


def _mask_coord(x):
    """脱敏坐标（保留 3 位小数）"""
    if isinstance(x, str) and "," in x:
        try:
            a, b = x.split(",", 1)
            return f"{float(a):.3f},{float(b):.3f}"
        except Exception:
            return x
    return x


def _format_task(task: dict) -> str:
    domain = task.get("domain", "?")
    objective = task.get("objective", "未命名任务")
    required = task.get("required_info") or []
    required_text = "、".join(map(str, required)) if required else "无"
    return f"- `{domain}`：{objective}（需要：{required_text}）"


def _format_reasoning_trace(raw_events: List[Dict[str, Any]]) -> str:
    """生成可展示的推理摘要，不暴露模型隐藏思维链。"""
    graph_state = {}
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        if "travel_graph" in event and isinstance(event["travel_graph"], dict):
            graph_state.update(event["travel_graph"])
        for payload in event.values():
            if isinstance(payload, dict):
                graph_state.update(payload)

    events = graph_state.get("events") or []
    plan = graph_state.get("plan") or []
    observations = graph_state.get("observations") or {}

    if not events and not plan:
        return "（等待工作流事件生成）"

    lines = ["### AI 推理摘要", ""]
    if plan:
        lines.append("**1. 任务拆解**")
        lines.extend(_format_task(task) for task in plan if isinstance(task, dict))
        lines.append("")

    exec_events = [e for e in events if isinstance(e, dict) and e.get("stage") in ("execute", "observe")]
    if exec_events:
        lines.append("**2. 子 Agent 执行轨迹**")
        for e in exec_events[-8:]:
            stage = e.get("stage")
            agent_name = e.get("agent", "?")
            task_id = e.get("task_id", "?")
            if stage == "execute":
                tools = e.get("tool_names") or []
                tool_text = "、".join(tools[:5])
                if len(tools) > 5:
                    tool_text += f" 等 {len(tools)} 个"
                lines.append(f"- `{agent_name}` 接手 `{task_id}`：{e.get('objective') or e.get('message')}。可用工具：{tool_text or '无'}")
            else:
                preview = e.get("observation_preview") or ""
                lines.append(f"- `{agent_name}` 观察 `{task_id}`：{preview or '已返回结果'}")
        lines.append("")

    replan_events = [e for e in events if isinstance(e, dict) and e.get("stage") == "replan"]
    if replan_events:
        last = replan_events[-1]
        missing = last.get("missing") or []
        lines.append("**3. 补全判断**")
        lines.append(f"- {last.get('message', '已完成补全判断')}；缺口数量：{len(missing)}")
        lines.append("")

    if observations:
        lines.append("**4. 信息整合依据**")
        for task_id, obs in list(observations.items())[:6]:
            lines.append(f"- `{task_id}`：{_safe_trunc(obs, 180)}")

    return "\n".join(lines)


def _event_to_summary(event: dict) -> str:
    """将事件转换为摘要日志（不包含思维链）"""
    rounds_info = ""
    if "__tool_rounds__" in event:
        rounds = event.get("__tool_rounds__", 0)
        if rounds > 0:
            rounds_info = f"[轮次 {rounds}] "

    for stage_key, label in (
        ("plan", "规划"),
        ("execute", "执行"),
        ("observe", "观察"),
        ("replan", "补全判断"),
        ("synthesize", "攻略生成"),
    ):
        if stage_key in event:
            payload = event.get(stage_key) or {}
            if isinstance(payload, dict):
                events = payload.get("events") or []
                message = ""
                if events and isinstance(events[-1], dict):
                    message = events[-1].get("message", "")
                if not message:
                    message = payload.get("message", "")
                if stage_key == "plan":
                    plan = payload.get("plan") or []
                    lines = [f"[{_fmt_ts()}] 规划：生成 {len(plan)} 个子任务"]
                    lines.extend(_format_task(task) for task in plan[:5] if isinstance(task, dict))
                    return "  \n".join(lines)
                if stage_key == "execute":
                    obs = payload.get("observations") or {}
                    events = payload.get("events") or []
                    last = events[-1] if events and isinstance(events[-1], dict) else {}
                    agent_name = last.get("agent", "?")
                    task_id = last.get("task_id", "?")
                    tools = last.get("tool_names") or []
                    tool_text = "、".join(tools[:4]) + (f" 等 {len(tools)} 个" if len(tools) > 4 else "")
                    return f"[{_fmt_ts()}] 执行：`{agent_name}` 子 Agent 处理 `{task_id}`；工具：{tool_text or '无'}；累计观察 {len(obs)} 个"
                if stage_key == "observe":
                    events = payload.get("events") or []
                    last = events[-1] if events and isinstance(events[-1], dict) else {}
                    return f"[{_fmt_ts()}] 观察：`{last.get('agent', '?')}` 返回 `{last.get('task_id', '?')}` -> {_safe_trunc(last.get('observation_preview', ''), 140)}"
                return f"[{_fmt_ts()}] {label}：{message or '完成'}"

    if "travel_graph" in event:
        graph_state = event.get("travel_graph") or {}
        if isinstance(graph_state, dict):
            plan = graph_state.get("plan") or []
            return f"[{_fmt_ts()}] 多Agent工作流完成：{len(plan)} 个计划任务"

    # 城市解析事件
    if "pin_cities_and_adcodes.before_model" in event:
        try:
            pin_data = event["pin_cities_and_adcodes.before_model"]
            if isinstance(pin_data, dict) and "messages" in pin_data:
                msgs = pin_data["messages"]
                for m in msgs:
                    text = (
                        msg_text(m)
                        if hasattr(m, "content") or isinstance(m, dict)
                        else str(m)
                    )
                    if "【DEBUG】本轮解析城市：" in text:
                        line = text.split("【DEBUG】本轮解析城市：", 1)[1].split("；")[0]
                        return f"[{_fmt_ts()}] 🛰 {rounds_info}解析城市：{line}"
                    elif "【强制约束】本轮用户指定城市：" in text:
                        import re

                        match = re.search(r"本轮用户指定城市：([^。]+)", text)
                        if match:
                            return f"[{_fmt_ts()}] 🛰 {rounds_info}解析城市：{match.group(1)}"
        except Exception:
            pass

    # 单工具事件
    if "tool" in event:
        name = event.get("tool", {}).get("name") or event.get("tool_name") or "tool"
        ti = event.get("tool_input") or event.get("input") or {}
        city = ti.get("city") or ti.get("cityd") or "-"
        origin = ti.get("origin") or "-"
        destination = ti.get("destination") or "-"
        origin = _mask_coord(origin)
        destination = _mask_coord(destination)
        return (
            f"[{_fmt_ts()}] 🔧 {rounds_info}工具 {name} | "
            f"city={city} | origin={origin} -> dest={destination}"
        )

    # 批量工具事件（并行调用）
    if "tools" in event:
        tools_info = []
        tools_data = event.get("tools", {})
        msgs = []
        if isinstance(tools_data, dict) and "messages" in tools_data:
            msgs = tools_data.get("messages", [])
            for m in msgs:
                if hasattr(m, "name"):
                    tools_info.append(getattr(m, "name", "?"))

        batch_prefix = None
        if msgs:
            first_msg = msgs[0]
            if hasattr(first_msg, "tool_call_id"):
                call_id = getattr(first_msg, "tool_call_id", "")
                if "_split_" in str(call_id):
                    batch_prefix = str(call_id).rsplit("_split_", 1)[0]

        tool_count = len(tools_info) if tools_info else len(msgs)

        if tools_info:
            tool_names_str = "、".join(tools_info[:3])
            if tool_count > 3:
                tool_names_str += f" 等 {tool_count} 个"
            if batch_prefix and tool_count > 1:
                return f"[{_fmt_ts()}] 🔧 {rounds_info}工具 {tool_names_str} 完成（并行批次）"
            if tool_count > 1:
                return f"[{_fmt_ts()}] 🔧 {rounds_info}工具 {tool_names_str} 完成"
            return f"[{_fmt_ts()}] 🔧 {rounds_info}工具 {tool_names_str} 完成"

        return f"[{_fmt_ts()}] 🔧 {rounds_info}工具调用完成"

    # 模型事件
    if "model" in event:
        return f"[{_fmt_ts()}] 🤖 {rounds_info}模型生成中…"

    # 消息更新事件
    if "messages" in event:
        try:
            msgs = event.get("messages") or []
            for m in msgs:
                text = (
                    msg_text(m)
                    if hasattr(m, "content") or isinstance(m, dict)
                    else str(m)
                )
                if "【DEBUG】本轮解析城市：" in text:
                    line = text.split("【DEBUG】本轮解析城市：", 1)[1].split("；")[0]
                    return f"[{_fmt_ts()}] 🛰 {rounds_info}解析城市：{line}"
                elif "【强制约束】本轮用户指定城市：" in text:
                    import re

                    match = re.search(r"本轮用户指定城市：([^。]+)", text)
                    if match:
                        return f"[{_fmt_ts()}] 🛰 {rounds_info}解析城市：{match.group(1)}"
        except Exception:
            pass
        return f"[{_fmt_ts()}] 📩 {rounds_info}消息更新"

    return f"[{_fmt_ts()}] 📎 {rounds_info}事件 {_safe_trunc(str(list(event.keys())))}"


def stream_answer(
    user_text: str, chat_history, dev_mode_flag: bool
) -> Tuple[str, str, str, Any]:  # 🆕 返回 4 个值：content, logs, reasoning, raw_events
    """使用 agent.stream 做增量推送，并生成摘要 / JSON 日志 + 推理摘要"""
    summaries: List[str] = []
    raw_events: List[Dict[str, Any]] = []
    final_text = ""
    reasoning_text = ""
    tool_rounds_tracker = 0
    last_batch_prefix_seen = None

    for event in agent.stream(
        {"messages": [HumanMessage(content=user_text)], "history": chat_history},
        config={"recursion_limit": 40},
    ):
        if isinstance(event, dict):
            current_batch_prefix = None
            if "tools" in event or "tool" in event:
                tool_call_id = None
                if "tool" in event:
                    tool_data = event.get("tool", {})
                    if isinstance(tool_data, dict):
                        tool_call_id = (
                            tool_data.get("tool_call_id") or tool_data.get("id")
                        )
                elif "tools" in event:
                    tools_data = event.get("tools", {})
                    if isinstance(tools_data, dict) and "messages" in tools_data:
                        msgs = tools_data.get("messages", [])
                        if msgs:
                            first_msg = msgs[0]
                            if hasattr(first_msg, "tool_call_id"):
                                tool_call_id = getattr(first_msg, "tool_call_id", None)
                if tool_call_id:
                    if "_split_" in str(tool_call_id):
                        current_batch_prefix = str(tool_call_id).rsplit("_split_", 1)[0]
                    else:
                        current_batch_prefix = str(tool_call_id)

                if current_batch_prefix and current_batch_prefix != last_batch_prefix_seen:
                    tool_rounds_tracker += 1
                    last_batch_prefix_seen = current_batch_prefix

            event_with_rounds = dict(event)
            event_with_rounds["__tool_rounds__"] = tool_rounds_tracker
            raw_events.append(event_with_rounds)

        try:
            if isinstance(event, dict):
                summaries.append(_event_to_summary(event))
        except Exception:
            pass

        msgs = None
        if isinstance(event, dict):
            if "model" in event and isinstance(event["model"], dict):
                msgs = event["model"].get("result") or event["model"].get("messages")
            elif "messages" in event:
                msgs = event["messages"]

        # 🆕 提取 reasoning 和 content
        if isinstance(msgs, list):
            for msg in msgs:
                if isinstance(msg, AIMessage):
                    # 提取 content（最终回复）
                    if hasattr(msg, 'content') and msg.content:
                        final_text = msg.content

        md_text = "  \n".join(summaries) if summaries else "（本次尚无日志）"
        reasoning_text = _format_reasoning_trace(raw_events)
        yield (
            final_text or "",
            md_text,
            reasoning_text or "",
            raw_events if dev_mode_flag else None,
        )

    # 兜底：没流出文本就 invoke 一次
    if not final_text:
        result = agent.invoke(
            {"messages": [HumanMessage(content=user_text)], "history": chat_history},
            config={"recursion_limit": 40},
        )
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage):
                # 提取 content
                final_text = msg.content if hasattr(msg, 'content') else str(msg)
                break

    md_text = "  \n".join(summaries) if summaries else "（本次尚无日志）"
    reasoning_text = _format_reasoning_trace(raw_events)
    yield (final_text, md_text, reasoning_text, raw_events if dev_mode_flag else None)


def create_gradio_app():
    """创建并返回 Gradio Blocks 应用"""
    css = """
    .app-header {
        padding: 18px 22px;
        border: 1px solid #dde3ea;
        border-radius: 10px;
        background: linear-gradient(135deg, #f8fbff 0%, #eef6f2 100%);
        margin-bottom: 14px;
    }
    .app-title {
        font-size: 24px;
        font-weight: 700;
        color: #1d2b36;
        margin-bottom: 6px;
    }
    .app-subtitle {
        color: #52616d;
        font-size: 14px;
        line-height: 1.6;
    }
    .cap-row {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 12px;
    }
    .cap {
        border: 1px solid #d8e2dc;
        background: #ffffff;
        color: #24343f;
        border-radius: 999px;
        padding: 5px 10px;
        font-size: 12px;
    }
    #workflow-panel textarea, #reasoning-panel textarea {
        font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
    }
    """

    with gr.Blocks(theme=gr.themes.Soft(primary_hue="teal", neutral_hue="slate"), css=css) as demo:
        gr.HTML(
            """
            <div class="app-header">
              <div class="app-title">智能旅游规划 Agent 助手</div>
              <div class="app-subtitle">
                FastAPI + LangGraph + LangChain + MCP + DeepSeek。父 Agent 负责规划与整合，地图、搜索、交通子 Agent 分工执行。
              </div>
              <div class="cap-row">
                <span class="cap">Plan-Execute-Replan</span>
                <span class="cap">高德地图 MCP</span>
                <span class="cap">Bing 搜索 MCP</span>
                <span class="cap">12306 MCP</span>
                <span class="cap">工具缓存</span>
                <span class="cap">反馈增量优化</span>
              </div>
            </div>
            """
        )

        with gr.Row(equal_height=True):
            with gr.Column(scale=7):
                chat = gr.Chatbot(
                    height=560,
                    label="旅行规划对话",
                    show_copy_button=True,
                    bubble_full_width=False,
                )
                txt = gr.Textbox(
                    label="输入需求",
                    placeholder="例如：规划成都2天轻松路线，结合天气、热门攻略，并帮我看杭州到成都高铁方案",
                    lines=3,
                )
                with gr.Row():
                    clear_btn = gr.Button("清空对话", variant="secondary")
                    dev_mode = gr.Checkbox(label="开发者模式：显示原始事件 JSON", value=False)
                status = gr.Markdown("", visible=False)

            with gr.Column(scale=5):
                with gr.Accordion("工作流日志", open=True, elem_id="workflow-panel"):
                    logs_md = gr.Markdown(label="阶段日志", value="（本次尚无日志）")

                with gr.Accordion("AI 推理摘要", open=True, elem_id="reasoning-panel"):
                    reasoning_md = gr.Markdown(
                        label="可解释执行轨迹",
                        value="（等待工作流事件生成）",
                    )
                    gr.Markdown(
                        "这里展示的是可公开的任务拆解、子 Agent 执行轨迹和信息整合依据，"
                        "用于调试流程与理解决策，不展示模型隐藏思维链。"
                    )

                with gr.Accordion("原始事件 JSON", open=False):
                    logs_json = gr.JSON(
                        label="仅开发者模式显示",
                        visible=False,
                    )

        def on_submit(history, user_text, dev_mode_flag):
            history = history or []
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": ""})

            # 🆕 接收 4 个返回值：content, logs, reasoning, raw_events
            for partial_text, md_logs, reasoning, raw in stream_answer(
                user_text, history, dev_mode_flag
            ):
                history[-1]["content"] = partial_text
                json_payload = raw if dev_mode_flag else None

                formatted_reasoning = reasoning if reasoning else "（等待工作流事件生成）"

                # 🆕 返回 6 个值：history, txt, status, logs_md, logs_json, reasoning_md
                yield (
                    history,
                    gr.update(value="", interactive=True),
                    gr.update(visible=False),
                    gr.update(value=md_logs),
                    gr.update(value=json_payload, visible=bool(dev_mode_flag)),
                    gr.update(value=formatted_reasoning),  # 🆕 思考过程
                )

        txt.submit(
            on_submit,
            inputs=[chat, txt, dev_mode],
            # 🆕 新增 reasoning_md 到 outputs
            outputs=[chat, txt, status, logs_md, logs_json, reasoning_md],
            queue=True,
            show_progress=True,
            concurrency_limit="default",
            concurrency_id="chat",
        )

        def _clear(dev_flag):
            # 🆕 新增返回 reasoning_md 的清空状态
            return (
                [],
                "",
                gr.update(visible=False),
                gr.update(value="（本次尚无日志）"),
                gr.update(value=None, visible=bool(dev_flag)),
                gr.update(value="（等待工作流事件生成）"),
            )

        clear_btn.click(
            _clear,
            inputs=[dev_mode],
            # 🆕 新增 reasoning_md 到 outputs
            outputs=[chat, txt, status, logs_md, logs_json, reasoning_md],
            queue=False,
        )

    return demo
