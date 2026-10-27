import "./index.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/misc";
import { ApiError } from "@/lib/api";
import { ArticlePage } from "./help/ArticlePage";
import { HelpLayout } from "./help/HelpLayout";
import { Home } from "./help/Home";
import { MyTickets } from "./help/MyTickets";
import { TicketPage } from "./help/TicketPage";
import { Verify } from "./help/Verify";

// Staff-only screens are split out so players never download them (or the charting library).
const ConsoleApp = lazy(() => import("./console/ConsoleApp"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (n, err) => !(err instanceof ApiError && err.status < 500) && n < 2,
      refetchOnWindowFocus: true,
    },
  },
});

const router = createBrowserRouter([
  {
    element: <HelpLayout />,
    children: [
      { path: "/", element: <Home /> },
      { path: "/articles/:slug", element: <ArticlePage /> },
      { path: "/tickets", element: <MyTickets /> },
      { path: "/tickets/:ref", element: <TicketPage /> },
      { path: "/auth/verify", element: <Verify /> },
    ],
  },
  {
    path: "/console/*",
    element: (
      <Suspense fallback={<div className="h-dvh bg-bg" />}>
        <ConsoleApp />
      </Suspense>
    ),
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <RouterProvider router={router} />
        <Toaster position="bottom-center" toastOptions={{ className: "!rounded-xl !border-border !bg-surface !text-text !shadow-lift" }} />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
