"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { api, errorMessage, unwrap } from "@/lib/api";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState(""); // shown in the "sent" message
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    setEmail(email);
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setError("Enter the email address of your account.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/auth/forgot-password", { body: { email } }));
      setSent(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="space-y-4">
        <Alert tone="success">
          If an account uses <strong>{email}</strong>, a reset link is on its way. It works for 60
          minutes.
        </Alert>
        <Link
          href="/login"
          className="inline-block text-sm font-medium text-accent hover:underline"
        >
          Back to sign in
        </Link>
      </div>
    );
  }
  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      {error && <Alert tone="error">{error}</Alert>}
      <Field label="Email">
        {(a) => <Input {...a} type="email" autoComplete="email" required name="email" />}
      </Field>
      <Button type="submit" className="h-10 w-full" disabled={busy}>
        {busy ? "Sending…" : "Email me a reset link"}
      </Button>
      <Link href="/login" className="block text-center text-sm text-ink-muted hover:text-ink">
        Back to sign in
      </Link>
    </form>
  );
}
