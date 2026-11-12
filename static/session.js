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
      const r = await fetch("/api/bootstrap", { credentials: "same-origin", cache: "no-store" });
      if (!r.ok) return;
      const boot = await r.json();
      const user = boot.user;
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

      // Один запрос уже содержит выжимки, задачи и аудит.
      try {
        (boot.meetings || []).forEach((item) => {
          if (typeof AI_MEETINGS !== "undefined") AI_MEETINGS[item.event_id] = item;
          if (typeof AI_LOADED !== "undefined") AI_LOADED.add(item.event_id);
          if (typeof ensureMeetingFromAI === "function") ensureMeetingFromAI(item);
        });
        // Bootstrap уже вернул все выжимки — отдельные запросы по встречам не нужны.
        window.AI_BOOTED = true;
        if (typeof MEETING_TASKS !== "undefined") MEETING_TASKS = boot.tasks || [];
        if (typeof addServerTask === "function") {
          (boot.tasks || []).forEach((item) => addServerTask(item));
        }
        window.SERVER_AUDIT = boot.audit || [];
        if (typeof mergeServerAudit === "function") mergeServerAudit(boot.audit || []);
        if (typeof refresh === "function") refresh(true);
      } catch {
        /* без бэкенда */
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
      /* статическая страница без бэкенда */
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
