/* AI-ассистент: чат по документам, источники, лог безопасности. */
(() => {
  const state = { me: null, busy: false, mePromise: null };
  const $ = (s, root = document) => root.querySelector(s);
  const esc = (s) => String(s ?? "");

  const PII_LABELS = {
    PERSON: "ФИО",
    PHONE: "телефон",
    EMAIL: "email",
    ORG: "организация",
    UNP: "УНП",
    PASSPORT: "паспорт",
    IBAN: "IBAN",
    CARD: "карта",
  };

  function initials(name) {
    return (name || "?")
      .split(/\s+/)
      .filter(Boolean)
      .map((x) => x[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }

  function fmtDate(iso) {
    const months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    if (!m) return String(iso || "");
    return `${+m[3]} ${months[+m[2] - 1]} ${m[1]}`;
  }

  async function loadMe() {
    try {
      const r = await fetch("/api/me", { credentials: "same-origin", cache: "no-store" });
      if (!r.ok) throw new Error("no-session");
      state.me = await r.json();
      window.APP_USER = state.me;
      const av = $("#meAvatar");
      if (av) {
        av.textContent = initials(state.me.name);
        av.title = `${state.me.name} · ${state.me.role_label}`;
      }
      const chip = $("#fpAiBtn .fp-role");
      if (chip) chip.textContent = state.me.role === "boss" ? "Директор" : state.me.dept;
    } catch {
      state.me = null;
      window.APP_USER = null;
      const av = $("#meAvatar");
      if (av) {
        av.textContent = "?";
        av.title = "Нет активной сессии";
      }
    }
  }

  function addMessage(role, text, opts = {}) {
    const log = $("#fpLog");
    const div = document.createElement("div");
    div.className = `fp-msg ${role}`;
    div.textContent = text;
    if (opts.tags) div.appendChild(opts.tags);
    if (opts.sources) div.appendChild(opts.sources);
    if (opts.security) div.appendChild(opts.security);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function addTyping() {
    const log = $("#fpLog");
    const div = document.createElement("div");
    div.className = "fp-msg a";
    div.innerHTML = '<span class="fp-typing"><i></i><i></i><i></i> <span>Думаю</span></span>';
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function sourceChips(sources) {
    if (!sources || !sources.length) return null;
    const wrap = document.createElement("div");
    wrap.className = "fp-meta";
    for (const s of sources) {
      const chip = document.createElement("span");
      chip.className = "fp-src";
      chip.title = `${s.title} · ${fmtDate(s.date)}`;
      const id = document.createElement("span");
      id.className = "id";
      id.textContent = s.id;
      chip.appendChild(id);
      chip.appendChild(document.createTextNode(` ${s.title} · ${fmtDate(s.date)}`));
      wrap.appendChild(chip);
    }
    return wrap;
  }

  function tagsBlock(data) {
    const wrap = document.createElement("div");
    wrap.className = "fp-meta";
    const mode = document.createElement("span");
    mode.className = `fp-tag ${data.used_llm ? "llm" : "local"}`;
    mode.textContent = data.used_llm ? "DeepSeek · ответ по документам" : "локальный ответ";
    wrap.appendChild(mode);

    const counts = Object.entries(data.pii_found || {}).filter(([, n]) => n > 0);
    if (counts.length) {
      const pii = document.createElement("span");
      pii.className = "fp-tag pii";
      pii.textContent = "ПДн замаскированы: " + counts.map(([k, n]) => `${PII_LABELS[k] || k} ×${n}`).join(", ");
      wrap.appendChild(pii);
    }
    return wrap;
  }

  function securityBlock(data) {
    if (!data.masked_preview) return null;
    const details = document.createElement("details");
    details.className = "fp-sec";
    const summary = document.createElement("summary");
    summary.textContent = "Что ушло во внешнюю модель";
    const pre = document.createElement("pre");
    pre.textContent = data.masked_preview;
    details.appendChild(summary);
    details.appendChild(pre);
    return details;
  }

  function showError(text) {
    addMessage("a err", text);
  }

  const ACTION_LABELS = {
    "assistant.ask": "Вопрос к ассистенту",
    "assistant.doc_denied": "Отказ в доступе к документу",
    "assistant.pii_block": "Блокировка запроса с ПДн",
    "assistant.rate_limited": "Превышен лимит запросов",
    "auth.qr": "Вход по QR",
    "auth.logout": "Выход",
    "doc.view": "Просмотр документа",
    "doc.access_denied": "Отказ в доступе",
  };

  function fmtTime(ts) {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return String(ts || "");
    return d.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  async function loadServerAudit() {
    const page = document.querySelector("#statPage");
    if (!page) return;
    const old = document.querySelector("#fpAuditCard");
    if (old) old.remove();
    try {
      const r = await fetch("/api/audit?limit=10", { credentials: "same-origin", cache: "no-store" });
      if (!r.ok) return;
      const data = await r.json();
      const card = document.createElement("div");
      card.id = "fpAuditCard";
      card.className = "glass card";
      card.style.marginTop = "16px";
      const title = document.createElement("h2");
      title.textContent = "Аудит ИИ";
      const note = document.createElement("div");
      note.className = "small muted";
      note.style.marginBottom = "6px";
      note.textContent = "Серверный журнал: только маскированные фрагменты, без сырых ПДн.";
      const list = document.createElement("div");
      list.className = "hl";
      for (const a of data.items || []) {
        const denied = /ОТКЛОН|отказ|denied/i.test(a.result || "");
        const icon = denied ? "lock" : String(a.action).startsWith("assistant") ? "auto_awesome" : String(a.action).startsWith("auth") ? "login" : "description";
        const row = document.createElement("div");
        row.className = "hli" + (denied ? " deny" : "");
        row.innerHTML = `<span class="ms">${icon}</span><div><div>${ACTION_LABELS[a.action] || a.action}</div><div class="hli-t">${a.result || ""}${a.obj ? " · " + a.obj : ""}</div></div><span class="hli-t">${fmtTime(a.ts)}</span>`;
        list.appendChild(row);
      }
      card.appendChild(title);
      card.appendChild(note);
      card.appendChild(list);
      page.appendChild(card);
    } catch {
      /* аудит не критичен для чата */
    }
  }

  function wrapShow() {
    if (typeof window.show !== "function" || window.show.__fpWrapped) return;
    const original = window.show;
    window.show = function (v) {
      const result = original.apply(this, arguments);
      if (v === "stats") setTimeout(loadServerAudit, 0);
      return result;
    };
    window.show.__fpWrapped = true;
  }

  async function ask(text) {
    const q = String(text || "").trim();
    if (!q || state.busy) return;
    await state.mePromise;
    if (!state.me) {
      showError("Нет активной сессии. Откройте QR-ссылку и обновите страницу.");
      return;
    }
    state.busy = true;
    $("#fpSend").disabled = true;
    $("#fpSugg").style.display = "none";
    addMessage("u", q);
    const typing = addTyping();
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 45000);
      const response = await fetch("/api/assistant/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ q }),
        signal: controller.signal,
      });
      clearTimeout(timer);
      let data = {};
      try {
        data = await response.json();
      } catch {
        data = {};
      }
      typing.remove();
      if (!response.ok) {
        const detail = data.detail || `Ошибка ${response.status}`;
        showError(detail);
        return;
      }
      const msg = addMessage("a", data.answer || "Пустой ответ", {
        tags: tagsBlock(data),
        sources: sourceChips(data.sources),
        security: securityBlock(data),
      });
      msg.dataset.answer = "1";
    } catch (e) {
      typing.remove();
      showError(e && e.name === "AbortError" ? "Модель отвечает слишком долго. Попробуйте ещё раз." : "Сервер недоступен. Проверьте соединение.");
    } finally {
      state.busy = false;
      $("#fpSend").disabled = false;
    }
  }

  function suggestions() {
    if (!state.me) return [];
    const a = new Set(state.me.acls || []);
    const list = [
      { label: "SLA поддержки", q: "Какой SLA первого ответа поддержки за октябрь?" },
      { label: "Правила ИБ", q: "Что говорит инструкция по информационной безопасности о персональных данных?" },
    ];
    if (a.has("prod")) list.push({ label: "Загрузка мощностей", q: "Какая загрузка мощностей на неделю 48?" });
    if (a.has("mkt")) list.push({ label: "Прогноз спроса", q: "Какой прогноз спроса на декабрь?" });
    if (a.has("support")) list.push({ label: "Скрипты поддержки", q: "Что делать, если клиент спрашивает «где мой заказ»?" });
    if (a.has("fin")) list.push({ label: "Финплан 2027", q: "Что в D-12?" });
    list.push({
      label: "Пример с ПДн",
      q: "Позвонить Ивану Иванову на +375291112233 по вопросу доставки, что говорит регламент?",
      demo: true,
    });
    return list.slice(0, 5);
  }

  function renderSuggestions() {
    const box = $("#fpSugg");
    box.innerHTML = "";
    for (const s of suggestions()) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = s.label;
      b.title = s.q;
      if (s.demo) b.className = "demo";
      b.addEventListener("click", () => ask(s.q));
      box.appendChild(b);
    }
    box.style.display = "flex";
  }

  function greeting() {
    const name = state.me ? state.me.name.split(/\s+/)[0] : "";
    if (!state.me) {
      addMessage("a", "Нет активной сессии. Откройте QR-ссылку от организатора и обновите страницу.");
      return;
    }
    addMessage(
      "a",
      `Привет, ${name}! Спросите по документам. Я показываю источники и не отправляю сырые персональные данные во внешнюю модель.`
    );
  }

  function openPanel() {
    const panel = $("#fpAi");
    panel.hidden = false;
    $("#fpAiBtn").style.display = "none";
    $("#fpAiBtn").setAttribute("aria-expanded", "true");
    setTimeout(() => $("#fpInput").focus(), 50);
  }

  function closePanel() {
    const panel = $("#fpAi");
    panel.hidden = true;
    $("#fpAiBtn").style.display = "";
    $("#fpAiBtn").setAttribute("aria-expanded", "false");
  }

  function build() {
    const btn = document.createElement("button");
    btn.id = "fpAiBtn";
    btn.type = "button";
    btn.setAttribute("aria-label", "Открыть ассистента");
    btn.setAttribute("aria-expanded", "false");
    btn.innerHTML = '<span class="spark">✦</span><span>Ассистент</span><span class="fp-role"></span>';
    document.body.appendChild(btn);

    const panel = document.createElement("section");
    panel.id = "fpAi";
    panel.className = "fp-ai";
    panel.hidden = true;
    panel.setAttribute("aria-label", "AI-ассистент");
    panel.innerHTML = `
      <div class="fp-ai-head">
        <span class="spark">✦</span>
        <div><b>Ассистент</b><div class="fp-sub">по документам · с источниками</div></div>
        <div class="spacer"></div>
        <button class="fp-icon" id="fpClose" type="button" aria-label="Закрыть">✕</button>
      </div>
      <div class="fp-ai-log" id="fpLog" role="log" aria-live="polite"></div>
      <div class="fp-sugg" id="fpSugg"></div>
      <form class="fp-form" id="fpForm" autocomplete="off">
        <input id="fpInput" placeholder="Спросите по документам…" aria-label="Вопрос ассистенту" maxlength="2000">
        <button id="fpSend" type="submit" aria-label="Отправить">→</button>
      </form>
      <div class="fp-foot">Внешняя модель видит только обезличенный текст. Сырые ПДн остаются на сервере.</div>`;
    document.body.appendChild(panel);

    btn.addEventListener("click", () => (panel.hidden ? openPanel() : closePanel()));
    $("#fpClose").addEventListener("click", closePanel);
    $("#fpForm").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = $("#fpInput");
      const v = input.value;
      input.value = "";
      ask(v);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !panel.hidden && !document.querySelector("#scrim.on")) closePanel();
    });

    state.mePromise = loadMe().then(() => {
      greeting();
      renderSuggestions();
    });
    wrapShow();
    if (document.querySelector("#v-stats") && document.querySelector("#v-stats").classList.contains("on")) {
      setTimeout(loadServerAudit, 0);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
