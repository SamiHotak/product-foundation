"use client";

import { useRouter } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { useForm } from "@/hooks/use-form";
import { api, unwrap } from "@/lib/api";
import { maxLength, required, rules } from "@/lib/validation";

/** "Create a workspace" dialog (from the workspace switcher and the command palette). */
export function CreateWorkspaceDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const form = useForm({
    initial: { name: "" },
    validate: { name: rules(required("Give the workspace a name."), maxLength(80)) },
    onSubmit: async ({ name }) => {
      const org = await unwrap(api.POST("/api/organizations", { body: { name: name.trim() } }));
      change(false);
      toast.success(`Workspace “${org.name}” created.`, {
        description: "You are working in it now.",
      });
      router.refresh(); // the new workspace is now the active one
    },
  });

  function change(next: boolean) {
    if (!next) form.reset();
    onOpenChange(next);
  }

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogContent
        title="Create a workspace"
        description="A separate space with its own data, for example one per client or team."
      >
        <form {...form.formProps} className="space-y-4">
          {form.formError && <Alert tone="error">{form.formError}</Alert>}
          <Field label="Workspace name" error={form.errors.name}>
            {(a) => (
              <Input
                {...a}
                {...form.field("name")}
                autoFocus
                maxLength={80}
                placeholder="Acme GmbH"
              />
            )}
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => change(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={form.submitting}>
              {form.submitting ? "Creating…" : "Create workspace"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
