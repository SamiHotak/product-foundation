"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { PASSWORD_MIN } from "@/components/auth/signup-form";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { PasswordInput } from "@/components/ui/password-input";
import { api, errorMessage, unwrap } from "@/lib/api";

export function ResetPasswordForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | undefined>();

  if (!token) {
    return (
      <Alert tone="error">
        <p>This page needs the link from your email.</p>
        <Link href="/forgot-password" className="font-medium underline">
          Ask for a new link
        </Link>
      </Alert>
    );
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    const confirm = String(form.get("confirm") ?? "");
    if (password.length < PASSWORD_MIN)
      return setFieldError(`Use at least ${PASSWORD_MIN} characters.`);
    if (password !== confirm) return setFieldError("The two passwords are not the same.");
    setFieldError(undefined);
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/auth/reset-password", { body: { token, password } }));
      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      {error && (
        <Alert tone="error">
          <p>{error}</p>
          <Link href="/forgot-password" className="font-medium underline">
            Ask for a new link
          </Link>
        </Alert>
      )}
      <Field label="New password" hint={`At least ${PASSWORD_MIN} characters.`} error={fieldError}>
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
      <Field label="Repeat new password">
        {(a) => (
          <PasswordInput
            {...a}
            autoComplete="new-password"
            required
            name="confirm"
            maxLength={128}
          />
        )}
      </Field>
      <p className="text-xs text-ink-muted">You will be signed out on all other devices.</p>
      <Button type="submit" className="h-10 w-full" disabled={busy}>
        {busy ? "Saving…" : "Save new password"}
      </Button>
    </form>
  );
}
