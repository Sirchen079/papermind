import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
export type Brand = "warm" | "blue";
const KEY = "papermind-theme";
const BRAND_KEY = "papermind-brand";

function readInitial(): Theme {
  if (typeof document !== "undefined" && document.documentElement.classList.contains("dark")) {
    return "dark";
  }
  return "light";
}

/** Theme toggle backed by the `.dark` class on <html> + localStorage. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readInitial);
  const [brand, setBrand] = useState<Brand>(() =>
    document.documentElement.dataset.brand === 'warm' ? 'warm' : 'blue');

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* ignore quota / privacy mode */
    }
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.brand = brand;
    try { localStorage.setItem(BRAND_KEY, brand); } catch { /* optional preference */ }
  }, [brand]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  const toggleBrand = useCallback(() => setBrand(value => value === 'warm' ? 'blue' : 'warm'), []);
  return { theme, toggle, brand, toggleBrand };
}
