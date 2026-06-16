export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, string[]>;
  traceId?: string;
}

export interface ApiResponse<T> {
  data: T;
  message?: string;
}

export interface HealthCheckResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  services: {
    database: 'up' | 'down';
    redis: 'up' | 'down';
    sap: 'up' | 'down';
  };
  timestamp: string;
}
