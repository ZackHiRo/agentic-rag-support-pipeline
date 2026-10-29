import { useQuery } from "@tanstack/react-query";
import { ExternalLink, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Prose, Skeleton } from "@/components/ui/misc";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { type Article, api } from "@/lib/api";

export function useArticle(slug: string | null) {
  return useQuery({
    queryKey: ["article", slug],
    queryFn: () => api<Article>(`/api/kb/articles/${slug}`),
    enabled: !!slug,
    staleTime: 5 * 60_000,
  });
}

export function ArticleFeedback({
  slug,
  query = "",
  onSolved,
}: {
  slug: string;
  query?: string;
  onSolved?: () => void;
}) {
  const [sent, setSent] = useState<null | boolean>(null);
  const send = async (helpful: boolean) => {
    setSent(helpful);
    await api(`/api/kb/articles/${slug}/feedback`, { method: "POST", json: { helpful, query } }).catch(() => {});
    if (helpful) {
      toast.success("Glad that helped!", { description: "No ticket needed. Happy gaming." });
      onSolved?.();
    }
  };
  if (sent === false) {
    return <p className="text-sm text-muted">Thanks for telling us. Close this and send us your question; we'll take it from there.</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <span className="text-sm text-muted">Did this solve your problem?</span>
      <span className="flex gap-2">
      <Button size="sm" variant="secondary" onClick={() => send(true)} disabled={sent !== null}>
        <ThumbsUp /> Yes, solved
      </Button>
      <Button size="sm" variant="ghost" onClick={() => send(false)} disabled={sent !== null}>
        <ThumbsDown /> Not quite
      </Button>
      </span>
    </div>
  );
}

export function ArticleSheet({
  slug,
  onOpenChange,
  query,
  onSolved,
  showFeedback = true,
}: {
  slug: string | null;
  onOpenChange: (open: boolean) => void;
  query?: string;
  onSolved?: () => void;
  showFeedback?: boolean;
}) {
  const article = useArticle(slug);
  return (
    <Sheet open={!!slug} onOpenChange={onOpenChange}>
      <SheetContent aria-describedby={undefined}>
        <div className="border-b border-border px-6 pt-6 pb-4 pr-12">
          <div className="mb-1.5 flex items-center gap-3">
            <p className="text-[12px] font-medium tracking-wide text-dawn-text uppercase">Help article</p>
            {slug && (
              <Link to={`/articles/${slug}`} className="inline-flex items-center gap-1 text-[12px] text-faint hover:text-text">
                Open page <ExternalLink className="size-3" />
              </Link>
            )}
          </div>
          {article.data ? (
            <SheetTitle className="text-xl font-semibold tracking-tight text-balance">{article.data.title}</SheetTitle>
          ) : (
            <>
              <SheetTitle className="sr-only">Loading article</SheetTitle>
              <Skeleton className="h-7 w-3/4" />
            </>
          )}
          {article.data?.summary && <SheetDescription className="mt-1.5 text-sm text-muted">{article.data.summary}</SheetDescription>}
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {article.data ? (
            <Prose>{article.data.body}</Prose>
          ) : (
            <div className="space-y-3">
              {[90, 75, 85, 60, 80].map((w) => (
                <Skeleton key={w} className="h-4" style={{ width: `${w}%` }} />
              ))}
            </div>
          )}
        </div>
        {slug && showFeedback && (
          <div className="border-t border-border bg-surface-2/50 px-6 py-4">
            <ArticleFeedback slug={slug} query={query} onSolved={onSolved} />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
