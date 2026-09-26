import Link from "next/link";

import { Button } from "@/components/ui/button";
import { product } from "@/config/product";

/** Placeholder landing page. Phase 3B replaces it with the full marketing site. */
export default function LandingPage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-3xl flex-col justify-center gap-6 px-6">
      <span
        aria-hidden="true"
        className="grid size-10 place-items-center rounded-[9px] bg-accent text-lg font-bold text-accent-ink"
      >
        {product.monogram}
      </span>
      <h1 className="text-4xl leading-tight font-semibold tracking-tight sm:text-5xl">
        {product.name}
      </h1>
      <p className="max-w-xl text-lg text-ink-muted">{product.tagline}</p>
      <div className="flex flex-wrap gap-3">
        <Button asChild>
          <Link href="/signup">Create account</Link>
        </Button>
        <Button asChild variant="secondary">
          <Link href="/login">Sign in</Link>
        </Button>
      </div>
    </main>
  );
}
