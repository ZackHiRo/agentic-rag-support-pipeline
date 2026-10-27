import { FileText, X } from "lucide-react";
import { useEffect, useMemo } from "react";
import { toast } from "sonner";
import { formatBytes } from "@/lib/utils";

export const ACCEPT = "image/png,image/jpeg,image/webp,image/gif,text/plain,.log,.txt";
const MAX_MB = 8;
const MAX_FILES = 6;

export function acceptFiles(current: File[], incoming: FileList | File[]): File[] {
  const next = [...current];
  for (const f of Array.from(incoming)) {
    const ok = f.type.startsWith("image/") || f.type === "text/plain" || /\.(txt|log)$/i.test(f.name);
    if (!ok) {
      toast.error(`${f.name}: only screenshots and .txt/.log files can be attached.`);
      continue;
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      toast.error(`${f.name} is larger than ${MAX_MB} MB.`);
      continue;
    }
    if (next.length >= MAX_FILES) {
      toast.error(`You can attach up to ${MAX_FILES} files.`);
      break;
    }
    next.push(f);
  }
  return next;
}

/** Files pasted from the clipboard (screenshots), for onPaste handlers. */
export function filesFromClipboard(e: React.ClipboardEvent): File[] {
  return Array.from(e.clipboardData.files ?? []);
}

function Thumb({ file, onRemove }: { file: File; onRemove: () => void }) {
  const url = useMemo(() => (file.type.startsWith("image/") ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url]);
  return (
    <div className="group relative flex h-16 items-center gap-2 overflow-hidden rounded-lg border border-border bg-surface-2 pr-3">
      {url ? (
        <img src={url} alt="" className="h-full w-16 object-cover" />
      ) : (
        <span className="flex h-full w-12 items-center justify-center bg-surface-3">
          <FileText className="size-5 text-muted" />
        </span>
      )}
      <div className="min-w-0">
        <p className="max-w-36 truncate text-[12.5px] font-medium">{file.name}</p>
        <p className="text-[11.5px] text-faint">{formatBytes(file.size)}</p>
      </div>
      <button
        type="button"
        onClick={onRemove}
        className="absolute top-1 right-1 rounded-full bg-bg/80 p-0.5 text-muted opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100"
        aria-label={`Remove ${file.name}`}
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}

export function AttachmentList({ files, onChange }: { files: File[]; onChange: (f: File[]) => void }) {
  if (!files.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {files.map((f, i) => (
        <Thumb key={`${f.name}-${f.size}-${i}`} file={f} onRemove={() => onChange(files.filter((_, j) => j !== i))} />
      ))}
    </div>
  );
}
