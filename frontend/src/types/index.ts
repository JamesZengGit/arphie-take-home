export interface Document {
  document_id: string;
  filename: string;
  content_type: string;
  upload_timestamp: string;
  processing_status: 'processing' | 'completed' | 'failed';
  total_chunks: number;
  processed_chunks: number;
}

export interface DocumentChunk {
  chunk_id: number;
  chunk_text: string;
  filename: string;
  content_type: string;
  entities: Record<string, string[]>;
  page_number?: number;
  section_header?: string;
  similarity_score: number;
}

export interface DocumentUploadResponse {
  document_id: string;
  filename: string;
  status: string;
  message: string;
}

export interface ChatResponse {
  response: string;
  sources: DocumentChunk[];
  stats: {
    processing_time_ms: number;
    candidates_found: number;
    final_results: number;
  };
  search_strategy: string;
}

export interface DocumentStatus {
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
}

export interface SystemStats {
  documents_processed: number;
  total_chunks: number;
  queries_processed: number;
  avg_response_time_ms: number;
}