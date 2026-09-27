"use client";

import { useMemo, useState } from "react";

export type SortDirection = "asc" | "desc";

export type Column<T> = {
  id: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  /** Makes the column sortable. Return a string or number (null sorts last). */
  sortValue?: (row: T) => string | number | null;
  /** Classes for the header and cells (e.g. a width). */
  className?: string;
  align?: "left" | "right";
  /** Hide the header text on phones (cells stack as "Label: value"). Use for the main column. */
  hideLabelOnPhone?: boolean;
};

export type Filter<T> = {
  id: string;
  /** Screen-reader label of the select, e.g. "Role". */
  label: string;
  /** First option, e.g. "All roles". */
  allLabel: string;
  options: { value: string; label: string }[];
  test: (row: T, value: string) => boolean;
};

type Options<T> = {
  /** null while loading (the table shows skeleton rows). */
  rows: T[] | null;
  columns: Column<T>[];
  /** Text to search in (lower-cased by the hook). Leave out for no search box. */
  searchText?: (row: T) => string;
  filters?: Filter<T>[];
  initialSort?: { id: string; direction: SortDirection };
  pageSize?: number;
};

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function compare(a: string | number | null, b: string | number | null): number {
  if (a === b) return 0;
  if (a === null) return 1; // empty values last, in both directions
  if (b === null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return collator.compare(String(a), String(b));
}

/**
 * Search, filter, sort and page a list in the browser. Good up to a few thousand rows.
 * For bigger lists, keep the same return shape and fetch each page from the API instead,
 * so <DataTable> stays the same.
 */
export function useDataTable<T>({
  rows,
  columns,
  searchText,
  filters = [],
  initialSort,
  pageSize: initialPageSize = 10,
}: Options<T>) {
  const [query, setQueryState] = useState("");
  const [filterValues, setFilterValues] = useState<Record<string, string>>({});
  const [sort, setSort] = useState(initialSort ?? null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSizeState] = useState(initialPageSize);

  const filtered = useMemo(() => {
    if (rows === null) return null;
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let result = rows.filter((row) => {
      if (words.length && searchText) {
        const text = searchText(row).toLowerCase();
        if (!words.every((w) => text.includes(w))) return false;
      }
      return filters.every((f) => !filterValues[f.id] || f.test(row, filterValues[f.id]!));
    });
    const column = sort && columns.find((c) => c.id === sort.id);
    if (sort && column?.sortValue) {
      const value = column.sortValue;
      const sign = sort.direction === "asc" ? 1 : -1;
      result = [...result].sort((a, b) => {
        const va = value(a);
        const vb = value(b);
        // Nulls stay last whatever the direction.
        if (va === null || vb === null) return compare(va, vb);
        return sign * compare(va, vb);
      });
    }
    return result;
  }, [rows, query, searchText, filters, filterValues, sort, columns]);

  const total = filtered?.length ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(page, pageCount); // the list got shorter (e.g. a row was deleted)
  const start = (current - 1) * pageSize;

  return {
    columns,
    filters,
    loading: rows === null,
    /** Rows on this page. */
    rows: filtered?.slice(start, start + pageSize) ?? [],
    /** Rows before search and filters. */
    count: rows?.length ?? 0,
    /** Rows after search and filters. */
    total,
    query,
    setQuery: (value: string) => {
      setQueryState(value);
      setPage(1);
    },
    filterValues,
    setFilter: (id: string, value: string) => {
      setFilterValues((prev) => ({ ...prev, [id]: value }));
      setPage(1);
    },
    sort,
    /** Click on a header: ascending, then descending. */
    toggleSort: (id: string) =>
      setSort((prev) =>
        prev?.id === id
          ? { id, direction: prev.direction === "asc" ? "desc" : "asc" }
          : { id, direction: "asc" },
      ),
    page: current,
    pageCount,
    setPage,
    pageSize,
    setPageSize: (size: number) => {
      setPageSizeState(size);
      setPage(1);
    },
    /** Range shown, 1-based: [first, last]. */
    range: [total === 0 ? 0 : start + 1, Math.min(start + pageSize, total)] as const,
    searchable: Boolean(searchText),
    isFiltered: query.trim() !== "" || Object.values(filterValues).some(Boolean),
    clear: () => {
      setQueryState("");
      setFilterValues({});
      setPage(1);
    },
  };
}

export type DataTableState<T> = ReturnType<typeof useDataTable<T>>;
