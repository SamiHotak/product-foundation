import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AuthHeader } from "@/components/auth/auth-header";
import { GoogleButton } from "@/components/auth/google-button";
import { SignupForm } from "@/components/auth/signup-form";
import { getMe, getProviders } from "@/lib/api/server";

export const metadata: Metadata = { title: "Create account" };

export default async function SignupPage() {
  if (await getMe()) redirect("/dashboard");
  const providers = await getProviders();
  return (
    <>
      <AuthHeader
        title="Create your account"
        description={
          <>
            Already have one?{" "}
            <Link href="/login" className="font-medium text-accent hover:underline">
              Sign in
            </Link>
          </>
        }
      />
      {providers.google && <GoogleButton />}
      <SignupForm />
    </>
  );
}
