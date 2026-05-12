"""Agent 创建入口。

当前默认导出 LangGraph 版多 Agent 旅行规划器：
- 父 Agent：Plan-Execute-Replan-Synthesize 编排
- 子 Agent：地图 / 交通 / 搜索，分别绑定对应 MCP 工具
"""

import logging

from tools import get_global_tools
from travel_graph import create_travel_graph_agent

logger = logging.getLogger(__name__)


def create_travel_agent():
    """创建并返回旅行规划多 Agent 图实例。"""
    agent = create_travel_graph_agent()
    logger.info(
        "[Agent] LangGraph 多 Agent 创建完成，已绑定 %d 个 MCP 工具",
        len(get_global_tools()),
    )
    return agent


agent = create_travel_agent()

