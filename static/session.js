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
      const avatar = document.querySelector("#meAvatar");
      if (avatar) {
        avatar.textContent = initials(user.name);
        avatar.title = user.is_impersonating
          ? `${user.name} · просмотр из аккаунта ${user.real_name}`
          : `${user.name} · ${user.role_label}`;
      }
    } catch {
      /* статическая демонстрация без бэкенда */
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
