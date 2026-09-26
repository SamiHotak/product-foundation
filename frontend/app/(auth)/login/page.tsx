import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { AuthHeader } from "@/components/auth/auth-header";
import { GoogleButton } from "@/components/auth/google-button";
import { LoginForm } from "@/components/auth/login-form";
import { getMe, getProviders } from "@/lib/api/server";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage() {
  if (await getMe()) redirect("/dashboard");
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
      {providers.google && <GoogleButton />}
      <Suspense>
        <LoginForm />
      </Suspense>
    </>
  );
}
