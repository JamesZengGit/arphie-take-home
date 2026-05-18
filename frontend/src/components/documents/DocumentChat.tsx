'use client';

import { useState } from 'react';
import { Send, Bot, User, RefreshCw } from 'lucide-react';

interface ChatMessage {
  id: string;
  type: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  sources?: any[];
}

interface DocumentChatProps {
  messages: ChatMessage[];
  onSendMessage: (message: string) => Promise<void>;
  onReset: () => void;
  loading: boolean;
}

export function DocumentChat({ messages, onSendMessage, onReset, loading }: DocumentChatProps) {
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!input.trim() || sending) return;

    const message = input.trim();
    setInput('');
    setSending(true);

    try {
      await onSendMessage(message);
    } catch (error) {
      console.error('Failed to send message:', error);
    } finally {
      setSending(false);
    }
  };

  const formatTimestamp = (timestamp: Date) => {
    return timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="flex flex-col h-[600px] bg-white rounded-lg border shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b bg-[#F5F1E8]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center">
            <Bot className="w-5 h-5 text-white" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900">Document Q&A Assistant</h3>
            <p className="text-xs text-gray-600">Ask questions about your uploaded documents</p>
          </div>
        </div>
        <button
          onClick={onReset}
          className="text-sm bg-white hover:bg-gray-50 text-gray-700 px-3 py-1 rounded border"
        >
          Reset Conversation
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="text-center text-gray-500 mt-12">
            <Bot className="w-12 h-12 mx-auto mb-4 text-gray-300" />
            <h3 className="text-lg font-medium mb-2">Start a conversation</h3>
            <p className="text-sm">Ask questions about your uploaded documents.</p>
            <div className="mt-6 space-y-2">
              <p className="text-xs font-medium text-gray-700">Try asking:</p>
              <div className="space-y-1 text-xs text-gray-600">
                <p>"What are the key findings in this document?"</p>
                <p>"Summarize the main recommendations"</p>
                <p>"What does it say about [specific topic]?"</p>
              </div>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`flex gap-3 ${
                message.type === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {message.type === 'assistant' && (
                <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center flex-shrink-0">
                  <Bot className="w-4 h-4 text-white" />
                </div>
              )}

              <div
                className={`max-w-[70%] rounded-lg px-4 py-2 ${
                  message.type === 'user'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-900'
                }`}
              >
                <p className="text-sm whitespace-pre-wrap">{message.content}</p>

                {message.sources && message.sources.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-gray-200">
                    <p className="text-xs text-gray-600 font-medium mb-1">Sources:</p>
                    {message.sources.map((source, index) => (
                      <div key={index} className="text-xs text-gray-600">
                        📄 {source.filename}
                        {source.page_number && ` (page ${source.page_number})`}
                      </div>
                    ))}
                  </div>
                )}

                <p className="text-xs opacity-70 mt-1">
                  {formatTimestamp(message.timestamp)}
                </p>
              </div>

              {message.type === 'user' && (
                <div className="w-8 h-8 bg-gray-300 rounded-full flex items-center justify-center flex-shrink-0">
                  <User className="w-4 h-4 text-gray-600" />
                </div>
              )}
            </div>
          ))
        )}

        {sending && (
          <div className="flex gap-3 justify-start">
            <div className="w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center flex-shrink-0">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <div className="bg-gray-100 rounded-lg px-4 py-2">
              <div className="flex items-center space-x-2">
                <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-blue-600"></div>
                <p className="text-sm text-gray-600">Thinking...</p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="p-4 border-t">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            placeholder="Ask about your documents..."
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={sending || loading}
          />
          <button
            type="submit"
            disabled={!input.trim() || sending || loading}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>

        <div className="mt-2 flex flex-wrap gap-2">
          <button
            onClick={() => setInput("What are the key findings in this document?")}
            className="text-xs bg-gray-100 hover:bg-gray-200 rounded-full px-3 py-1 transition-colors"
          >
            🔍 Key findings
          </button>
          <button
            onClick={() => setInput("Summarize the main recommendations")}
            className="text-xs bg-gray-100 hover:bg-gray-200 rounded-full px-3 py-1 transition-colors"
          >
            📋 Summarize
          </button>
          <button
            onClick={() => setInput("What are the important dates and deadlines?")}
            className="text-xs bg-gray-100 hover:bg-gray-200 rounded-full px-3 py-1 transition-colors"
          >
            📅 Dates & deadlines
          </button>
        </div>
      </div>
    </div>
  );
}