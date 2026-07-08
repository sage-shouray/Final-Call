import { useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { UploadCloud, FileText, AlertCircle, X } from 'lucide-react';
import { cn } from '@/lib/cn';

const ACCEPTED_MIME: Record<string, string[]> = {
  'application/pdf':  ['.pdf'],
  'image/png':        ['.png'],
  'image/jpeg':       ['.jpg', '.jpeg'],
  'image/tiff':       ['.tiff', '.tif'],
  'image/webp':       ['.webp'],
};
const MAX_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB

interface FileDropzoneProps {
  file:         File | null;
  progress:     number;          // 0–100
  uploading:    boolean;
  error:        string | null;
  onFileSelect: (file: File) => void;
  onClear:      () => void;
}

function fileSizeLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function FileDropzone({
  file, progress, uploading, error, onFileSelect, onClear,
}: FileDropzoneProps) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      if (accepted[0]) onFileSelect(accepted[0]);
    },
    [onFileSelect],
  );

  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    onDrop,
    accept:   ACCEPTED_MIME,
    maxSize:  MAX_SIZE_BYTES,
    multiple: false,
    disabled: uploading,
  });

  const rejection = fileRejections[0]?.errors[0]?.message ?? null;
  const displayError = error ?? rejection;

  return (
    <div className="space-y-2">
      <div
        {...getRootProps()}
        className={cn(
          'relative flex min-h-[180px] cursor-pointer flex-col items-center justify-center gap-3',
          'rounded-xl border-2 border-dashed transition-all duration-200',
          uploading && 'pointer-events-none',
          isDragActive
            ? 'border-indigo-400 bg-indigo-50 dark:bg-indigo-950/50'
            : file
              ? 'border-indigo-300 bg-indigo-50/40 dark:bg-indigo-950/30'
              : displayError
                ? 'border-red-300 bg-red-50/30 dark:bg-red-950/20'
                : 'border-neutral-200 bg-white hover:border-indigo-300 hover:bg-indigo-50/20 dark:border-neutral-700 dark:bg-neutral-800 dark:hover:border-indigo-600 dark:hover:bg-indigo-950/20',
        )}
      >
        <input {...getInputProps()} />

        {!file ? (
          <>
            <div className={cn(
              'flex h-14 w-14 items-center justify-center rounded-full transition-colors duration-200',
              isDragActive ? 'bg-indigo-100 dark:bg-indigo-900' : 'bg-neutral-100 dark:bg-neutral-700',
            )}>
              <UploadCloud className={cn('h-7 w-7 transition-colors duration-200', isDragActive ? 'text-indigo-500' : 'text-neutral-400')} />
            </div>
            <div className="text-center">
              <p className={cn('text-sm font-medium', isDragActive ? 'text-indigo-700 dark:text-indigo-300' : 'text-neutral-600 dark:text-neutral-400')}>
                {isDragActive ? 'Release to upload' : 'Drop your file here'}
              </p>
              {!isDragActive && <p className="mt-0.5 text-xs text-neutral-400">or click to browse</p>}
            </div>
            <p className="text-xs text-neutral-400">PDF · PNG · JPEG · TIFF · WebP — max 20 MB</p>
          </>
        ) : (
          <div className="flex w-full items-center gap-4 px-6">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-indigo-100">
              <FileText className="h-6 w-6 text-indigo-600" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="truncate text-sm font-semibold text-neutral-800 dark:text-neutral-200">{file.name}</p>
              <p className="mt-0.5 text-xs text-neutral-400">
                {fileSizeLabel(file.size)} · {file.type || 'unknown type'}
              </p>
            </div>
            {!uploading && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onClear(); }}
                className="flex h-7 w-7 items-center justify-center rounded-full text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 transition-colors"
                aria-label="Remove file"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Upload progress bar */}
      {uploading && (
        <div className="space-y-1">
          <div className="h-[3px] w-full overflow-hidden rounded-full bg-neutral-100 dark:bg-neutral-700">
            <div
              className="h-full rounded-full bg-indigo-500 transition-all duration-300 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-right text-xs text-neutral-400">{progress}%</p>
        </div>
      )}

      {/* Error */}
      {displayError && !uploading && (
        <div className="flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {displayError}
        </div>
      )}
    </div>
  );
}
