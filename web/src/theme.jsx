import { useEffect, useState } from "react";

export const THEMES = [
  { key: "loom", label: "⟐ loom" },
  { key: "grimoire", label: "☙ grimoire" },
  { key: "glass", label: "◈ nightglass" },
];

export function useTheme() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem("fw-theme") || "loom");
  useEffect(() => {
    const el = document.documentElement;
    THEMES.forEach((t) => el.classList.remove(`theme-${t.key}`));
    el.classList.add(`theme-${theme}`);
    localStorage.setItem("fw-theme", theme);
  }, [theme]);
  return [theme, setTheme];
}

export function ThemePicker({ theme, setTheme }) {
  return (
    <span className="themes">
      {THEMES.map((t) => (
        <button key={t.key} className={`theme-chip ${theme === t.key ? "sel" : ""}`}
          onClick={() => setTheme(t.key)} title={`Switch to the ${t.key} look`}>
          {t.label}
        </button>
      ))}
    </span>
  );
}
