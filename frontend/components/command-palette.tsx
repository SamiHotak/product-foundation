"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  ArrowRight,
  Building2,
  CornerDownLeft,
  LogOut,
  Monitor,
  Moon,
  Plus,
  Search,
  Settings,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { CreateWorkspaceDialog } from "@/components/layout/create-workspace-dialog";
import { canSee } from "@/components/layout/nav-links";
import { useSession } from "@/components/session-provider";
import { SETTINGS_PAGES } from "@/components/settings/settings-nav";
import { useTheme } from "@/components/theme-provider";
import { toast } from "@/components/ui/toast";
import { product } from "@/config/product";
import { api, errorMessage, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

type Command = {
  id: string;
  group: "Pages" | "Actions" | "Workspaces" | "Theme";
  label: string;
  hint?: string;
  keywords?: string[];
  icon: LucideIcon;
  run: () => void;
};

/** Every word must appear in the label, hint, group or keywords. Label matches rank first. */
export function filterCommands(commands: Command[], query: string): Command[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return commands;
  return commands
    .map((command) => {
      const label = command.label.toLowerCase();
      const text = [label, command.hint, command.group, ...(command.keywords ?? [])]
        .join(" ")
        .toLowerCase();
      if (!words.every((w) => text.includes(w))) return null;
      const score = label.startsWith(words[0]!) ? 0 : label.includes(words[0]!) ? 1 : 2;
      return { command, score };
    })
    .filter((x): x is { command: Command; score: number } => x !== null)
    .sort((a, b) => a.score - b.score)
    .map((x) => x.command);
}

function subscribeNothing(): () => void {
  return () => {};
}

/** "⌘K" on Mac, "Ctrl K" elsewhere (Ctrl on the server, so no hydration mismatch). */
function useIsMac(): boolean {
  return useSyncExternalStore(
    subscribeNothing,
    () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent),
    () => false,
  );
}

/**
 * Command palette: press Ctrl+K (⌘K on Mac) anywhere, type, press Enter.
 * Finds pages (sidebar + settings, only the ones you may use) and runs actions.
 * Products get their pages here automatically from `nav` in config/product.ts.
 */
export function CommandPalette() {
  const router = useRouter();
  const session = useSession();
  const { organizations, activeOrganization, can } = session;
  const { setTheme } = useTheme();
  const isMac = useIsMac();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Global keyboard shortcut (a browser event listener, cleaned up on unmount).
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault(); // stops the browser's own Ctrl+K (search bar)
        setOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const commands = useMemo<Command[]>(() => {
    const go = (href: string) => () => router.push(href);
    const pages: Command[] = [...product.nav, ...product.navFooter]
      .filter((item) => canSee(item, session))
      .map((item) => ({
        id: `page:${item.href}`,
        group: "Pages",
        label: item.label,
        keywords: item.keywords,
        icon: item.icon,
        run: go(item.href),
      }));
    const settings: Command[] = SETTINGS_PAGES.filter((p) => !p.needs || can(p.needs))
      .filter((p) => !pages.some((c) => c.id === `page:${p.href}`))
      .map((p) => ({
        id: `page:${p.href}`,
        group: "Pages",
        label: p.label,
        hint: "Settings",
        keywords: ["settings", ...(p.keywords ?? [])],
        icon: Settings,
        run: go(p.href),
      }));
    const actions: Command[] = [
      {
        id: "action:create-workspace",
        group: "Actions",
        label: "Create workspace",
        keywords: ["new", "organization", "team"],
        icon: Plus,
        run: () => setCreating(true),
      },
    ];
    if (can("members:invite")) {
      actions.push({
        id: "action:invite",
        group: "Actions",
        label: "Invite someone",
        keywords: ["member", "team", "add", "people"],
        icon: Plus,
        run: go("/settings/members#invite"),
      });
    }
    if (can("api_keys:manage")) {
      actions.push({
        id: "action:api-key",
        group: "Actions",
        label: "Create an API key",
        keywords: ["token", "new"],
        icon: Plus,
        run: go("/settings/api-keys"),
      });
    }
    actions.push({
      id: "action:sign-out",
      group: "Actions",
      label: "Sign out",
      keywords: ["log out", "logout", "exit"],
      icon: LogOut,
      run: () => {
        void api
          .POST("/api/auth/logout")
          .catch(() => null)
          .then(() => {
            router.replace("/login");
            router.refresh();
          });
      },
    });
    const workspaces: Command[] = organizations
      .filter((org) => org.id !== activeOrganization.id)
      .map((org) => ({
        id: `workspace:${org.id}`,
        group: "Workspaces",
        label: `Switch to ${org.name}`,
        keywords: ["workspace", "organization"],
        icon: Building2,
        run: () => {
          unwrap(api.PUT("/api/auth/session/organization", { body: { organization_id: org.id } }))
            .then(() => router.refresh())
            .catch((err: unknown) =>
              toast.error("Could not switch the workspace.", { description: errorMessage(err) }),
            );
        },
      }));
    const theme: Command[] = [
      { value: "light", label: "Light theme", icon: Sun },
      { value: "dark", label: "Dark theme", icon: Moon },
      { value: "system", label: "Theme same as device", icon: Monitor },
    ].map((t) => ({
      id: `theme:${t.value}`,
      group: "Theme",
      label: t.label,
      keywords: ["appearance", "mode", "colors"],
      icon: t.icon,
      run: () => setTheme(t.value as "light" | "dark" | "system"),
    }));
    return [...pages, ...settings, ...actions, ...workspaces, ...theme];
  }, [router, can, session, organizations, activeOrganization.id, setTheme]);

  // Grouped (in the order groups first appear), then flat for the arrow keys.
  const groups = useMemo(() => {
    const map = new Map<Command["group"], Command[]>();
    for (const command of filterCommands(commands, query)) {
      map.set(command.group, [...(map.get(command.group) ?? []), command]);
    }
    return [...map.entries()];
  }, [commands, query]);
  const results = useMemo(() => groups.flatMap(([, list]) => list), [groups]);
  const current = Math.min(active, Math.max(results.length - 1, 0));

  useEffect(() => {
    // Keep the highlighted option visible while moving with the arrow keys.
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${current}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [current]);

  function change(next: boolean) {
    setOpen(next);
    if (!next) {
      setQuery("");
      setActive(0);
    }
  }

  function run(command: Command | undefined) {
    if (!command) return;
    change(false);
    command.run();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    const last = results.length - 1;
    if (event.key === "ArrowDown") setActive(current >= last ? 0 : current + 1);
    else if (event.key === "ArrowUp") setActive(current <= 0 ? last : current - 1);
    else if (event.key === "Home" && event.ctrlKey) setActive(0);
    else if (event.key === "End" && event.ctrlKey) setActive(last);
    else if (event.key === "Enter") run(results[current]);
    else return;
    event.preventDefault();
  }

  const optionId = (index: number) => `${listId}-option-${index}`;

  return (
    <>
      <button
        type="button"
        onClick={() => change(true)}
        aria-label="Search and commands"
        aria-keyshortcuts={isMac ? "Meta+K" : "Control+K"}
        className="flex h-9 items-center gap-2 rounded-control border border-line px-2.5 text-sm text-ink-muted hover:border-line-strong hover:text-ink sm:w-56 sm:px-3"
      >
        <Search className="size-4 shrink-0" aria-hidden="true" />
        <span className="hidden flex-1 text-left sm:inline">Search…</span>
        <span className="hidden items-center gap-0.5 sm:flex" aria-hidden="true">
          {isMac ? (
            <kbd className="kbd">⌘K</kbd>
          ) : (
            <>
              <kbd className="kbd">Ctrl</kbd>
              <kbd className="kbd">K</kbd>
            </>
          )}
        </span>
      </button>

      <DialogPrimitive.Root open={open} onOpenChange={change}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/30 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
          <DialogPrimitive.Content
            aria-describedby={undefined}
            className={cn(
              "fixed top-[12vh] left-1/2 z-50 flex max-h-[70vh] w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 flex-col",
              "overflow-hidden rounded-sheet border border-line bg-surface shadow-2xl shadow-ink/20",
              "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
            )}
          >
            <DialogPrimitive.Title className="sr-only">Search and commands</DialogPrimitive.Title>
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Search className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
              <input
                autoFocus
                role="combobox"
                aria-label="Search pages and commands"
                aria-expanded="true"
                aria-controls={listId}
                aria-autocomplete="list"
                aria-activedescendant={results.length ? optionId(current) : undefined}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setActive(0);
                }}
                onKeyDown={onKeyDown}
                placeholder="Type a page or a command…"
                className="h-12 min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-ink-muted/70"
              />
              <kbd className="kbd" aria-hidden="true">
                Esc
              </kbd>
            </div>

            <div
              ref={listRef}
              id={listId}
              role="listbox"
              aria-label="Results"
              className="min-h-0 flex-1 overflow-y-auto p-2"
            >
              {results.length === 0 && (
                <p className="px-3 py-8 text-center text-sm text-ink-muted">
                  Nothing found for “{query.trim()}”.
                </p>
              )}
              {groups.map(([group, list]) => (
                <div key={group} role="group" aria-labelledby={`${listId}-${group}`}>
                  <div
                    id={`${listId}-${group}`}
                    role="presentation"
                    className="px-3 pt-2 pb-1 text-xs font-medium text-ink-muted"
                  >
                    {group}
                  </div>
                  {list.map((command) => {
                    const index = results.indexOf(command);
                    const Icon = command.icon;
                    const selected = index === current;
                    return (
                      <div
                        key={command.id}
                        id={optionId(index)}
                        role="option"
                        aria-selected={selected}
                        data-index={index}
                        onMouseMove={() => current !== index && setActive(index)}
                        onClick={() => run(command)}
                        className={cn(
                          "flex h-10 cursor-pointer items-center gap-3 rounded-control px-3 text-sm",
                          selected && "bg-accent-soft",
                        )}
                      >
                        <Icon
                          className={cn(
                            "size-4 shrink-0",
                            selected ? "text-accent" : "text-ink-muted",
                          )}
                          aria-hidden="true"
                        />
                        <span className="min-w-0 flex-1 truncate">{command.label}</span>
                        {command.hint && (
                          <span className="text-xs text-ink-muted">{command.hint}</span>
                        )}
                        {selected && (
                          <ArrowRight className="size-3.5 text-accent" aria-hidden="true" />
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>

            <div
              aria-hidden="true"
              className="hidden items-center gap-4 border-t border-line px-4 py-2 text-xs text-ink-muted sm:flex"
            >
              <span className="flex items-center gap-1">
                <kbd className="kbd">↑</kbd>
                <kbd className="kbd">↓</kbd> to move
              </span>
              <span className="flex items-center gap-1">
                <kbd className="kbd">
                  <CornerDownLeft className="size-3" />
                </kbd>{" "}
                to open
              </span>
            </div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>

      <CreateWorkspaceDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}
