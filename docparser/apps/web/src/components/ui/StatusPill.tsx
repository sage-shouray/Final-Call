import { DocumentStatus } from '@/types';
import { Badge, type BadgeVariant } from './Badge';
import { cn } from '@/lib/cn';

const statusConfig: Record<
  DocumentStatus,
  { label: string; variant: BadgeVariant }
> = {
  [DocumentStatus.UPLOADED]:   { label: 'Uploaded',   variant: 'neutral'  },
  [DocumentStatus.EXTRACTING]: { label: 'Extracting', variant: 'info'     },
  [DocumentStatus.EXTRACTED]:  { label: 'Extracted',  variant: 'info'     },
  [DocumentStatus.VALIDATING]: { label: 'Validating', variant: 'warning'  },
  [DocumentStatus.VALIDATED]:  { label: 'Validated',   variant: 'success'  },
  [DocumentStatus.GR_POSTING]: { label: 'GR Posting',  variant: 'warning'  },
  [DocumentStatus.GR_POSTED]:  { label: 'GR Posted',   variant: 'success'  },
  [DocumentStatus.POSTING]:    { label: 'Posting',     variant: 'warning'  },
  [DocumentStatus.POSTED]:     { label: 'Posted',      variant: 'success'  },
  [DocumentStatus.FAILED]:     { label: 'Failed',     variant: 'error'    },
};

const pulsingStatuses = new Set<DocumentStatus>([
  DocumentStatus.EXTRACTING,
  DocumentStatus.VALIDATING,
  DocumentStatus.POSTING,
]);

interface StatusPillProps {
  status:     DocumentStatus;
  className?: string;
}

export function StatusPill({ status, className }: StatusPillProps) {
  const { label, variant } = statusConfig[status] ?? { label: status, variant: 'neutral' as BadgeVariant };
  const isPulsing = pulsingStatuses.has(status);

  return (
    <Badge variant={variant} dot className={cn(isPulsing && 'animate-pulse', className)}>
      {label}
    </Badge>
  );
}
