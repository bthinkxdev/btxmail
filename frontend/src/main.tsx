import "@fontsource/instrument-sans/400.css";
import "@fontsource/instrument-sans/500.css";
import "@fontsource/instrument-sans/600.css";
import "@fontsource/instrument-sans/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./styles.css";

import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { ApiError } from "./api";
import App from "./App";
import { AuthProvider } from "./auth";
import { ToastProvider } from "./components/ui";
import { PwaStatus, registerServiceWorker } from "./pwa";
import { syncPushSubscription } from "./push";

registerServiceWorker();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
  mutationCache: new MutationCache({
    onSuccess: () => {
      // Any change may affect counters/usage shown elsewhere.
      void queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
  }),
});

// Messages from the service worker: refresh data after a push, re-register after the browser rotated keys.
navigator.serviceWorker?.addEventListener("message", (event: MessageEvent<{ type?: string }>) => {
  if (event.data?.type === "push") void queryClient.invalidateQueries();
  if (event.data?.type === "pushsubscriptionchange") void syncPushSubscription();
});

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ToastProvider>
          <PwaStatus />
          <AuthProvider>
            <App />
          </AuthProvider>
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
