"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api";

/**
 * "Are you sure?" before something that is hard to undo.
 * With `typeToConfirm`, the button only works after typing that exact text
 * (for deleting an account or a workspace).
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  busyLabel,
  tone = "danger",
  typeToConfirm,
  typeLabel,
  onConfirm,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  confirmLabel: string;
  busyLabel?: string;
  tone?: "danger" | "primary";
  typeToConfirm?: string;
  typeLabel?: string;
  /** Throw to show the error inside the dialog; resolve to close it. */
  onConfirm: (typed: string) => Promise<void>;
  children?: React.ReactNode;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const matches = typeToConfirm === undefined || typed.trim() === typeToConfirm;

  function change(next: boolean) {
    if (!next) {
      setTyped("");
      setError(null);
    }
    onOpenChange(next);
  }

  async function confirm(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!matches) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(typed.trim());
      change(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogContent title={title} description={description}>
        <form onSubmit={confirm} className="space-y-4" noValidate>
          {children}
          {error && <Alert tone="error">{error}</Alert>}
          {typeToConfirm !== undefined && (
            <Field label={typeLabel ?? `Type “${typeToConfirm}” to confirm`}>
              {(a) => (
                <Input
                  {...a}
                  autoFocus
                  autoComplete="off"
                  spellCheck={false}
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                />
              )}
            </Field>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => change(false)}>
              Cancel
            </Button>
            <Button type="submit" variant={tone} disabled={busy || !matches}>
              {busy ? (busyLabel ?? "Working…") : confirmLabel}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
