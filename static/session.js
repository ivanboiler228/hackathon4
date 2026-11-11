/* Только данные сессии: внешний вид интерфейса не меняется. */
(() => {
  const initials = (name) =>
    (name || "?")
      .split(/\s+/)
      .filter(Boolean)
      .map((x) => x[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();

  async function load() {
    try {
      const r = await fetch("/api/me", { credentials: "same-origin", cache: "no-store" });
      if (!r.ok) return;
      const user = await r.json();
      window.APP_USER = user;

      // Применяем роль к клиентским данным, не меняя сам дизайн.
      try {
        const roleKey = user.id === "anna" ? "director" : user.id === "igor" ? "prod" : user.id;
        if (typeof ROLES !== "undefined") {
          if (!ROLES[roleKey]) {
            ROLES[roleKey] = { me: user.id, label: user.role_label, access: user.acls };
          }
          ROLES[roleKey].access = user.acls;
          ROLE = roleKey;
          if (typeof refresh === "function") refresh();
          if (typeof log === "function") log("Вход в систему", "сессия", "роль: " + user.role_label);
        }
      } catch {
        /* если страница открыта без основного скрипта */
      }

      // Подтягиваем серверные выжимки, задачи и аудит, чтобы данные не терялись после перезагрузки.
      try {
        const [mr, tr, ar] = await Promise.all([
          fetch("/api/meetings/ai", { credentials: "same-origin", cache: "no-store" }),
          fetch("/api/tasks", { credentials: "same-origin", cache: "no-store" }),
          fetch("/api/audit?limit=100", { credentials: "same-origin", cache: "no-store" }),
        ]);
        if (mr.ok) {
          const data = await mr.json();
          (data.items || []).forEach((item) => {
            if (typeof AI_MEETINGS !== "undefined") AI_MEETINGS[item.event_id] = item;
            if (typeof AI_LOADED !== "undefined") AI_LOADED.add(item.event_id);
            if (typeof ensureMeetingFromAI === "function") ensureMeetingFromAI(item);
          });
        }
        if (tr.ok) {
          const data = await tr.json();
          if (typeof MEETING_TASKS !== "undefined") MEETING_TASKS = data.items || [];
          if (typeof addServerTask === "function") {
            (data.items || []).forEach((item) => addServerTask(item));
          }
        }
        if (ar.ok) {
          const data = await ar.json();
          window.SERVER_AUDIT = data.items || [];
          if (typeof mergeServerAudit === "function") mergeServerAudit(data.items || []);
        }
        if (typeof refresh === "function") refresh(true);
      } catch {
        /* демо без бэкенда */
      }

      // Какая модель реально подключена — показываем в интерфейсе без хардкода.
      try {
        const hr = await fetch("/health", { credentials: "same-origin", cache: "no-store" });
        if (hr.ok) {
          const health = await hr.json();
          window.LLM_INFO = {
            provider: health.llm?.provider || "DeepSeek",
            model: health.llm?.model || "deepseek-chat",
            stt: health.stt?.model || "Vosk",
          };
          if (typeof refresh === "function") refresh(true);
        }
      } catch {
        /* health недоступен */
      }

      const avatar = document.querySelector("#meAvatar");
      if (avatar) {
        avatar.textContent = initials(user.name);
        avatar.title = user.is_impersonating
          ? `${user.name} · просмотр из аккаунта ${user.real_name}`
          : `${user.name} · ${user.role_label}`;
      }

      if (window.innerWidth <= 900) {
        setTimeout(() => {
          const day = document.querySelector('#rangeSeg button[data-days="1"]');
          if (day) day.click();
        }, 0);
      }
      setTimeout(focusActiveTab, 120);
    } catch {
      /* статическая демонстрация без бэкенда */
    }
  }

  function focusActiveTab() {
    if (window.innerWidth > 900) return;
    const nav = document.querySelector("#nav");
    const active = nav && nav.querySelector("a.active");
    if (!nav || !active) return;
    const nr = nav.getBoundingClientRect();
    const ar = active.getBoundingClientRect();
    if (ar.left < nr.left + 6 || ar.right > nr.right - 6) {
      nav.scrollLeft += ar.left - nr.left - 8;
    }
  }

  const navEl = document.querySelector("#nav");
  if (navEl) {
    navEl.addEventListener("click", () => setTimeout(focusActiveTab, 30));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
