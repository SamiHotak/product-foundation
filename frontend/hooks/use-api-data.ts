"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { errorMessage } from "@/lib/api";

/**
 * Load data when the component appears (and again with `reload()` after a change).
 *
 *   const { data, error, reload } = useApiData(() => unwrap(api.GET("/api/...")));
 *
 * `data` is null while the first load runs (show a skeleton). A failed reload keeps the
 * old data on screen and sets `error`. `setData` updates the list right away (optimistic).
 */
export function useApiData<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  const reload = useCallback(async () => {
    try {
      const value = await loadRef.current();
      setData(value);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    // Initial load (data fetching from an external system).
    void reload();
  }, [reload]);

  return { data, error, reload, setData };
}
