const pageMeta = {
  login: ["身份与权限", "登录"],
  dashboard: ["经营监控", "经营驾驶舱"],
  chat: ["可信 ChatBI", "智能问数"],
  evidence: ["运行证据", "证据面板"],
  anomalies: ["诊断与归因", "异常中心"],
  metrics: ["语义治理", "指标中心"],
  runs: ["审计与复现", "分析记录"]
};

const stateCopy = {
  empty: ["暂无可展示数据", "当前筛选范围内没有质量通过的模拟数据。请调整时间或范围。"],
  error: ["运行失败", "本次运行未成功，最近成功结果不会被覆盖。错误追踪：run_demo_failed_001。"],
  delayed: ["数据刷新延迟", "计划数据时间为 2026-06-30 23:59，当前最近成功数据截至 2026-06-29 23:59。"],
  unauthorized: ["无权限访问", "当前角色无权查看该区域或对象。系统不会披露对象名称、数量或是否存在。"]
};

const nav = document.getElementById("page-nav");
const title = document.getElementById("page-title");
const eyebrow = document.getElementById("page-eyebrow");
const content = document.getElementById("page-content");
const stateSelect = document.getElementById("state-select");
const stateMessage = document.getElementById("state-message");
const drawer = document.getElementById("evidence-drawer");
const backdrop = document.getElementById("drawer-backdrop");

function showPage(page) {
  document.querySelectorAll("[data-page]").forEach((button) => button.classList.toggle("active", button.dataset.page === page));
  document.querySelectorAll("[data-view]").forEach((view) => view.classList.toggle("active", view.dataset.view === page));
  eyebrow.textContent = pageMeta[page][0];
  title.textContent = pageMeta[page][1];
  applyState(stateSelect.value);
}

function applyState(state) {
  stateMessage.className = "state-message hidden";
  content.classList.remove("content-muted");
  if (state === "normal") return;
  const copy = stateCopy[state];
  stateMessage.innerHTML = `<h2>${copy[0]}</h2><p>${copy[1]}</p>`;
  stateMessage.className = `state-message ${state}`;
  content.classList.add("content-muted");
}

function openDrawer() {
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  backdrop.classList.remove("hidden");
}

function closeDrawer() {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  backdrop.classList.add("hidden");
}

nav.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-page]");
  if (button) showPage(button.dataset.page);
});
stateSelect.addEventListener("change", (event) => applyState(event.target.value));
document.getElementById("open-evidence").addEventListener("click", openDrawer);
document.getElementById("close-evidence").addEventListener("click", closeDrawer);
backdrop.addEventListener("click", closeDrawer);
document.querySelectorAll(".evidence-link").forEach((button) => button.addEventListener("click", openDrawer));
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
