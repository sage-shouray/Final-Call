export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'retrying';

export interface ProcessingJob {
  id: string;
  documentId: string;
  status: JobStatus;
  progress: number;
  currentStep: string;
  totalSteps: number;
  startedAt?: string;
  completedAt?: string;
  errorMessage?: string;
  retryCount: number;
  maxRetries: number;
}

export interface JobEvent {
  jobId: string;
  documentId: string;
  event: 'progress' | 'completed' | 'failed';
  data: Partial<ProcessingJob>;
  timestamp: string;
}
