try {
  document.documentElement.dataset.theme =
    localStorage.getItem("clans-theme") || "dark";
} catch {
  /* The default theme works when storage is unavailable. */
}
