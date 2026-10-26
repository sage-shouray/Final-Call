import {
  format,
  formatDistanceToNow,
  parseISO,
  isValid,
} from 'date-fns';

function parse(value: string | Date): Date {
  if (value instanceof Date) return value;
  const d = parseISO(value);
  return isValid(d) ? d : new Date(value);
}

/** "14 Mar 2026" */
export function formatDate(value: string | Date): string {
  return format(parse(value), 'd MMM yyyy');
}

/** "14 Mar 2026, 09:42 AM" */
export function formatDateTime(value: string | Date): string {
  return format(parse(value), 'd MMM yyyy, hh:mm aa');
}

/** "2 hours ago" / "just now" */
export function timeAgo(value: string | Date): string {
  return formatDistanceToNow(parse(value), { addSuffix: true });
}

/** "14-03-2026" (DD-MM-YYYY, SAP invoice date format) */
export function formatSAPDate(value: string | Date): string {
  return format(parse(value), 'dd-MM-yyyy');
}
