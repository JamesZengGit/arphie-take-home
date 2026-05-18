'use client';

import { useState, useEffect } from 'react';
import { Header } from '@/components/ui/Header';
import { Sidebar } from '@/components/ui/Sidebar';
import { DocumentUpload } from '@/components/documents/DocumentUpload';
import { DocumentChat } from '@/components/documents/DocumentChat';
import { DocumentList } from '@/components/documents/DocumentList';
import { Toast } from '@/components/ui/Toast';
import api from '@/lib/api';
import { Document, DocumentStatus } from '@/types';

interface ChatMessage {
  id: string;
  type: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  sources?: any[];
}

export default function Home() {
  const [activeTab, setActiveTab] = useState('chat');
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [uploadStatus, setUploadStatus] = useState<DocumentStatus | null>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    loadDocuments();
  }, []);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const response = await fetch('http://localhost:8000/api/documents');
      if (response.ok) {
        const data = await response.json();
        setDocuments(data.documents || []);
      }
    } catch (error) {
      console.error('Failed to load documents:', error);
      setDocuments([]);
    }
    setLoading(false);
  };

  const handleDocumentUpload = async (file: File) => {
    try {
      setLoading(true);
      const response = await api.uploadDocument(file);

      if (response.document_id) {
        setUploadStatus({
          document_id: response.document_id,
          status: 'processing',
          progress: 0,
          processing_stage: 'uploading'
        });

        pollUploadStatus(response.document_id);

        setActiveTab('documents');

        setToast({ message: 'Document uploaded successfully!', type: 'success' });
      }

      await loadDocuments();

      return response;
    } catch (error) {
      console.error('Upload failed:', error);
      setToast({ message: 'Upload failed. Please try again.', type: 'error' });
      throw error;
    } finally {
      setLoading(false);
    }
  };

  const pollUploadStatus = async (documentId: string) => {
    const pollInterval = setInterval(async () => {
      try {
        const status = await api.getDocumentStatus(documentId);
        setUploadStatus(status);

        if (status.status === 'completed' || status.status === 'failed') {
          clearInterval(pollInterval);
          setUploadStatus(null);
          await loadDocuments();
        }
      } catch (error) {
        console.error('Status poll failed:', error);
        clearInterval(pollInterval);
        setUploadStatus(null);
      }
    }, 2000);
  };

  const handleChatMessage = async (message: string) => {
    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      type: 'user',
      content: message,
      timestamp: new Date()
    };

    setChatMessages(prev => [...prev, userMessage]);

    const response = await api.chat(message);

    const assistantMessage: ChatMessage = {
      id: (Date.now() + 1).toString(),
      type: 'assistant',
      content: response.response,
      timestamp: new Date(),
      sources: response.sources
    };

    setChatMessages(prev => [...prev, assistantMessage]);
  };

  const handleChatReset = () => {
    setChatMessages([]);
  };

  const renderContent = () => {
    switch (activeTab) {
      case 'chat':
        return (
          <div className="max-w-4xl mx-auto">
            <div className="mb-6">
              <h1 className="text-2xl font-bold text-gray-900 mb-2">
                Document Q&A Assistant
              </h1>
              <p className="text-gray-600">
                Upload documents and ask questions to get intelligent answers with source references
              </p>
            </div>
            <DocumentChat
              messages={chatMessages}
              onSendMessage={handleChatMessage}
              onReset={handleChatReset}
              loading={loading}
            />
          </div>
        );

      case 'documents':
        return (
          <div className="max-w-6xl mx-auto">
            <div className="mb-6">
              <h1 className="text-2xl font-bold text-gray-900 mb-2">
                Document Library
              </h1>
              <p className="text-gray-600">
                Manage your uploaded documents and track processing status
              </p>
            </div>
            <DocumentList
              documents={documents}
              loading={loading}
              onRefresh={loadDocuments}
            />
          </div>
        );

      case 'upload':
        return (
          <div className="max-w-4xl mx-auto">
            <div className="mb-6">
              <h1 className="text-2xl font-bold text-gray-900 mb-2">
                Upload Documents
              </h1>
              <p className="text-gray-600">
                Upload PDF, text, or markdown files for processing and analysis
              </p>
            </div>
            <DocumentUpload
              onUpload={handleDocumentUpload}
              uploadStatus={uploadStatus}
            />
          </div>
        );

      default:
        return renderContent();
    }
  };

  return (
    <div className="h-screen flex flex-col">
      <Header />

      <div className="flex-1 flex overflow-hidden">
        <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />

        <main className="flex-1 overflow-y-auto p-6">
          {renderContent()}
        </main>
      </div>

      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
}
