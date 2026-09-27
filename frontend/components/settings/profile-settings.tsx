"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useRouter } from "next/navigation";

import { useSession } from "@/components/session-provider";
import { Section } from "@/components/settings/section";
import { useTheme } from "@/components/theme-provider";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { toast } from "@/components/ui/toast";
import { useApiData } from "@/hooks/use-api-data";
import { useForm } from "@/hooks/use-form";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import {
  maxLength,
  minLength,
  PASSWORD_MAX,
  PASSWORD_MIN,
  required,
  rules,
  sameAs,
} from "@/lib/validation";

/** Settings → Profile: name, password, theme, and the "Get started" checklist. */
export function ProfileSettings() {
  return (
    <div className="space-y-12">
      <ProfileForm />
      <PasswordForm />
      <Appearance />
      <ChecklistToggle />
    </div>
  );
}

// --- name -----------------------------------------------------------------------------------

function ProfileForm() {
  const router = useRouter();
  const { user } = useSession();
  const form = useForm({
    initial: { name: user.name },
    validate: {
      name: rules(required("Enter your name."), maxLength(120)),
    },
    onSubmit: async ({ name }) => {
      const saved = await unwrap(api.PATCH("/api/account/profile", { body: { name } }));
      form.reset({ name: saved.name });
      toast.success("Profile saved.");
      router.refresh(); // the user menu and member lists show the new name
    },
  });

  return (
    <Section
      title="Profile"
      description="Your name is shown to your team, in emails and in the audit log."
    >
      <form {...form.formProps} aria-label="Profile" className="space-y-4">
        {form.formError && <Alert tone="error">{form.formError}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" error={form.errors.name}>
            {(a) => <Input {...a} {...form.field("name")} autoComplete="name" maxLength={120} />}
          </Field>
          <Field
            label="Email"
            hint={`Account since ${formatDate(user.created_at)}. Changing the email is not possible yet.`}
          >
            {(a) => <Input {...a} value={user.email} readOnly disabled />}
          </Field>
        </div>
        <Button type="submit" variant="secondary" disabled={form.submitting || !form.dirty}>
          {form.submitting ? "Saving…" : "Save profile"}
        </Button>
      </form>
    </Section>
  );
}

// --- password -------------------------------------------------------------------------------

function PasswordForm() {
  const router = useRouter();
  const { user } = useSession();
  const hasPassword = user.has_password;
  const form = useForm({
    initial: { current: "", next: "", repeat: "" },
    validate: {
      current: hasPassword ? required("Enter your current password.") : undefined,
      next: rules(
        required("Choose a new password."),
        minLength(PASSWORD_MIN, `Use at least ${PASSWORD_MIN} characters.`),
        (value) =>
          value.length > PASSWORD_MAX ? `Use at most ${PASSWORD_MAX} characters.` : undefined,
      ),
      repeat: rules(
        required("Repeat the new password."),
        sameAs("next", "The passwords are not the same."),
      ),
    },
    // A wrong current password belongs under that field, not at the top.
    mapError: (err) =>
      err instanceof ApiError && err.code === "wrong_password" ? { current: err.message } : null,
    onSubmit: async ({ current, next }) => {
      await unwrap(
        api.PUT("/api/account/password", {
          body: { current_password: hasPassword ? current : null, new_password: next },
        }),
      );
      form.reset();
      toast.success(hasPassword ? "Password changed." : "Password set.", {
        description: "You were signed out on your other devices.",
      });
      router.refresh();
    },
  });

  const methods = [
    user.has_password && "Email and password",
    user.google_linked && "Google",
  ].filter(Boolean) as string[];

  return (
    <Section
      title={hasPassword ? "Change password" : "Set a password"}
      description={
        hasPassword
          ? "After the change you stay signed in here, and are signed out everywhere else."
          : "You sign in with Google. Add a password to also sign in with your email."
      }
    >
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-ink-muted">Sign-in methods:</span>
        {methods.map((m) => (
          <Badge key={m}>{m}</Badge>
        ))}
      </p>
      <form {...form.formProps} aria-label="Password" className="space-y-4">
        {form.formError && <Alert tone="error">{form.formError}</Alert>}
        {/* Hidden username helps password managers save the right account. */}
        <input type="email" autoComplete="username" value={user.email} readOnly hidden />
        {hasPassword && (
          <Field label="Current password" error={form.errors.current} className="sm:max-w-sm">
            {(a) => (
              <PasswordInput {...a} {...form.field("current")} autoComplete="current-password" />
            )}
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="New password"
            error={form.errors.next}
            hint={`At least ${PASSWORD_MIN} characters. A short sentence is easy to remember.`}
          >
            {(a) => <PasswordInput {...a} {...form.field("next")} autoComplete="new-password" />}
          </Field>
          <Field label="Repeat new password" error={form.errors.repeat}>
            {(a) => <PasswordInput {...a} {...form.field("repeat")} autoComplete="new-password" />}
          </Field>
        </div>
        <Button type="submit" variant="secondary" disabled={form.submitting}>
          {form.submitting ? "Saving…" : hasPassword ? "Change password" : "Set password"}
        </Button>
      </form>
    </Section>
  );
}

// --- theme ----------------------------------------------------------------------------------

const THEME_OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Same as device", icon: Monitor },
];

function Appearance() {
  const { theme, setTheme } = useTheme();
  return (
    <Section title="Appearance" description="Saved in this browser.">
      <div role="radiogroup" aria-label="Theme" className="grid gap-2 sm:grid-cols-3">
        {THEME_OPTIONS.map(({ value, label, icon: Icon }) => {
          const checked = theme === value;
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={checked}
              onClick={() => setTheme(value)}
              className={cn(
                "flex items-center gap-2.5 rounded-menu border px-4 py-3 text-left text-sm transition-colors",
                checked
                  ? "border-accent bg-accent-soft font-medium"
                  : "border-line hover:border-line-strong hover:bg-surface-sunken/60",
              )}
            >
              <Icon
                className={cn("size-4", checked ? "text-accent" : "text-ink-muted")}
                aria-hidden="true"
              />
              {label}
            </button>
          );
        })}
      </div>
    </Section>
  );
}

// --- checklist ------------------------------------------------------------------------------

function ChecklistToggle() {
  const status = useApiData(() => unwrap(api.GET("/api/organizations/current/onboarding")));
  if (!status.data?.dismissed) return null;

  async function show() {
    try {
      status.setData(await unwrap(api.DELETE("/api/organizations/current/onboarding/dismiss")));
      toast.success("The checklist is back on the dashboard.");
    } catch (err) {
      toast.error("Could not show the checklist.", { description: errorMessage(err) });
    }
  }

  return (
    <Section
      title="Get started checklist"
      description="You hid the checklist in this workspace. Show it on the dashboard again?"
    >
      <div>
        <Button variant="secondary" onClick={() => void show()}>
          Show checklist
        </Button>
      </div>
    </Section>
  );
}
