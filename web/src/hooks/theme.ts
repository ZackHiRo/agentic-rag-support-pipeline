import { useCallback, useEffect, useState } from "react";

export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("evd-theme", dark ? "dark" : "light");
    } catch {
      /* storage unavailable: theme just won't persist */
    }
  }, [dark]);
  const toggle = useCallback(() => setDark((d) => !d), []);
  return { dark, toggle };
}

export function useDebounced<T>(value: T, ms = 200): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}
