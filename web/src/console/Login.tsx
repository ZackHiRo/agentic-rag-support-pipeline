import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { LogoMark } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { api, type User } from "@/lib/api";

export function Login() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [email, setEmail] = useState("agent@everdawn.dev");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await api<User>("/api/auth/login", { method: "POST", json: { email, password } });
      qc.setQueryData(["me"], user);
      navigate("/console", { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex min-h-dvh items-center justify-center bg-bg px-4">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(50%_40%_at_50%_0%,color-mix(in_oklch,var(--primary)_12%,transparent),transparent)]" />
      <div className="relative w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <LogoMark className="size-10" />
          <h1 className="mt-4 text-xl font-semibold tracking-tight">Everdawn Support Console</h1>
          <p className="mt-1 text-sm text-muted">Sign in with your staff account</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-border bg-surface p-6 shadow-lift">
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus />
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <ArrowRight />} Sign in
          </Button>
        </form>
        <p className="mt-4 text-center text-xs text-faint">
          Demo accounts: agent@, lead@ or admin@everdawn.dev. The password is set by STAFF_DEMO_PASSWORD (see the README).
        </p>
      </div>
    </div>
  );
}
