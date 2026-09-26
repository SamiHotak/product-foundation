/**
 * Theme choice: light, dark, or "system" (same as the device).
 *
 * No JavaScript runs before the first paint:
 * - "system": no class on <html>; CSS follows the device (prefers-color-scheme in globals.css).
 * - "light" / "dark": saved in a cookie; the server renders <html class="dark"> (or "light").
 * So the page never flashes the wrong colors, and React never renders a <script> tag.
 */

export type Theme = "light" | "dark" | "system";

export const THEMES: readonly Theme[] = ["light", "dark", "system"];

export const THEME_COOKIE = "theme";

/** Any cookie value -> a valid theme ("system" if missing or unknown). */
export function parseTheme(value: string | undefined | null): Theme {
  return THEMES.includes(value as Theme) ? (value as Theme) : "system";
}

/** Class for <html>: none for "system" (CSS decides from the device setting). */
export function themeClass(theme: Theme): string | undefined {
  return theme === "system" ? undefined : theme;
}
