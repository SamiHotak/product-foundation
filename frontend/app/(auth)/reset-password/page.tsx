import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthHeader } from "@/components/auth/auth-header";
import { ResetPasswordForm } from "@/components/auth/reset-password-form";

export const metadata: Metadata = { title: "Choose a new password" };

export default function ResetPasswordPage() {
  return (
    <>
      <AuthHeader title="Choose a new password" />
      <Suspense>
        <ResetPasswordForm />
      </Suspense>
    </>
  );
}
