import { Document, DocumentChunk, DocumentUploadResponse, ChatResponse } from '@/types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

async function fetchApi<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new ApiError(`API Error: ${errorText}`, response.status);
  }

  return response.json();
}

export const api = {
  // Document upload endpoint
  uploadDocument: async (file: File): Promise<DocumentUploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${API_BASE_URL}/api/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new ApiError(`Upload failed: ${errorText}`, response.status);
    }

    return response.json();
  },

  // Chat endpoint
  chat: (message: string, entityFilters?: string[]) =>
    fetchApi<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        message,
        entity_filters: entityFilters,
      }),
    }),

  // Document status endpoint
  getDocumentStatus: (documentId: string) =>
    fetchApi<{
      document_id: string;
      status: string;
      progress?: number;
      processing_stage?: string;
      searchable_capabilities?: {
        keyword: boolean;
        entity: boolean;
        semantic: boolean;
      };
      processed_chunks?: number;
      total_chunks?: number;
      entities_extracted?: number;
      embeddings_generated?: number;
    }>(`/api/status/${documentId}`),

  // System stats endpoint
  getStats: () => fetchApi<{
    documents_processed: number;
    total_chunks: number;
    queries_processed: number;
    avg_response_time_ms: number;
  }>('/api/stats'),
};

export default api;
