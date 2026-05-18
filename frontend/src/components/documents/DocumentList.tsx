'use client';

import { useState } from 'react';
import { File, Clock, CheckCircle, AlertCircle, RefreshCw } from 'lucide-react';
import { Document } from '@/types';

interface DocumentListProps {
  documents: Document[];
  loading: boolean;
  onRefresh: () => void;
}

export function DocumentList({ documents, loading, onRefresh }: DocumentListProps) {
  const [sortBy, setSortBy] = useState<'name' | 'date' | 'status'>('date');

  const sortedDocuments = [...documents].sort((a, b) => {
    switch (sortBy) {
      case 'name':
        return a.filename.localeCompare(b.filename);
      case 'date':
        return new Date(b.upload_timestamp).getTime() - new Date(a.upload_timestamp).getTime();
      case 'status':
        return a.processing_status.localeCompare(b.processing_status);
      default:
        return 0;
    }
  });

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-600" />;
      case 'processing':
        return <Clock className="w-4 h-4 text-blue-600 animate-pulse" />;
      case 'failed':
        return <AlertCircle className="w-4 h-4 text-red-600" />;
      default:
        return <Clock className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusBadge = (status: string) => {
    const baseClasses = "px-2 py-1 rounded-full text-xs font-medium";

    switch (status) {
      case 'completed':
        return `${baseClasses} bg-green-100 text-green-800`;
      case 'processing':
        return `${baseClasses} bg-blue-100 text-blue-800`;
      case 'failed':
        return `${baseClasses} bg-red-100 text-red-800`;
      default:
        return `${baseClasses} bg-gray-100 text-gray-800`;
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  if (loading) {
    return (
      <div className="text-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-4"></div>
        <p className="text-gray-500">Loading documents...</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">
            Uploaded Documents ({documents.length})
          </h2>
          <p className="text-sm text-gray-600">
            Manage and monitor your document processing status
          </p>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center space-x-2 px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          <span>Refresh</span>
        </button>
      </div>

      {/* Sort Controls */}
      <div className="flex items-center space-x-4">
        <span className="text-sm text-gray-600">Sort by:</span>
        <div className="flex space-x-2">
          {[
            { key: 'date', label: 'Date' },
            { key: 'name', label: 'Name' },
            { key: 'status', label: 'Status' }
          ].map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setSortBy(key as 'name' | 'date' | 'status')}
              className={`px-3 py-1 rounded text-sm transition-colors ${
                sortBy === key
                  ? 'bg-blue-100 text-blue-700'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Documents List */}
      {sortedDocuments.length === 0 ? (
        <div className="text-center py-12 bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
          <File className="w-12 h-12 mx-auto mb-4 text-gray-300" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No documents yet</h3>
          <p className="text-gray-600">Upload your first document to get started</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Document
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Progress
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Uploaded
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {sortedDocuments.map((doc) => (
                  <tr key={doc.document_id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="flex items-center space-x-3">
                        <File className="w-8 h-8 text-blue-600" />
                        <div>
                          <p className="text-sm font-medium text-gray-900">
                            {doc.filename}
                          </p>
                          <p className="text-sm text-gray-500">
                            {doc.content_type}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center space-x-2">
                        {getStatusIcon(doc.processing_status)}
                        <span className={getStatusBadge(doc.processing_status)}>
                          {doc.processing_status.charAt(0).toUpperCase() + doc.processing_status.slice(1)}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="space-y-1">
                        {doc.total_chunks > 0 && (
                          <>
                            <div className="flex items-center justify-between text-xs text-gray-600">
                              <span>Chunks processed</span>
                              <span>{doc.processed_chunks}/{doc.total_chunks}</span>
                            </div>
                            <div className="w-full bg-gray-200 rounded-full h-2">
                              <div
                                className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                                style={{
                                  width: `${(doc.processed_chunks / doc.total_chunks) * 100}%`
                                }}
                              ></div>
                            </div>
                          </>
                        )}
                        {doc.total_chunks === 0 && doc.processing_status === 'processing' && (
                          <div className="text-xs text-gray-500">Initializing...</div>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-900">
                        {formatDate(doc.upload_timestamp)}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
