"use client";

import { useEffect, useState } from "react";
import Icon from "./Icons";

type Theme = "dark" | "light";

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => {
    try {
      if (window.localStorage.getItem("theme") === "light") setTheme("light");
    } catch {
      /* storage can be blocked; dark is the default */
    }
  }, []);

  const choose = (next: Theme) => {
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      if (next === "light") window.localStorage.setItem("theme", "light");
      else window.localStorage.removeItem("theme");
    } catch {
      /* ignore */
    }
  };

  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" className="theme-button" onClick={() => choose(next)} aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}>
      <Icon name={theme === "dark" ? "sun" : "moon"} size={15} />
    </button>
  );
}
