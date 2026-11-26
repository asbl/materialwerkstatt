const THEME_KEY = "material-ui:theme";
const THEMES = ["light", "system", "dark"];

export function createThemeController() {
  function stored() {
    try {
      return localStorage.getItem(THEME_KEY) || "system";
    } catch {
      return "system";
    }
  }

  function apply(theme) {
    theme = THEMES.includes(theme) ? theme : "system";
    document.documentElement.dataset.theme = theme === "system" ? "" : theme;
    document.querySelectorAll("#themeToggle [data-theme-option]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.themeOption === theme));
    });
  }

  function select(theme) {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      // Die UI funktioniert auch ohne persistierte Browser-Praeferenz.
    }
    apply(theme);
    return theme;
  }

  function init() {
    apply(stored());
    document.querySelectorAll("#themeToggle [data-theme-option]").forEach((button) => {
      button.addEventListener("click", () => select(button.dataset.themeOption));
    });
  }

  return { init, select, apply };
}
