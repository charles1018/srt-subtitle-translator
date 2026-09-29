// SRT 字幕翻譯器前端：畫面狀態與事件處理；所有規則與存檔都在 Rust 端（invoke）。
"use strict";

const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

const $ = (id) => document.getElementById(id);

const state = {
  files: [],
  running: false,
  paused: false,
  stopping: false,
  version: "",
  ready: false,
};

// ─── 小工具 ────────────────────────────────────────────────

function fillSelect(select, options, value) {
  select.replaceChildren(
    ...options.map((opt) => {
      const [val, label, title] = Array.isArray(opt) ? opt : [opt, opt];
      const o = document.createElement("option");
      o.value = val;
      o.textContent = label;
      if (title) o.title = title;
      return o;
    })
  );
  if (value !== undefined) select.value = value;
}

let toastTimer;
function toast(text, warn = false) {
  const el = $("toast");
  el.textContent = text;
  el.classList.toggle("warn", warn);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), warn ? 5000 : 3000);
}

/** 顯示訊息對話框；buttons 為 [值, 文字, 樣式?]，回傳使用者按下的值（Esc 為 "cancel"）。 */
function ask(title, body, buttons = [["ok", "確定", "primary"]]) {
  const dialog = $("message-dialog");
  $("message-title").textContent = title;
  $("message-body").textContent = body;
  $("message-buttons").replaceChildren(
    ...buttons.map(([value, label, cls]) => {
      const b = document.createElement("button");
      b.value = value;
      b.textContent = label;
      if (cls) b.className = cls;
      return b;
    })
  );
  return new Promise((resolve) => {
    dialog.returnValue = "cancel";
    dialog.addEventListener("close", () => resolve(dialog.returnValue || "cancel"), { once: true });
    dialog.showModal();
    dialog.querySelector(".primary")?.focus();
  });
}

const alertBox = (title, body) => ask(title, body);
const confirmBox = async (title, body) =>
  (await ask(title, body, [["cancel", "取消"], ["ok", "確定", "primary"]])) === "ok";

function setStatus(text, kind = "normal") {
  $("status-text").textContent = text;
  $("status").dataset.state = kind;
}

function setProgress(percent) {
  $("progress-fill").style.width = `${percent}%`;
  $("progress").setAttribute("aria-valuenow", String(percent));
  $("percent").textContent = `${percent}%`;
}

function currentSettings() {
  return {
    source_lang: $("source-lang").value,
    target_lang: $("target-lang").value,
    llm_type: $("llm-type").value,
    model_name: $("model").value,
    parallel_requests: $("parallel").value,
    display_mode: $("display-mode").value,
    netflix_style_enabled: $("netflix").checked,
    structure_text_enabled: $("structure").checked,
  };
}

// ─── 檔案列表 ──────────────────────────────────────────────

function renderFiles() {
  const list = $("file-list");
  list.replaceChildren(
    ...state.files.map((path, i) => {
      const li = document.createElement("li");
      li.title = path;
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = path.split(/[\\/]/).pop();
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "remove";
      remove.textContent = "✕";
      remove.title = "從列表移除";
      remove.dataset.lock = "";
      remove.disabled = state.running;
      remove.addEventListener("click", () => {
        state.files.splice(i, 1);
        renderFiles();
      });
      li.append(name, remove);
      return li;
    })
  );
  $("file-empty").hidden = state.files.length > 0;
  $("file-count").textContent = `已選擇 ${state.files.length} 個檔案`;
}

/** 展開路徑（資料夾遞迴）並加入列表，回傳新加入的數量。 */
async function addPaths(paths) {
  if (!paths.length) return { added: 0, found: 0 };
  const result = await invoke("add_paths", { paths });
  let added = 0;
  for (const f of result.files) {
    if (!state.files.includes(f)) {
      state.files.push(f);
      added += 1;
    }
  }
  for (const bad of result.unsupported) {
    toast(`${bad.split(/[\\/]/).pop()} 不是支援的字幕格式，已略過`, true);
  }
  renderFiles();
  return { added, found: result.files.length };
}

async function pickFiles() {
  if (state.running) return;
  const paths = await invoke("pick_files");
  await addPaths(paths);
}

async function pickFolder() {
  if (state.running) return;
  const folder = await invoke("pick_folder");
  if (!folder) return;
  const { found } = await addPaths([folder]);
  toast(found ? `在資料夾中找到 ${found} 個字幕檔案` : "在選中的資料夾中未找到任何字幕檔案", !found);
}

// ─── 模型列表 ──────────────────────────────────────────────

let modelRequest = 0;
async function loadModels() {
  const llm = $("llm-type").value;
  const ticket = ++modelRequest;
  fillSelect($("model"), ["載入中..."]);
  try {
    const { models, selected } = await invoke("list_models", { llmType: llm });
    // llama-server 回報的 id 可能是完整路徑：顯示檔名，值維持原樣（與 Python 送出相同的 model 名稱）
    const options = models.map((m) => [m, m.split(/[\\/]/).pop(), m]);
    if (ticket === modelRequest) fillSelect($("model"), options, selected);
  } catch (e) {
    if (ticket === modelRequest) fillSelect($("model"), ["無法載入模型"]);
    console.error(e);
  }
}

// ─── 翻譯流程 ──────────────────────────────────────────────

function lockControls(locked) {
  document.querySelectorAll("[data-lock]").forEach((el) => (el.disabled = locked));
  $("btn-start").disabled = locked;
  $("btn-pause").disabled = !locked;
  $("btn-stop").disabled = !locked;
  $("btn-pause").textContent = "⏸ 暫停";
  $("btn-pause").classList.remove("paused");
}

async function start() {
  if (state.running || $("btn-start").disabled) return;
  if (!state.files.length) {
    await alertBox("警告", "請先選擇要翻譯的檔案");
    return;
  }
  $("btn-start").disabled = true;
  setStatus("正在檢查模型連線…", "running");
  try {
    await invoke("start_translation", { files: [...state.files], settings: currentSettings() });
  } catch (e) {
    $("btn-start").disabled = false;
    setStatus("準備就緒");
    await alertBox("錯誤", String(e));
    return;
  }
  state.running = true;
  state.paused = false;
  state.stopping = false;
  lockControls(true);
  renderFiles();
  setProgress(0);
  $("results").replaceChildren();
  setStatus(`正在翻譯 ${state.files.length} 個檔案...`, "running");
  $("total-files").textContent = `總進度: 0/${state.files.length} 檔案完成`;
}

async function togglePause() {
  if (!state.running || state.stopping) return;
  state.paused = !state.paused;
  await invoke(state.paused ? "pause" : "resume");
  $("btn-pause").textContent = state.paused ? "▶ 繼續" : "⏸ 暫停";
  $("btn-pause").classList.toggle("paused", state.paused);
  setStatus(state.paused ? "已暫停（進行中的批次完成後暫停）" : "翻譯中...", state.paused ? "paused" : "running");
}

async function stop() {
  if (!state.running || state.stopping) return;
  state.stopping = true;
  $("btn-pause").disabled = true;
  $("btn-stop").disabled = true;
  setStatus("正在停止…", "paused");
  await invoke("stop");
}

function beep() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.35);
  } catch (e) {
    console.warn("無法播放提示音", e);
  }
}

function listenRunEvents() {
  listen("file-started", ({ payload }) => {
    $("current-file").textContent = `目前檔案（${payload.index}/${payload.total}）：${payload.name}`;
    setProgress(0);
  });

  listen("progress", ({ payload }) => {
    setProgress(payload.percent);
    if (!state.paused && !state.stopping) setStatus(payload.status, "running");
  });

  listen("file-finished", ({ payload }) => {
    const msg = payload.message;
    const kind = msg.startsWith("翻譯完成") ? "success" : msg.startsWith("翻譯部分完成") ? "partial" : "error";
    if (!state.paused && !state.stopping) setStatus(msg, kind === "partial" ? "paused" : kind);
    $("total-files").textContent = `總進度: ${payload.completed}/${payload.total} 檔案完成`;
    const li = document.createElement("li");
    li.textContent = msg.split(" | 總進度:")[0];
    li.className = kind;
    $("results").append(li);
    li.scrollIntoView({ block: "nearest" });
  });

  listen("conflict", async ({ payload }) => {
    const choice = await ask(
      "檔案已存在",
      `檔案 ${payload.path} 已存在。\n要覆蓋、重新命名，還是略過這個檔案？`,
      [["skip", "略過"], ["rename", "重新命名"], ["overwrite", "覆蓋", "primary"]]
    );
    await invoke("resolve_conflict", { choice: choice === "cancel" ? "skip" : choice });
  });

  listen("run-finished", async ({ payload }) => {
    state.running = false;
    state.paused = false;
    state.stopping = false;
    lockControls(false);
    renderFiles();
    $("current-file").textContent = "";
    if (payload.error) {
      setStatus("翻譯失敗", "error");
      await alertBox("錯誤", payload.error);
    } else if (payload.stopped) {
      setProgress(0);
      setStatus(`已停止（完成 ${payload.completed}/${payload.total} 個檔案）`);
    } else if (payload.playSound) {
      beep();
    }
  });
}

// ─── 提示詞編輯器 ──────────────────────────────────────────

async function loadPrompt() {
  $("prompt-text").value = await invoke("prompt_get", {
    llmType: $("prompt-llm-type").value,
    contentType: $("prompt-content-type").value,
  });
}

async function openPromptEditor() {
  $("prompt-content-type").value = $("content-type").value;
  await loadPrompt();
  $("prompt-dialog").showModal();
}

async function savePrompt() {
  const llmType = $("prompt-llm-type").value;
  const contentType = $("prompt-content-type").value;
  try {
    await invoke("prompt_save", { llmType, contentType, text: $("prompt-text").value.trim() });
    toast(`已成功儲存 ${contentType} 類型的 ${llmType} 提示詞`);
  } catch (e) {
    await alertBox("錯誤", String(e));
  }
}

async function resetPrompt() {
  const llmType = $("prompt-llm-type").value;
  const contentType = $("prompt-content-type").value;
  if (!(await confirmBox("確認重置", `確定要將 ${contentType} 類型的 ${llmType} 提示詞重置為預設值嗎？`))) return;
  await invoke("prompt_reset", { llmType, contentType });
  await loadPrompt();
  toast("已重置為預設提示詞");
}

// ─── 說明 ─────────────────────────────────────────────────

const HELP_TEXT = `1. 選擇檔案：點擊「選擇檔案」按鈕，或直接把字幕檔案、資料夾拖放到列表中。
2. 設定翻譯參數：選擇來源語言、目標語言、LLM 類型和模型。
3. 設定內容類型和翻譯風格：根據字幕內容選擇合適的類型和風格。
4. 設定顯示模式：選擇如何顯示原文和翻譯。
   - 雙語對照：原文和翻譯同時顯示（原文在上，翻譯在下）
   - 僅顯示翻譯：只顯示翻譯文本
   - 翻譯在上：翻譯在上，原文在下
   - 原文在上：原文在上，翻譯在下
5. 點擊「開始翻譯」按鈕開始翻譯過程。
6. 翻譯過程中可以暫停或停止（停止後不會寫出未完成的檔案）。
7. 可以在「提示詞編輯」自訂提示詞。

支援的檔案格式：`;

// ─── 初始化 ────────────────────────────────────────────────

async function init() {
  // 最先註冊：即使初始化失敗也要能關閉視窗（此時不存設定，避免寫入空白值）
  listen("close-requested", async () => {
    if (state.running && !(await confirmBox("確認", "正在進行翻譯，確定要關閉程式嗎？"))) return;
    await invoke("save_and_quit", { settings: state.ready ? currentSettings() : null });
  });
  const data = await invoke("init");
  state.version = data.version;
  const s = data.settings;
  fillSelect($("source-lang"), data.sourceLangs, s.source_lang);
  fillSelect($("target-lang"), data.targetLangs, s.target_lang);
  fillSelect($("llm-type"), data.llmTypes, s.llm_type);
  fillSelect($("parallel"), data.parallelOptions, s.parallel_requests);
  fillSelect($("display-mode"), data.displayModes, s.display_mode);
  fillSelect($("content-type"), data.contentTypes, data.contentType);
  fillSelect($("style"), data.styles.map(([id, desc]) => [id, id, desc]), data.style);
  fillSelect($("prompt-content-type"), data.contentTypes, data.contentType);
  fillSelect($("prompt-llm-type"), data.llmTypes, "llamacpp");
  $("netflix").checked = s.netflix_style_enabled;
  $("structure").checked = s.structure_text_enabled;
  state.extensions = data.extensions;
  renderFiles();
  loadModels();

  const onLanguage = async () => {
    const source = $("source-lang").value;
    const target = $("target-lang").value;
    if (!(await invoke("set_language", { source, target }))) {
      toast(`不支援的語言對組合：${source}→${target}（提示詞仍沿用上一個語言對）`, true);
    }
  };
  $("source-lang").addEventListener("change", onLanguage);
  $("target-lang").addEventListener("change", onLanguage);
  $("llm-type").addEventListener("change", loadModels);
  $("content-type").addEventListener("change", (e) => invoke("set_content_type", { value: e.target.value }));
  $("style").addEventListener("change", (e) => invoke("set_style", { value: e.target.value }));
  $("display-mode").addEventListener("change", (e) =>
    invoke("set_option", { key: "display_mode", value: e.target.value })
  );
  $("netflix").addEventListener("change", (e) =>
    invoke("set_option", { key: "netflix_style_enabled", value: e.target.checked })
  );
  $("structure").addEventListener("change", (e) =>
    invoke("set_option", { key: "structure_text_enabled", value: e.target.checked })
  );

  $("btn-files").addEventListener("click", pickFiles);
  $("btn-folder").addEventListener("click", pickFolder);
  $("btn-clear").addEventListener("click", () => {
    state.files = [];
    renderFiles();
  });
  $("btn-start").addEventListener("click", start);
  $("btn-pause").addEventListener("click", togglePause);
  $("btn-stop").addEventListener("click", stop);

  $("btn-prompt").addEventListener("click", openPromptEditor);
  $("prompt-content-type").addEventListener("change", loadPrompt);
  $("prompt-llm-type").addEventListener("change", loadPrompt);
  $("prompt-save").addEventListener("click", savePrompt);
  $("prompt-reset").addEventListener("click", resetPrompt);
  $("prompt-close").addEventListener("click", () => $("prompt-dialog").close());
  $("btn-help").addEventListener("click", () =>
    alertBox("使用說明", HELP_TEXT + state.extensions.map((e) => e.toUpperCase()).join(", "))
  );
  $("btn-about").addEventListener("click", () =>
    alertBox(
      "關於",
      `SRT 字幕翻譯器 V${state.version}（Rust 版）\n\n` +
        "使用大型語言模型（LLM）翻譯字幕，支援多種語言和翻譯風格。\n" +
        "可以使用本地模型（llama.cpp）或雲端 API（OpenAI / Google）進行翻譯。"
    )
  );

  document.addEventListener("keydown", (e) => {
    if (document.querySelector("dialog[open]")) return;
    if (e.ctrlKey && e.key.toLowerCase() === "o") {
      e.preventDefault();
      pickFiles();
    } else if (e.ctrlKey && e.key === "Enter") {
      e.preventDefault();
      start();
    } else if (e.key === "Escape") {
      stop();
    }
  });

  listen("drag-hover", ({ payload }) => $("drop-zone").classList.toggle("hover", payload && !state.running));
  listen("paths-dropped", async ({ payload }) => {
    if (state.running) return;
    const { added } = await addPaths(payload);
    if (added) toast(`已新增 ${added} 個字幕檔案`);
  });
  listenRunEvents();
  state.ready = true;
}

init().catch((e) => {
  setStatus(`初始化失敗：${e}`, "error");
  console.error(e);
});
