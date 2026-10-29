import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type User } from "@/lib/api";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<User | null>("/api/auth/me"), staleTime: 60_000 });
}

/**
 * Passwordless sign-in. Returns the dev link when the server runs with
 * DEV_MAGIC_LINKS (no mail server): the UI then verifies it right away.
 */
export async function requestMagicLink(email: string, displayName = "") {
  return api<{ sent: boolean; dev_link: string | null }>("/api/auth/magic-link", {
    method: "POST",
    json: { email, display_name: displayName },
  });
}

export async function verifyToken(token: string) {
  return api<User>("/api/auth/verify", { method: "POST", json: { token } });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => {
      qc.setQueryData(["me"], null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
  });
}
