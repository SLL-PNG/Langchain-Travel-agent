
"""配置管理与常量集中定义"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """项目级别配置常量"""

    # 工具调用预算（轮次）
    # 启用并行调用后，1 轮即可完成大部分查询（POI + 路线 + 天气）
    MAX_TOOL_ROUNDS: int = 1

    # 模型输出配置
    MAX_OUTPUT_TOKENS: int = 1200

    # 异步工具超时（秒）
    ASYNC_TOOL_TIMEOUT: int = 10

    # Plan-Execute-Replan 循环配置
    MAX_REPLAN_LOOPS: int = 2

    # 子 Agent ReAct 最大递归步数
    SUBAGENT_RECURSION_LIMIT: int = 24

    # 上下文压缩：保留最近 N 条普通消息，ToolMessage 始终保留
    RECENT_MESSAGE_KEEP: int = 8

    # 工具结果缓存上限（内存缓存，按工具名+参数去重）
    TOOL_CACHE_MAX_SIZE: int = 256

    # 城市标识映射 / “外地”指示，用于 strip_unasked_cities 额外检查
    CITY_INDICATORS = {
        "成都": ["杭州", "西湖", "330100", "330102", "北京", "110000", "上海", "310000"],
        "杭州": ["成都", "510100", "北京", "110000", "上海", "310000"],
        "北京": ["杭州", "330100", "成都", "510100", "上海", "310000"],
    }


# 环境变量（对外暴露，方便其它模块直接使用）
DEEPSEEK_API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL: str | None = os.getenv("DEEPSEEK_BASE_URL")
DEEPSEEK_MODEL: str | None = os.getenv("DEEPSEEK_MODEL")
AMAP_MCP_URL: str | None = os.getenv("AMAP_MCP_URL")
BING_MCP_URL: str | None = os.getenv("BING_MCP_URL")
TRAIN12306_MCP_URL: str | None = os.getenv("TRAIN12306_MCP_URL")
