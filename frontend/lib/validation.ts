/**
 * Small, reusable validation rules for `useForm` (hooks/use-form.ts).
 * Each rule returns an error message, or undefined when the value is fine.
 * The backend checks everything again: these rules are for fast, friendly feedback.
 */

export type Rule<V = Record<string, string>> = (value: string, values: V) => string | undefined;

/** Run rules in order; the first message wins. */
export function rules<V>(...list: Rule<V>[]): Rule<V> {
  return (value, values) => {
    for (const rule of list) {
      const message = rule(value, values);
      if (message) return message;
    }
    return undefined;
  };
}

export const required =
  <V>(message = "This field is required."): Rule<V> =>
  (value) =>
    value.trim() ? undefined : message;

export const maxLength =
  <V>(max: number, message = `Use at most ${max} characters.`): Rule<V> =>
  (value) =>
    value.trim().length > max ? message : undefined;

export const minLength =
  <V>(min: number, message = `Use at least ${min} characters.`): Rule<V> =>
  (value) =>
    value.length > 0 && value.length < min ? message : undefined;

// Same simple check the invite form used before; the backend does the full check.
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const email =
  <V>(message = "Enter a valid email address."): Rule<V> =>
  (value) =>
    !value.trim() || EMAIL.test(value.trim()) ? undefined : message;

/** The value must equal another field (e.g. "repeat password"). */
export const sameAs =
  <V extends Record<string, string>>(field: keyof V, message: string): Rule<V> =>
  (value, values) =>
    value === values[field] ? undefined : message;

/** Password rules, same as the backend (backend/app/schemas/auth.py). */
export const PASSWORD_MIN = 10;
export const PASSWORD_MAX = 128;
