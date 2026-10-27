import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { verifyToken } from "@/hooks/auth";

/** Landing page for emailed magic links. The saved draft (if any) is restored on the home page. */
export function Verify() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [error, setError] = useState("");
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return;
    once.current = true;
    verifyToken(params.get("token") ?? "")
      .then((user) => {
        qc.setQueryData(["me"], user);
        let hasDraft = false;
        try {
          hasDraft = !!sessionStorage.getItem("evd-draft");
        } catch {
          /* ignore */
        }
        navigate(hasDraft ? "/" : "/tickets", { replace: true });
      })
      .catch((e: Error) => setError(e.message));
  }, [params, navigate, qc]);

  return (
    <div className="mx-auto flex max-w-sm flex-col items-center px-4 py-24 text-center">
      {error ? (
        <>
          <h1 className="text-lg font-semibold">That link didn't work</h1>
          <p className="mt-2 text-sm text-muted">{error}</p>
          <Link to="/tickets" className="mt-6 text-sm font-medium text-primary hover:underline">
            Request a new link
          </Link>
        </>
      ) : (
        <>
          <Loader2 className="size-6 animate-spin text-primary" />
          <p className="mt-4 text-sm text-muted">Signing you in…</p>
        </>
      )}
    </div>
  );
}
