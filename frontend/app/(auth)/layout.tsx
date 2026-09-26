import { ProductMark } from "@/components/layout/product-mark";

/** Sign-in pages: the product mark, then one focused form on a raised sheet. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col px-4 py-6 sm:py-10">
      <div className="mx-auto w-full max-w-[26rem]">
        <ProductMark href="/" />
      </div>
      <main className="mx-auto flex w-full max-w-[26rem] flex-1 flex-col justify-start py-6 sm:justify-center sm:py-8">
        <div className="rounded-sheet border border-line bg-surface p-6 sm:p-8">{children}</div>
      </main>
    </div>
  );
}
