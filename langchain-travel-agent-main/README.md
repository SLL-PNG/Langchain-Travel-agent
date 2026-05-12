# LangChain Travel Agent

一个基于 LangChain、LangGraph、FastAPI 和 MCP 的智能旅行规划 Agent。项目会把旅行需求拆分给地图、搜索、铁路等子 Agent 执行，再汇总为可读的行程建议，适合用来学习多 Agent 编排、MCP 工具接入和旅行规划类应用原型。

## 功能特性

- **多 Agent 编排**：使用 Plan-Execute-Replan-Synthesize 流程拆解、执行和汇总任务。
- **MCP 工具接入**：支持高德地图 MCP、Bing 搜索 MCP 和 12306 MCP。
- **工具调用治理**：包含工具结果缓存、调用超时、失败降级和任务补全判断。
- **Web 交互界面**：FastAPI 提供接口，原生 HTML/CSS/JS 提供聊天和执行日志面板。
- **环境变量配置**：所有密钥和 MCP 地址均通过 `.env` 管理，不写入代码。

## 技术栈

| 模块 | 用途 |
| --- | --- |
| LangChain | Agent 与工具调用 |
| LangGraph | 多阶段工作流编排 |
| langchain-mcp-adapters | MCP Server 接入 |
| langchain-openai | 兼容 OpenAI 协议的 DeepSeek 模型调用 |
| FastAPI | HTTP API 与静态页面服务 |
| Uvicorn | 本地开发服务器 |
| python-dotenv | 加载本地环境变量 |

## 项目结构

```text
.
├── agent.py                  # Agent 创建入口
├── api.py                    # FastAPI API 和静态页面路由
├── config.py                 # 配置项与环境变量读取
├── main.py                   # 应用启动入口
├── tools.py                  # MCP 工具加载、同步封装和缓存
├── travel_graph.py           # LangGraph 多 Agent 工作流
├── middleware.py             # 早期 LangChain 中间件实验代码
├── static/                   # 前端页面资源
├── docs/                     # 架构说明文档
├── src/                      # README 图片资源
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量模板
└── README.md                 # 项目说明
```

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/your-name/langchain-travel-agent.git
cd langchain-travel-agent
```

### 2. 安装依赖

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置环境变量

复制环境变量模板：

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

填写 `.env`：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

AMAP_MCP_URL=your_amap_mcp_sse_url
BING_MCP_URL=
TRAIN12306_MCP_URL=
```

### 4. 启动应用

```bash
python main.py
```

启动后访问终端中显示的本地地址，默认从 `http://127.0.0.1:7861/` 开始寻找可用端口。

## 环境变量

| 变量名 | 必填 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | 是 | DeepSeek OpenAI 兼容接口地址，默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 是 | 模型名称，例如 `deepseek-chat` | 
| `AMAP_MCP_URL` | 是 | 高德地图 MCP Server 的 SSE 地址 |  魔搭社区
| `BING_MCP_URL` | 否 | Bing 搜索 MCP Server 的 SSE 地址 |  魔搭社区
| `TRAIN12306_MCP_URL` | 否 | 12306 MCP Server 的 Streamable HTTP 地址 |

`.env` 会被 `.gitignore` 忽略，请不要把真实密钥、个人 MCP 地址或本地配置提交到 GitHub。

## API

### 健康检查

```http
GET /api/health
```

### 旅行规划对话

```http
POST /api/chat
Content-Type: application/json

{
  "query": "帮我规划成都两日美食路线，顺便考虑天气和交通",
  "history": []
}
```

响应会返回最终答案、执行计划、子 Agent 观察结果、工作流事件和失败任务等调试信息。

## 开发说明

- `travel_graph.py` 是当前主流程，负责父 Agent 规划、子 Agent 执行、补全判断和最终汇总。
- `tools.py` 会按环境变量动态加载 MCP Server；可选 MCP 未配置时会自动跳过。
- `static/app.js` 会把 `/api/chat` 返回的事件渲染成工作流日志和推理摘要。



