/**
 * Where to go after signing in. Only paths inside this app are allowed, never another
 * website (the backend checks the same for Google sign-in).
 */
export function safeNext(next: string | null | undefined, fallback = "/dashboard"): string {
  if (!next || next.length > 500 || !next.startsWith("/") || next.startsWith("//")) {
    return fallback;
  }
  if (next.includes("\\") || /[\u0000-\u001f]/.test(next)) return fallback;
  return next;
}
