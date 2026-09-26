/**
 * Theme (light / dark / system), shared by the early script and the React provider.
 *
 * The script below runs BEFORE the page is painted, so dark mode never flashes white.
 * It is an inline <script> in the <head> of app/layout.tsx (a server component).
 * Do not move it into a client component: React warns about rendering <script> there.
 * (next/script "beforeInteractive" is not an option: in the App Router it runs too late.)
 */

export type Theme = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "theme";

export const THEMES: readonly Theme[] = ["light", "dark", "system"];

/** Inline JS: read the saved choice, resolve "system", set the class on <html>. */
export const themeInitScript = `(function(){try{
var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
if(t!=="light"&&t!=="dark")t="system";
var d=t==="dark"||(t==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);
var c=document.documentElement.classList;c.toggle("dark",d);c.toggle("light",!d);
}catch(e){}})();`;
