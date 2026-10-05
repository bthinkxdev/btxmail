import { useMutation, useQuery, type UseQueryOptions } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, qs } from "./api";
import { useToast } from "./components/ui";
import type { Page } from "./types";

export const PAGE_SIZE = 25;

export function usePaged<T>(path: string, params: Record<string, string | number | boolean | undefined> = {}) {
  const [page, setPage] = useState(1);
  const filterKey = JSON.stringify(params);
  useEffect(() => setPage(1), [filterKey]); // new filters start at page 1
  const query = useQuery({
    queryKey: [path, params, page],
    queryFn: () => api.get<Page<T>>(`${path}${qs({ ...params, page, page_size: PAGE_SIZE })}`),
    placeholderData: (prev) => prev,
  });
  return { ...query, page, setPage };
}

export function useApiGet<T>(path: string, options?: Partial<UseQueryOptions<T>>) {
  return useQuery<T>({ queryKey: [path], queryFn: () => api.get<T>(path), ...options });
}

/** Mutation with toast feedback. `success` is the toast text, named after the action. */
export function useAction<TVars = void, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  opts: {
    success?: string | ((res: TRes, vars: TVars) => string);
    onSuccess?: (res: TRes, vars: TVars) => void;
  } = {},
) {
  const toast = useToast();
  return useMutation<TRes, unknown, TVars>({
    mutationFn: fn,
    onSuccess: (res, vars) => {
      if (opts.success) toast.ok(typeof opts.success === "function" ? opts.success(res, vars) : opts.success);
      opts.onSuccess?.(res, vars);
    },
    onError: (err) => toast.error(err),
  });
}

/** Debounced value for search boxes. */
export function useDebounced<T>(value: T, delay = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setV(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return v;
}
