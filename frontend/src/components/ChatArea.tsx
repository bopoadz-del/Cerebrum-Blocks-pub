import React, { useState, useRef, useEffect } from 'react';
import {
  Send,
  Paperclip,
  X,
  FileText,
  Loader2,
  Zap,
  PanelLeft,
  PanelRight,
  Sun,
  Moon,
} from 'lucide-react';
import type { Message, ProcessingState } from '@/types';
import { useTheme } from '@/context/ThemeContext';

interface ChatAreaProps {
  messages: Message[];
  onSendMessage: (content: string, files: File[]) => void;
  processing: ProcessingState;
  isLeftOpen: boolean;
  isRightOpen: boolean;
  onToggleLeft: () => void;
  onToggleRight: () => void;
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user';
  const isError = message.role === 'error';
  const isSystem = message.role === 'system';

  const bgColor = isUser
    ? 'bg-[hsl(var(--chat-user))] text-white'
    : isError
    ? 'bg-[hsl(var(--chat-error))] text-white'
    : isSystem
    ? 'bg-[hsl(var(--chat-system))] text-white'
    : 'bg-[hsl(var(--chat-assistant))] text-[hsl(var(--chat-assistant-fg))]';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div className={`max-w-[80%] ${isUser ? 'order-2' : 'order-1'}`}>
        <div className={`px-4 py-3 rounded-2xl ${bgColor} ${isUser ? 'rounded-br-md' : 'rounded-bl-md'}`}>
          {message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {message.attachments.map((att, i) => (
                <div
                  key={i}
                  className="flex items-center gap-1.5 px-2 py-1 bg-black/10 rounded-md text-xs"
                >
                  <FileText className="w-3 h-3" />
                  <span className="truncate max-w-[150px]">{att.name}</span>
                </div>
              ))}
            </div>
          )}
          <div className="text-sm whitespace-pre-wrap leading-relaxed">{message.content}</div>
        </div>
        <div className={`text-xs text-[hsl(var(--muted-foreground))] mt-1 px-1 ${isUser ? 'text-right' : 'text-left'}`}>
          {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </div>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex justify-start mb-4">
      <div className="bg-[hsl(var(--chat-assistant))] text-[hsl(var(--chat-assistant-fg))] px-4 py-3 rounded-2xl rounded-bl-md">
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-[hsl(var(--muted-foreground))] typing-dot" />
          <div className="w-2 h-2 rounded-full bg-[hsl(var(--muted-foreground))] typing-dot" />
          <div className="w-2 h-2 rounded-full bg-[hsl(var(--muted-foreground))] typing-dot" />
        </div>
      </div>
    </div>
  );
}

export default function ChatArea({
  messages,
  onSendMessage,
  processing,
  isLeftOpen,
  isRightOpen,
  onToggleLeft,
  onToggleRight
}: ChatAreaProps) {
  const [input, setInput] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { theme, toggleTheme } = useTheme();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, processing]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);

  const handleSend = () => {
    const textValue = textareaRef.current?.value || input;
    if (!textValue.trim() && files.length === 0) return;
    onSendMessage(textValue, files);
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.value = '';
      textareaRef.current.style.height = 'auto';
    }
    setFiles([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(prev => [...prev, ...Array.from(e.target.files!)]);
    }
  };

  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  return (
    <div className="flex flex-col h-full bg-[hsl(var(--background))] rounded-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[hsl(var(--border))] shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleLeft}
            className={`p-1.5 rounded-lg transition-colors ${isLeftOpen ? 'text-[hsl(var(--muted-foreground))]' : 'text-[hsl(var(--primary))] bg-[hsl(var(--accent))]'}`}
            title="Toggle sidebar"
          >
            <PanelLeft className="w-4 h-4" />
          </button>
          <div className="flex items-center gap-2">
            <img src="/cerebrum-logo.png" alt="Cerebrum" className="w-5 h-5 object-contain" />
            <h1 className="font-semibold text-sm">Cerebrum Platform</h1>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {processing.active && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-[hsl(var(--muted))] rounded-full text-xs">
              <Zap className="w-3 h-3 text-[hsl(var(--warning))] processing-pulse" />
              <span className="text-[hsl(var(--muted-foreground))]">Processing...</span>
              <span className="text-[hsl(var(--foreground))]">{processing.stage}</span>
            </div>
          )}
          <button
            onClick={onToggleRight}
            className={`p-1.5 rounded-lg transition-colors ${isRightOpen ? 'text-[hsl(var(--muted-foreground))]' : 'text-[hsl(var(--primary))] bg-[hsl(var(--accent))]'}`}
            title="Toggle results panel"
          >
            <PanelRight className="w-4 h-4" />
          </button>
          <button
            onClick={toggleTheme}
            className="p-1.5 rounded-lg hover:bg-[hsl(var(--muted))] transition-colors"
            title={theme === 'light' ? 'Switch to dark' : 'Switch to light'}
          >
            {theme === 'light' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-4">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-[hsl(var(--muted-foreground))]">
            <img src="/cerebrum-logo.png" alt="Cerebrum" className="w-12 h-12 mb-4 opacity-20 object-contain" />
            <p className="text-sm">Start a conversation or upload a file</p>
            <p className="text-xs mt-1 opacity-60">Construction documents will be analyzed automatically</p>
          </div>
        ) : (
          <>
            {messages.map(message => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {processing.active && <TypingIndicator />}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t border-[hsl(var(--border))] p-4 shrink-0">
        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {files.map((file, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 px-2 py-1 bg-[hsl(var(--muted))] rounded-lg text-xs"
              >
                <FileText className="w-3 h-3 text-[hsl(var(--amber))]" />
                <span className="truncate max-w-[200px]">{file.name}</span>
                <button
                  onClick={() => removeFile(i)}
                  className="p-0.5 hover:bg-[hsl(var(--destructive))] hover:text-white rounded transition-colors"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2 bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={handleFileSelect}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="p-2 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))] rounded-lg transition-colors shrink-0"
            title="Attach files"
          >
            <Paperclip className="w-5 h-5" />
          </button>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your construction project..."
            className="flex-1 bg-transparent text-sm resize-none outline-none min-h-[40px] max-h-[200px] py-2.5 text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))]"
            rows={1}
          />
          <button
            onClick={handleSend}
            className="p-2 bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] rounded-lg hover:opacity-90 transition-opacity shrink-0"
          >
            {processing.active ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
          </button>
        </div>
      </div>
    </div>
  );
}
