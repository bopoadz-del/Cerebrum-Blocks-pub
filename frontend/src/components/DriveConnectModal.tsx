import React, { useState } from 'react';
import {
  X,
  HardDrive,
  Server,
  Cloud,
  Smartphone,
  Check,
  Loader2,
  AlertCircle
} from 'lucide-react';
import { api } from '@/api';
import type { DriveSource } from '@/types';

interface DriveConnectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConnect: (drive: DriveSource) => void;
  onBrowseLocal?: () => void;
  onBrowseLocalFolder?: () => void;
  existingDrives: DriveSource[];
}

interface DriveOption {
  id: string;
  name: string;
  icon: React.ReactNode;
  type: DriveSource['type'];
  disabled: boolean;
  description: string;
}

export default function DriveConnectModal({ isOpen, onClose, onConnect, onBrowseLocal, onBrowseLocalFolder, existingDrives }: DriveConnectModalProps) {
  const [connecting, setConnecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const driveOptions: DriveOption[] = [
    {
      id: 'local',
      name: 'Pick Files',
      icon: <HardDrive className="w-5 h-5" />,
      type: 'local',
      disabled: false,
      description: 'Choose individual documents from your device'
    },
    {
      id: 'local-folder',
      name: 'Pick Folder',
      icon: <HardDrive className="w-5 h-5" />,
      type: 'local',
      disabled: false,
      description: 'Browse a project folder — preserves the folder hierarchy in the sidebar'
    },
    {
      id: 'server',
      name: 'Server Files',
      icon: <Server className="w-5 h-5" />,
      type: 'server',
      disabled: false,
      description: 'Connect to project server storage'
    },
    {
      id: 'google',
      name: 'Google Drive',
      icon: <Cloud className="w-5 h-5" />,
      type: 'google',
      disabled: true,
      description: 'Coming soon'
    },
    {
      id: 'onedrive',
      name: 'OneDrive',
      icon: <Cloud className="w-5 h-5" />,
      type: 'onedrive',
      disabled: true,
      description: 'Coming soon'
    },
    {
      id: 'android',
      name: 'Android Drive',
      icon: <Smartphone className="w-5 h-5" />,
      type: 'android',
      disabled: true,
      description: 'Coming soon'
    },
    {
      id: 'dropbox',
      name: 'Dropbox',
      icon: <Cloud className="w-5 h-5" />,
      type: 'dropbox',
      disabled: true,
      description: 'Coming soon'
    }
  ];

  const handleConnect = async (option: DriveOption) => {
    if (option.disabled || connecting) return;

    setError(null);

    // Local drive → native picker (file or folder mode); no API call needed
    if (option.type === 'local') {
      if (option.id === 'local-folder') {
        onBrowseLocalFolder?.();
      } else {
        onBrowseLocal?.();
      }
      onClose();
      return;
    }

    const existing = existingDrives.find(d => d.type === option.type);
    if (existing?.connected) {
      onClose();
      return;
    }

    setConnecting(option.id);

    try {
      const result = await api.connectDrive(option.type);
      if (result.success) {
        const newDrive: DriveSource = {
          id: option.id,
          name: option.name,
          icon: 'folder',
          connected: true,
          type: option.type,
          files: result.files || []
        };
        onConnect(newDrive);
        onClose();
      } else {
        setError(`Failed to connect to ${option.name}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to connect to ${option.name}`);
    } finally {
      setConnecting(null);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="relative w-full max-w-md bg-[hsl(var(--card))] rounded-xl border border-[hsl(var(--border))] shadow-2xl mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[hsl(var(--border))]">
          <h2 className="text-lg font-semibold">Connect Drive</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-[hsl(var(--muted))] rounded-md transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          {error && (
            <div className="flex items-center gap-2 px-3 py-2 mb-4 bg-[hsl(var(--destructive))]/10 border border-[hsl(var(--destructive))]/20 rounded-lg text-sm text-[hsl(var(--destructive))]">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="space-y-2">
            {driveOptions.map(option => {
              const existing = existingDrives.find(d => d.type === option.type);
              const isConnected = existing?.connected;

              return (
                <button
                  key={option.id}
                  onClick={() => handleConnect(option)}
                  disabled={option.disabled || !!connecting}
                  className={`w-full flex items-center gap-4 p-4 rounded-lg border transition-all text-left ${
                    option.disabled
                      ? 'border-[hsl(var(--border))] opacity-40 cursor-not-allowed'
                      : isConnected
                      ? 'border-[hsl(var(--success))] bg-[hsl(var(--success))]/5'
                      : 'border-[hsl(var(--border))] hover:border-[hsl(var(--primary))] hover:bg-[hsl(var(--muted))] cursor-pointer'
                  }`}
                >
                  <div className={`p-2 rounded-lg ${isConnected ? 'bg-[hsl(var(--success))]/10 text-[hsl(var(--success))]' : 'bg-[hsl(var(--muted))] text-[hsl(var(--foreground))]'}`}>
                    {option.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">{option.name}</span>
                      {isConnected && (
                        <span className="flex items-center gap-1 text-xs text-[hsl(var(--success))]">
                          <Check className="w-3 h-3" />
                          Connected
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-[hsl(var(--muted-foreground))]">
                      {option.disabled
                        ? option.description
                        : option.type === 'local'
                        ? 'Browse and select files from your device'
                        : isConnected
                        ? 'Click to reconnect'
                        : 'Click to connect'}
                    </span>
                  </div>
                  {connecting === option.id ? (
                    <Loader2 className="w-5 h-5 animate-spin text-[hsl(var(--primary))]" />
                  ) : (
                    <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-[hsl(var(--success))]' : option.disabled ? 'bg-[hsl(var(--muted-foreground))]' : 'bg-[hsl(var(--muted))]'}`} />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
