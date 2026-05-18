'use client';

import { useState, useRef } from 'react';
import { Upload, File, CheckCircle, AlertCircle } from 'lucide-react';
import { DocumentStatus } from '@/types';

interface DocumentUploadProps {
  onUpload: (file: File) => Promise<any>;
  uploadStatus: DocumentStatus | null;
}

export function DocumentUpload({ onUpload, uploadStatus }: DocumentUploadProps) {
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFileUpload(files[0]);
    }
  };

  const handleFileUpload = async (file: File) => {
    const allowedTypes = ['application/pdf', 'text/plain', 'text/markdown'];
    if (!allowedTypes.includes(file.type) && !file.name.endsWith('.md')) {
      setError('Only PDF, text, and markdown files are supported');
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      setError('File size must be less than 10MB');
      return;
    }

    setError(null);
    setUploading(true);

    try {
      await onUpload(file);
    } catch (err: any) {
      setError(err.message || 'Upload failed. Please try again.');
    } finally {
      setUploading(false);
    }
  };

  const getStatusDisplay = () => {
    if (!uploadStatus) return null;

    const { status, progress, processing_stage } = uploadStatus;

    if (status === 'processing') {
      return (
        <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="flex items-center space-x-3">
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
            <div className="flex-1">
              <p className="text-sm font-medium text-blue-900">
                Processing document...
              </p>
              <p className="text-xs text-blue-700">
                {processing_stage || 'Analyzing content'}
              </p>
              {progress !== undefined && (
                <div className="mt-2 w-full bg-blue-200 rounded-full h-2">
                  <div
                    className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  ></div>
                </div>
              )}
            </div>
          </div>
        </div>
      );
    }

    if (status === 'completed') {
      return (
        <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-center space-x-3">
            <CheckCircle className="h-5 w-5 text-green-600" />
            <div>
              <p className="text-sm font-medium text-green-900">
                Document processed successfully!
              </p>
              <p className="text-xs text-green-700">
                Ready for questions and analysis
              </p>
            </div>
          </div>
        </div>
      );
    }

    if (status === 'failed') {
      return (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-center space-x-3">
            <AlertCircle className="h-5 w-5 text-red-600" />
            <div>
              <p className="text-sm font-medium text-red-900">
                Processing failed
              </p>
              <p className="text-xs text-red-700">
                Please try uploading again
              </p>
            </div>
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <div className="space-y-4">
      {/* Upload Area */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`
          relative border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer
          ${dragOver ? 'border-blue-400 bg-blue-50' : 'border-gray-300'}
          ${uploading ? 'opacity-50 pointer-events-none' : 'hover:border-blue-400 hover:bg-blue-50'}
        `}
      >
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          accept=".pdf,.txt,.md,.markdown"
          onChange={handleInputChange}
        />
        <div className="space-y-4">
          <div className="mx-auto w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center">
            <Upload className="w-8 h-8 text-gray-400" />
          </div>

          <div>
            <h3 className="text-lg font-medium text-gray-900">
              Upload Document
            </h3>
            <p className="text-gray-600">
              Drag and drop files here
            </p>
            <p className="text-sm text-blue-600 mt-1">
              or click to select
            </p>
          </div>

          <div className="text-sm text-gray-500">
            <p>Supported formats: PDF, TXT, MD</p>
            <p>Maximum size: 10MB</p>
          </div>

          {uploading && (
            <div className="flex items-center justify-center space-x-2">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
              <span className="text-blue-600">Uploading...</span>
            </div>
          )}
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-center space-x-3">
            <AlertCircle className="h-5 w-5 text-red-600" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        </div>
      )}

      {/* Status Display */}
      {getStatusDisplay()}

      {/* Instructions */}
      <div className="bg-gray-50 rounded-lg p-4">
        <h4 className="text-sm font-medium text-gray-900 mb-2">
          How it works:
        </h4>
        <ul className="text-sm text-gray-600 space-y-1">
          <li>• Upload documents in PDF, text, or markdown format</li>
          <li>• Our AI extracts entities and creates searchable chunks</li>
          <li>• Ask questions about your documents using natural language</li>
          <li>• Get intelligent answers with source references</li>
        </ul>
      </div>
    </div>
  );
}
