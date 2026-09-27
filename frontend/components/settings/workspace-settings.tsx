"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/session-provider";
import { NoAccess, Section } from "@/components/settings/section";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { useForm } from "@/hooks/use-form";
import { api, unwrap } from "@/lib/api";
import { maxLength, required, rules } from "@/lib/validation";

const ROLE_LABEL = { owner: "Owner", admin: "Admin", member: "Member" } as const;

/** Settings → Workspace: name, your role, leave. The team is on Settings → Members. */
export function WorkspaceSettings() {
  return (
    <div className="space-y-12">
      <WorkspaceName />
      <LeaveWorkspace />
    </div>
  );
}

// --- name -----------------------------------------------------------------------------------

function WorkspaceName() {
  const router = useRouter();
  const { activeOrganization, can } = useSession();
  const form = useForm({
    initial: { name: activeOrganization.name },
    validate: { name: rules(required("Give the workspace a name."), maxLength(80)) },
    onSubmit: async ({ name }) => {
      const saved = await unwrap(api.PATCH("/api/organizations/current", { body: { name } }));
      form.reset({ name: saved.name });
      toast.success("Workspace name saved.");
      router.refresh();
    },
  });

  const role = (
    <p className="text-sm text-ink-muted">
      Your role here:{" "}
      <span className="font-medium text-ink">{ROLE_LABEL[activeOrganization.role]}</span>.
    </p>
  );

  if (!can("org:update")) {
    return (
      <Section title="Workspace name">
        <p className="text-sm font-medium">{activeOrganization.name}</p>
        {role}
      </Section>
    );
  }
  return (
    <Section title="Workspace name" description="Everyone in the workspace sees this name.">
      <form {...form.formProps} aria-label="Workspace name" className="space-y-3">
        {form.formError && <Alert tone="error">{form.formError}</Alert>}
        <div className="flex flex-wrap items-start gap-3">
          <Field label="Name" error={form.errors.name} className="min-w-0 flex-1 basis-60">
            {(a) => <Input {...a} {...form.field("name")} maxLength={80} />}
          </Field>
          <Button
            type="submit"
            variant="secondary"
            disabled={form.submitting || !form.dirty}
            className="sm:mt-7"
          >
            {form.submitting ? "Saving…" : "Save name"}
          </Button>
        </div>
      </form>
      {role}
    </Section>
  );
}

// --- leave ----------------------------------------------------------------------------------

function LeaveWorkspace() {
  const router = useRouter();
  const { activeOrganization } = useSession();
  const [open, setOpen] = useState(false);
  if (activeOrganization.role === "owner") {
    return (
      <Section title="Leave workspace">
        <NoAccess>
          You own this workspace, so you can&apos;t leave it. Make someone else the owner first (on
          the{" "}
          <Link
            href="/settings/members"
            className="font-medium text-ink underline underline-offset-2"
          >
            Members
          </Link>{" "}
          page), or delete the workspace under{" "}
          <Link
            href="/settings/privacy"
            className="font-medium text-ink underline underline-offset-2"
          >
            Privacy
          </Link>
          .
        </NoAccess>
      </Section>
    );
  }
  return (
    <Section
      title="Leave workspace"
      description="You lose access to its data. Someone has to invite you again to come back."
    >
      <div>
        <Button variant="secondary" onClick={() => setOpen(true)}>
          Leave {activeOrganization.name}
        </Button>
      </div>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Leave ${activeOrganization.name}?`}
        confirmLabel="Leave workspace"
        busyLabel="Leaving…"
        onConfirm={async () => {
          await unwrap(api.POST("/api/organizations/current/leave"));
          toast.success(`You left ${activeOrganization.name}.`);
          router.replace("/dashboard");
          router.refresh();
        }}
      />
    </Section>
  );
}
