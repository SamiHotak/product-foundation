import { Plus } from "lucide-react";

/**
 * Questions and answers as native <details> elements: they open and close without any
 * JavaScript, work with the keyboard, and are found by the browser's "find in page".
 */
export function FaqList({ items }: { items: { question: string; answer: string }[] }) {
  return (
    <div className="divide-y divide-line border-y border-line">
      {items.map((item) => (
        <details key={item.question} className="group">
          <summary className="flex cursor-pointer list-none items-start justify-between gap-6 py-5 text-base font-medium [&::-webkit-details-marker]:hidden">
            {item.question}
            <Plus
              className="mt-1 size-4 shrink-0 text-ink-muted transition-transform group-open:rotate-45"
              aria-hidden="true"
            />
          </summary>
          <p className="max-w-prose pb-5 text-ink-muted">{item.answer}</p>
        </details>
      ))}
    </div>
  );
}
