const chatMessages = document.querySelector("#chatMessages");
const chatForm = document.querySelector("#chatForm");
const queryInput = document.querySelector("#queryInput");
const sendBtn = document.querySelector("#sendBtn");
const clearBtn = document.querySelector("#clearBtn");
const workflowLog = document.querySelector("#workflowLog");
const reasoningTrace = document.querySelector("#reasoningTrace");
const rawJson = document.querySelector("#rawJson");
const copyLogsBtn = document.querySelector("#copyLogsBtn");
const copyTraceBtn = document.querySelector("#copyTraceBtn");
const serviceUrl = document.querySelector("#service-url");

let history = [];
let lastPayload = null;

serviceUrl.textContent = window.location.origin;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortText(value, limit = 180) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function addMessage(role, content) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.innerHTML = `
    <div class="avatar">${role === "user" ? "你" : "AI"}</div>
    <div class="bubble">${escapeHtml(content)}</div>
  `;
  chatMessages.appendChild(article);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function setBusy(isBusy) {
  sendBtn.disabled = isBusy;
  queryInput.disabled = isBusy;
  sendBtn.textContent = isBusy ? "运行中" : "发送";
}

function renderWorkflow(events = []) {
  if (!events.length) {
    workflowLog.className = "timeline empty";
    workflowLog.textContent = "暂无工作流事件";
    return;
  }

  workflowLog.className = "timeline";
  workflowLog.innerHTML = events
    .map((event) => {
      const stage = event.stage || "event";
      const titleMap = {
        plan: "Plan 任务规划",
        execute: "Execute 子 Agent 执行",
        observe: "Observe 工具观察",
        replan: "Replan 缺口补全",
        synthesize: "Synthesize 攻略生成",
      };
      const title = titleMap[stage] || stage;
      const detail = event.observation_preview || event.objective || event.message || "";
      const agent = event.agent ? `子 Agent：${event.agent}` : "";
      const task = event.task_id ? `任务：${event.task_id}` : "";
      const meta = [agent, task].filter(Boolean).join(" · ");
      return `
        <div class="log-item">
          <strong>${escapeHtml(title)}</strong>
          <div>${escapeHtml(shortText(detail, 240))}</div>
          ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
        </div>
      `;
    })
    .join("");
}

function renderReasoning(payload) {
  const plan = payload?.plan || [];
  const observations = payload?.observations || {};
  const events = payload?.events || [];
  const failedTasks = payload?.failed_tasks || [];
  const executeEvents = events.filter((e) => ["execute", "observe"].includes(e.stage));
  const replanEvents = events.filter((e) => e.stage === "replan");

  if (!plan.length && !events.length) {
    reasoningTrace.className = "trace empty";
    reasoningTrace.textContent = "等待工作流事件生成";
    return;
  }

  reasoningTrace.className = "trace";
  const planHtml = plan
    .map((task) => `<li><strong>${escapeHtml(task.domain || "?")}</strong>：${escapeHtml(task.objective || "")}</li>`)
    .join("");

  const execHtml = executeEvents
    .slice(-10)
    .map((event) => {
      if (event.stage === "execute") {
        const tools = (event.tool_names || []).slice(0, 5).join("、");
        return `<li>${escapeHtml(event.agent || "?")} 接手 ${escapeHtml(event.task_id || "?")}；工具：${escapeHtml(tools || "无")}</li>`;
      }
      return `<li>${escapeHtml(event.agent || "?")} 观察 ${escapeHtml(event.task_id || "?")}：${escapeHtml(shortText(event.observation_preview || "", 180))}</li>`;
    })
    .join("");

  const lastReplan = replanEvents.at(-1);
  const replanHtml = lastReplan
    ? `<li>${escapeHtml(lastReplan.message || "")}；缺口数量：${(lastReplan.missing || []).length}；失败任务：${escapeHtml(failedTasks.join("、") || "无")}</li>`
    : "<li>尚未进入补全判断</li>";

  const obsHtml = Object.entries(observations)
    .slice(0, 6)
    .map(([key, value]) => `<li><strong>${escapeHtml(key)}</strong>：${escapeHtml(shortText(value, 180))}</li>`)
    .join("");

  reasoningTrace.innerHTML = `
    <div class="trace-section">
      <h3>1. 任务拆解</h3>
      <ul>${planHtml || "<li>暂无计划</li>"}</ul>
    </div>
    <div class="trace-section">
      <h3>2. 子 Agent 执行轨迹</h3>
      <ul>${execHtml || "<li>等待执行</li>"}</ul>
    </div>
    <div class="trace-section">
      <h3>3. 补全判断</h3>
      <ul>${replanHtml}</ul>
    </div>
    <div class="trace-section">
      <h3>4. 信息整合依据</h3>
      <ul>${obsHtml || "<li>暂无观察结果</li>"}</ul>
    </div>
  `;
}

function renderPayload(payload) {
  lastPayload = payload;
  renderWorkflow(payload.events || []);
  renderReasoning(payload);
  rawJson.textContent = JSON.stringify(payload, null, 2);
}

async function sendQuery(query) {
  setBusy(true);
  addMessage("user", query);
  workflowLog.className = "timeline";
  workflowLog.innerHTML = '<div class="log-item"><strong>请求已发送</strong><div>父 Agent 正在规划任务...</div></div>';
  reasoningTrace.className = "trace empty";
  reasoningTrace.textContent = "等待工作流事件生成";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, history }),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `HTTP ${response.status}`);
    }

    const payload = await response.json();
    addMessage("assistant", payload.answer || "未生成答案");
    history.push({ role: "user", content: query });
    history.push({ role: "assistant", content: payload.answer || "" });
    renderPayload(payload);
  } catch (error) {
    const message = `请求失败：${error.message}`;
    addMessage("assistant", message);
    workflowLog.innerHTML = `<div class="log-item"><strong class="error">执行失败</strong><div>${escapeHtml(message)}</div></div>`;
  } finally {
    setBusy(false);
    queryInput.focus();
  }
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (!query) return;
  queryInput.value = "";
  sendQuery(query);
});

clearBtn.addEventListener("click", () => {
  history = [];
  lastPayload = null;
  chatMessages.innerHTML = "";
  addMessage(
    "assistant",
    "你好，我可以帮你规划行程、查询路线天气、搜索实时攻略，也能结合 12306 查询铁路方案。",
  );
  workflowLog.className = "timeline empty";
  workflowLog.textContent = "等待任务开始";
  reasoningTrace.className = "trace empty";
  reasoningTrace.textContent = "等待工作流事件生成";
  rawJson.textContent = "{}";
});

async function copyText(text) {
  if (!text) return;
  await navigator.clipboard.writeText(text);
}

copyLogsBtn.addEventListener("click", () => {
  copyText(workflowLog.innerText);
});

copyTraceBtn.addEventListener("click", () => {
  copyText(reasoningTrace.innerText);
});
