import Link from "next/link";

import { ProductMark } from "@/components/layout/product-mark";
import { Button } from "@/components/ui/button";
import { product } from "@/config/product";

/** Placeholder landing page. Phase 3B replaces it with the full marketing site. */
export default function LandingPage() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-3xl flex-col justify-center gap-6 px-6">
      <div>
        <ProductMark href="/" size="lg" />
      </div>
      <h1 className="text-4xl leading-tight font-semibold tracking-tight sm:text-5xl">
        {product.tagline}
      </h1>
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
