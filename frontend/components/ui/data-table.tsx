"use client";

import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Search,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { DataTableState } from "@/hooks/use-data-table";
import { cn } from "@/lib/utils";

const PAGE_SIZES = [10, 25, 50];

/**
 * A table with search, filters, sorting and pages (state from `useDataTable`).
 * Desktop: a normal table. Phone: each row becomes a small card ("Label: value").
 *
 *   const table = useDataTable({ rows, columns, searchText: (m) => `${m.name} ${m.email}` });
 *   <DataTable table={table} label="Members" rowKey={(m) => m.id} empty={<EmptyState .../>} />
 */
export function DataTable<T>({
  table,
  label,
  rowKey,
  rowProps,
  empty,
  searchLabel,
  actions,
  className,
}: {
  table: DataTableState<T>;
  /** Accessible name of the table, e.g. "Members". */
  label: string;
  rowKey: (row: T) => string;
  /** Extra attributes per row (e.g. data-* for tests). */
  rowProps?: (row: T) => Record<string, string | undefined>;
  /** Shown instead of the table when there are no rows at all (not after filtering). */
  empty?: React.ReactNode;
  /** Placeholder + label of the search box, e.g. "Search members". */
  searchLabel?: string;
  /** Buttons on the right of the toolbar. */
  actions?: React.ReactNode;
  className?: string;
}) {
  const { columns } = table;
  if (!table.loading && table.count === 0 && empty) return <>{empty}</>;

  const showToolbar = table.searchable || table.filters.length > 0 || actions;
  const showPager = table.total > PAGE_SIZES[0]!;

  return (
    <div className={cn("space-y-3", className)}>
      {showToolbar && (
        <div className="flex flex-wrap items-center gap-2">
          {table.searchable && (
            <div className="relative min-w-0 flex-1 basis-48">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-muted"
              />
              <Input
                type="search"
                value={table.query}
                onChange={(e) => table.setQuery(e.target.value)}
                placeholder={`${searchLabel ?? "Search"}…`}
                aria-label={searchLabel ?? "Search"}
                className="h-9 pl-9"
              />
            </div>
          )}
          {table.filters.map((filter) => (
            <Select
              key={filter.id}
              aria-label={filter.label}
              value={table.filterValues[filter.id] ?? ""}
              onChange={(e) => table.setFilter(filter.id, e.target.value)}
              className="w-40 [&_select]:h-9"
            >
              <option value="">{filter.allLabel}</option>
              {filter.options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          ))}
          {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
        </div>
      )}

      <div className="overflow-hidden rounded-menu border border-line">
        <table aria-label={label} aria-busy={table.loading || undefined} className="w-full text-sm">
          <thead className="bg-surface-sunken/70 text-left text-xs text-ink-muted max-sm:sr-only">
            <tr>
              {columns.map((column) => {
                const sorted = table.sort?.id === column.id ? table.sort.direction : null;
                return (
                  <th
                    key={column.id}
                    scope="col"
                    aria-sort={sorted ? (sorted === "asc" ? "ascending" : "descending") : undefined}
                    className={cn(
                      "h-9 px-4 font-medium",
                      column.align === "right" && "text-right",
                      column.className,
                    )}
                  >
                    {column.sortValue ? (
                      <button
                        type="button"
                        onClick={() => table.toggleSort(column.id)}
                        className={cn(
                          "-mx-1.5 inline-flex items-center gap-1 rounded-control px-1.5 py-1 hover:text-ink",
                          sorted && "text-ink",
                        )}
                      >
                        {column.header}
                        {sorted === "asc" ? (
                          <ArrowUp className="size-3.5" aria-hidden="true" />
                        ) : sorted === "desc" ? (
                          <ArrowDown className="size-3.5" aria-hidden="true" />
                        ) : (
                          <ChevronsUpDown className="size-3.5 opacity-50" aria-hidden="true" />
                        )}
                      </button>
                    ) : (
                      column.header || <span className="sr-only">Actions</span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {table.loading &&
              [0, 1, 2].map((i) => (
                <tr key={i} className="max-sm:block max-sm:px-4 max-sm:py-3">
                  {columns.map((column) => (
                    <td key={column.id} className="px-4 py-3 max-sm:block max-sm:px-0 max-sm:py-1">
                      <Skeleton className="h-4 w-full max-w-40" />
                    </td>
                  ))}
                </tr>
              ))}
            {!table.loading && table.total === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-ink-muted">
                  <p>Nothing matches{table.query.trim() ? ` “${table.query.trim()}”` : ""}.</p>
                  <Button variant="ghost" size="sm" className="mt-2" onClick={table.clear}>
                    Clear search and filters
                  </Button>
                </td>
              </tr>
            )}
            {table.rows.map((row) => (
              <tr
                key={rowKey(row)}
                {...rowProps?.(row)}
                className="align-middle hover:bg-surface-sunken/40 max-sm:block max-sm:space-y-1.5 max-sm:px-4 max-sm:py-3"
              >
                {columns.map((column) => (
                  <td
                    key={column.id}
                    data-label={column.hideLabelOnPhone ? undefined : column.header}
                    className={cn(
                      "px-4 py-3",
                      column.align === "right" && "text-right",
                      // Phone: stacked "Label  value" lines.
                      "max-sm:flex max-sm:items-center max-sm:gap-3 max-sm:p-0 max-sm:text-left",
                      !column.hideLabelOnPhone &&
                        column.header &&
                        "max-sm:before:w-20 max-sm:before:shrink-0 max-sm:before:text-xs max-sm:before:text-ink-muted max-sm:before:content-[attr(data-label)]",
                      column.className,
                    )}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(showPager || table.isFiltered) && !table.loading && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-ink-muted">
          <p aria-live="polite" className="tabular">
            {table.total === 0
              ? `No results (of ${table.count})`
              : `${table.range[0]}–${table.range[1]} of ${table.total}${
                  table.isFiltered ? ` (filtered from ${table.count})` : ""
                }`}
          </p>
          {showPager && (
            <nav aria-label={`${label} pages`} className="flex items-center gap-2">
              <Select
                aria-label="Rows per page"
                value={String(table.pageSize)}
                onChange={(e) => table.setPageSize(Number(e.target.value))}
                className="w-28 [&_select]:h-8"
              >
                {PAGE_SIZES.map((size) => (
                  <option key={size} value={size}>
                    {size} / page
                  </option>
                ))}
              </Select>
              <span className="px-1 tabular">
                Page {table.page} of {table.pageCount}
              </span>
              <Button
                variant="secondary"
                size="icon"
                className="size-8"
                aria-label="Previous page"
                disabled={table.page <= 1}
                onClick={() => table.setPage(table.page - 1)}
              >
                <ChevronLeft />
              </Button>
              <Button
                variant="secondary"
                size="icon"
                className="size-8"
                aria-label="Next page"
                disabled={table.page >= table.pageCount}
                onClick={() => table.setPage(table.page + 1)}
              >
                <ChevronRight />
              </Button>
            </nav>
          )}
        </div>
      )}
    </div>
  );
}
