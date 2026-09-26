import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AuthHeader } from "@/components/auth/auth-header";
import { GoogleButton } from "@/components/auth/google-button";
import { LoginForm } from "@/components/auth/login-form";
import { getMe, getProviders } from "@/lib/api/server";
import { safeNext } from "@/lib/safe-next";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string | string[] }>;
}) {
  const raw = (await searchParams).next;
  const next = safeNext(typeof raw === "string" ? raw : null);
  if (await getMe()) redirect(next);
  const providers = await getProviders();
  return (
    <>
      <AuthHeader
        title="Sign in"
        description={
          <>
            New here?{" "}
            <Link href="/signup" className="font-medium text-accent hover:underline">
              Create an account
            </Link>
          </>
        }
      />
      {providers.google && <GoogleButton next={next === "/dashboard" ? undefined : next} />}
      <Suspense>
        <LoginForm />
      </Suspense>
    </>
  );
}
