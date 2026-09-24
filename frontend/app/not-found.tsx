import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col items-start justify-center gap-4 px-6">
      <p className="text-sm text-ink-muted tabular">404</p>
      <h1 className="text-2xl font-semibold tracking-tight">This page does not exist</h1>
      <p className="text-ink-muted">The link may be old, or the address has a typo.</p>
      <Button asChild variant="secondary">
        <Link href="/dashboard">Go to the dashboard</Link>
      </Button>
    </main>
  );
}
