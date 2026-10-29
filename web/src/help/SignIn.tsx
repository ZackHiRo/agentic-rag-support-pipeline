import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2, Mail } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { requestMagicLink, verifyToken } from "@/hooks/auth";

/**
 * Inline passwordless sign-in. With the server's dev magic links (no mail
 * server) the link is verified immediately, so the flow never leaves the page.
 */
export function SignInForm({
  onSignedIn,
  submitLabel = "Continue",
  compact,
}: {
  onSignedIn: () => void;
  submitLabel?: string;
  compact?: boolean;
}) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sentTo, setSentTo] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await requestMagicLink(email, name);
      if (res.dev_link) {
        const token = new URL(res.dev_link, location.origin).searchParams.get("token")!;
        const user = await verifyToken(token);
        qc.setQueryData(["me"], user);
        onSignedIn();
      } else {
        setSentTo(email);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  if (sentTo) {
    return (
      <div className="flex items-start gap-3 rounded-xl bg-primary-soft p-4 text-sm">
        <Mail className="mt-0.5 size-4 text-primary" />
        <p>
          We sent a sign-in link to <strong>{sentTo}</strong>. Open it on this device to continue; your message is saved.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className={compact ? "grid gap-3 sm:grid-cols-[1fr_0.7fr]" : "space-y-3"}>
        <div className="space-y-1.5">
          <Label htmlFor="signin-email">Email</Label>
          <Input id="signin-email" type="email" required autoComplete="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="signin-name">
            Name <span className="font-normal text-faint">(optional)</span>
          </Label>
          <Input id="signin-name" autoComplete="nickname" placeholder="What should we call you?" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-faint">No password needed. Demo mode signs you in instantly instead of emailing a link.</p>
        <Button type="submit" disabled={busy || !email}>
          {busy ? <Loader2 className="animate-spin" /> : <ArrowRight />}
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
