import { ArrowLeft, MessageCircleQuestion } from "lucide-react";
import { Link, useParams } from "react-router";
import { Button } from "@/components/ui/button";
import { Prose, Skeleton } from "@/components/ui/misc";
import { ArticleFeedback, useArticle } from "./ArticleSheet";

export function ArticlePage() {
  const { slug = "" } = useParams();
  const article = useArticle(slug);
  return (
    <div className="mx-auto max-w-2xl px-4 pt-8 pb-16">
      <Link to="/" className="mb-6 inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-text">
        <ArrowLeft className="size-4" /> Help center
      </Link>
      {article.isError ? (
        <p className="text-muted">This article doesn't exist or was moved.</p>
      ) : !article.data ? (
        <div className="space-y-3">
          <Skeleton className="h-9 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="mt-8 h-40" />
        </div>
      ) : (
        <article>
          <p className="mb-2 text-[12px] font-medium tracking-wide text-dawn-text uppercase">{article.data.category}</p>
          <h1 className="text-3xl font-semibold tracking-tight text-balance">{article.data.title}</h1>
          <p className="mt-2 text-muted">{article.data.summary}</p>
          <Prose className="mt-8 text-[15.5px]">{article.data.body}</Prose>
          <div className="mt-10 rounded-2xl border border-border bg-surface p-5 shadow-soft">
            <ArticleFeedback slug={slug} />
          </div>
          <div className="mt-4 flex items-center justify-between gap-4 rounded-2xl bg-surface-2 p-5">
            <div className="flex items-center gap-3">
              <MessageCircleQuestion className="size-5 text-primary" />
              <p className="text-sm">Still stuck? Our assistant can look at your specific case.</p>
            </div>
            <Button asChild size="sm">
              <Link to="/">Ask us</Link>
            </Button>
          </div>
        </article>
      )}
    </div>
  );
}
