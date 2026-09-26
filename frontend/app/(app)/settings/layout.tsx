import { PageHeader } from "@/components/page-header";
import { SettingsNav } from "@/components/settings/settings-nav";

/** All settings pages: one header, a section menu, and the section on the right. */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <PageHeader title="Settings" description="Your account, your team and your data." />
      <div className="grid gap-6 lg:grid-cols-[11rem_minmax(0,1fr)] lg:gap-10">
        <SettingsNav />
        <div className="max-w-3xl min-w-0">{children}</div>
      </div>
    </>
  );
}
