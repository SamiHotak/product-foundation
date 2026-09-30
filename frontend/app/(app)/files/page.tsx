import type { Metadata } from "next";

import { FilesBrowser } from "@/components/files/files-browser";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Files" };

export default function FilesPage() {
  return (
    <>
      <PageHeader
        title="Files"
        description="Files of this workspace. Products use this for documents, invoices, images and more."
      />
      <div className="max-w-4xl">
        <FilesBrowser />
      </div>
    </>
  );
}
