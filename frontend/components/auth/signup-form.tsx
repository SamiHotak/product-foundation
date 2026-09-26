"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { api, errorMessage, fieldErrors, unwrap } from "@/lib/api";

export const PASSWORD_MIN = 10;

export function SignupForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Read from the form (not React state): text typed before the page finished loading is kept.
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");
    const local: Record<string, string> = {};
    if (!name.trim()) local.name = "Enter your name.";
    if (!/^\S+@\S+\.\S+$/.test(email)) local.email = "Enter a valid email address.";
    if (password.length < PASSWORD_MIN) local.password = `Use at least ${PASSWORD_MIN} characters.`;
    setErrors(local);
    if (Object.keys(local).length) return;

    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/auth/signup", { body: { name, email, password } }));
      router.push(`/verify-email?email=${encodeURIComponent(email)}`);
    } catch (err) {
      const fields = fieldErrors(err);
      if (Object.keys(fields).length) setErrors(fields);
      else setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      {error && <Alert tone="error">{error}</Alert>}
      <Field label="Your name" error={errors.name}>
        {(a) => <Input {...a} autoComplete="name" required name="name" maxLength={120} />}
      </Field>
      <Field label="Work email" error={errors.email}>
        {(a) => <Input {...a} type="email" autoComplete="email" required name="email" />}
      </Field>
      <Field
        label="Password"
        error={errors.password}
        hint={`At least ${PASSWORD_MIN} characters. A short sentence works well.`}
      >
        {(a) => (
          <PasswordInput
            {...a}
            autoComplete="new-password"
            required
            name="password"
            maxLength={128}
          />
        )}
      </Field>
      <Button type="submit" className="h-10 w-full" disabled={busy}>
        {busy ? "Creating your account…" : "Create account"}
      </Button>
    </form>
  );
}
