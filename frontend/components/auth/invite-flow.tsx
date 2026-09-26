"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthHeader } from "@/components/auth/auth-header";
import { GoogleButton } from "@/components/auth/google-button";
import { PASSWORD_MIN } from "@/components/auth/signup-form";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { api, errorMessage, fieldErrors, unwrap, type InvitePreview, type Me } from "@/lib/api";

const ROLE_TEXT = { owner: "an owner", admin: "an admin", member: "a member" } as const;

/**
 * The page behind the invite link. Four cases:
 * - signed in with the invited email      -> "Join" button
 * - signed in with another email          -> explain, offer to sign out
 * - signed out, account exists            -> sign in (then back here)
 * - signed out, no account yet            -> name + password, and you're in
 */
export function InviteFlow({
  token,
  me,
  googleEnabled,
  preview,
  error,
}: {
  token: string;
  me: Me | null;
  googleEnabled: boolean;
  preview: InvitePreview | null;
  error: string | null;
}) {
  if (error || !preview) {
    return (
      <>
        <AuthHeader title="This invite didn't work" />
        <Alert tone="error">{error ?? "This invite link is not valid."}</Alert>
        <p className="mt-4 text-sm text-ink-muted">
          <Link
            href={me ? "/dashboard" : "/login"}
            className="font-medium text-accent hover:underline"
          >
            {me ? "Go to your dashboard" : "Sign in"}
          </Link>
        </p>
      </>
    );
  }

  const who = preview.invited_by_name ? `${preview.invited_by_name} invited you` : "You're invited";
  const header = (
    <AuthHeader
      title={`Join ${preview.organization_name}`}
      description={`${who} to join as ${ROLE_TEXT[preview.role]}.`}
    />
  );

  if (me) {
    const sameEmail = me.user.email.toLowerCase() === preview.email.toLowerCase();
    return (
      <>
        {header}
        {sameEmail ? <AcceptButton token={token} /> : <WrongAccount me={me} preview={preview} />}
      </>
    );
  }
  const here = `/invite?token=${encodeURIComponent(token)}`;
  if (preview.account_exists) {
    return (
      <>
        {header}
        <p className="mb-4 text-sm text-ink-muted">
          You already have an account for <strong className="text-ink">{preview.email}</strong>.
          Sign in to accept.
        </p>
        <div className="space-y-3">
          <Button asChild className="h-10 w-full">
            <Link href={`/login?next=${encodeURIComponent(here)}`}>Sign in to accept</Link>
          </Button>
          {googleEnabled && <GoogleButton next={here} divider={false} />}
        </div>
      </>
    );
  }
  return (
    <>
      {header}
      <InviteSignupForm token={token} email={preview.email} />
    </>
  );
}

function AcceptButton({ token }: { token: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function accept() {
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/invites/accept", { body: { token } }));
      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }
  return (
    <div className="space-y-4">
      {error && <Alert tone="error">{error}</Alert>}
      <Button className="h-10 w-full" onClick={() => void accept()} disabled={busy}>
        {busy ? "Joining…" : "Join workspace"}
      </Button>
    </div>
  );
}

function WrongAccount({ me, preview }: { me: Me; preview: InvitePreview }) {
  const router = useRouter();
  async function signOut() {
    await api.POST("/api/auth/logout").catch(() => null);
    router.refresh(); // the page shows the "sign in" or "create account" step now
  }
  return (
    <div className="space-y-4">
      <Alert tone="info">
        <p>
          This invite is for <strong>{preview.email}</strong>, but you are signed in as{" "}
          <strong>{me.user.email}</strong>.
        </p>
      </Alert>
      <Button variant="secondary" className="h-10 w-full" onClick={() => void signOut()}>
        Sign out and continue as {preview.email}
      </Button>
    </div>
  );
}

function InviteSignupForm({ token, email }: { token: string; email: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    const password = String(form.get("password") ?? "");
    const local: Record<string, string> = {};
    if (!name) local.name = "Enter your name.";
    if (password.length < PASSWORD_MIN) local.password = `Use at least ${PASSWORD_MIN} characters.`;
    setErrors(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/api/invites/signup", { body: { token, name, password } }));
      router.replace("/dashboard");
      router.refresh();
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
      <Field label="Email" hint="The invite was sent here, so no confirmation email is needed.">
        {(a) => <Input {...a} value={email} readOnly autoComplete="username" />}
      </Field>
      <Field label="Your name" error={errors.name}>
        {(a) => <Input {...a} name="name" autoComplete="name" maxLength={120} autoFocus />}
      </Field>
      <Field
        label="Choose a password"
        error={errors.password}
        hint={`At least ${PASSWORD_MIN} characters. A short sentence works well.`}
      >
        {(a) => (
          <PasswordInput {...a} name="password" autoComplete="new-password" maxLength={128} />
        )}
      </Field>
      <Button type="submit" className="h-10 w-full" disabled={busy}>
        {busy ? "Creating your account…" : "Create account and join"}
      </Button>
    </form>
  );
}
