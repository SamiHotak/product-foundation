"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";

import { THEME_COOKIE, type Theme } from "@/lib/theme";

type ThemeContextValue = {
  /** What the user picked: light, dark, or same as the device. */
  theme: Theme;
  /** What is shown right now ("system" resolved to light or dark). */
  resolvedTheme: "light" | "dark";
  setTheme: (theme: Theme) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

const DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribeDevice(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

const deviceIsDark = () => window.matchMedia(DARK_QUERY).matches;

/** Switch the <html> class without animating every color on the page. */
function applyTheme(theme: Theme) {
  const root = document.documentElement;
  const style = document.createElement("style");
  style.textContent = "*,*::before,*::after{transition:none!important}";
  document.head.appendChild(style);
  root.classList.remove("light", "dark");
  if (theme !== "system") root.classList.add(theme);
  void window.getComputedStyle(document.body).opacity; // flush styles
  setTimeout(() => style.remove(), 0);
}

/**
 * Light / dark / same-as-device theme.
 * `initialTheme` comes from the cookie, read by the server in app/layout.tsx.
 */
export function ThemeProvider({
  initialTheme,
  children,
}: {
  initialTheme: Theme;
  children: React.ReactNode;
}) {
  const [theme, setThemeState] = useState<Theme>(initialTheme);
  const deviceDark = useSyncExternalStore(subscribeDevice, deviceIsDark, () => false);
  const resolvedTheme = theme === "system" ? (deviceDark ? "dark" : "light") : theme;

  const setTheme = useCallback((next: Theme) => {
    // One year; the server reads it on the next page load (no flash).
    document.cookie = `${THEME_COOKIE}=${next}; path=/; max-age=31536000; samesite=lax`;
    applyTheme(next);
    setThemeState(next);
  }, []);

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme }),
    [theme, resolvedTheme, setTheme],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** Read and change the theme from any client component. */
export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside <ThemeProvider>.");
  return value;
}
