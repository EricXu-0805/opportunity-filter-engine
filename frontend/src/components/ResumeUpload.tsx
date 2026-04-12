'use client';

import { useState, useRef, useCallback } from 'react';
import { Upload, FileText, CheckCircle, AlertCircle, Loader2, X } from 'lucide-react';
import { parseResumePDF } from '@/lib/pdf-parser';
import type { ResumeParseResponse } from '@/lib/types';

interface ResumeUploadProps {
  onParsed: (data: ResumeParseResponse) => void;
}

type UploadState = 'idle' | 'uploading' | 'success' | 'error';

export default function ResumeUpload({ onParsed }: ResumeUploadProps) {
  const [state, setState] = useState<UploadState>('idle');
  const [fileName, setFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [progress, setProgress] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const processFile = useCallback(
    async (file: File) => {
      // Validate
      if (file.type !== 'application/pdf') {
        setError('Only PDF files are accepted');
        setState('error');
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        setError('File must be under 5 MB');
        setState('error');
        return;
      }

      setFileName(file.name);
      setState('uploading');
      setError(null);

      // Simulate progress while uploading
      const progressInterval = setInterval(() => {
        setProgress((p) => Math.min(p + 15, 85));
      }, 300);

      try {
        const data = await parseResumePDF(file);
        clearInterval(progressInterval);
        setProgress(100);
        if (data.success) {
          setState('success');
          onParsed(data);
        } else {
          setError(data.message || 'Could not parse PDF');
          setState('error');
        }
      } catch (err) {
        clearInterval(progressInterval);
        setProgress(0);
        setError(err instanceof Error ? err.message : 'Failed to parse resume');
        setState('error');
      }
    },
    [onParsed],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) processFile(file);
    },
    [processFile],
  );

  const handleSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) processFile(file);
    },
    [processFile],
  );

  function reset() {
    setState('idle');
    setFileName(null);
    setError(null);
    setProgress(0);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  return (
    <div>
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        onChange={handleSelect}
        className="sr-only"
        id="resume-upload"
      />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => state !== 'uploading' && fileInputRef.current?.click()}
        className={`relative flex flex-col items-center justify-center gap-3 p-6 border-2 border-dashed rounded-xl cursor-pointer transition-all duration-200
          ${
            dragOver
              ? 'border-blue-400 bg-blue-50/80 scale-[1.01]'
              : state === 'success'
                ? 'border-emerald-300 bg-emerald-50/50'
                : state === 'error'
                  ? 'border-red-300 bg-red-50/50'
                  : 'border-gray-300 bg-gray-50/50 hover:border-blue-300 hover:bg-blue-50/30'
          }`}
      >
        {state === 'idle' && (
          <>
            <div className="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center">
              <Upload className="w-6 h-6 text-blue-500" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-gray-700">
                Drop your resume here, or{' '}
                <span className="text-blue-600">browse</span>
              </p>
              <p className="mt-1 text-xs text-gray-400">PDF only · Max 5 MB</p>
            </div>
          </>
        )}

        {state === 'uploading' && (
          <>
            <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
            <div className="w-full max-w-[200px]">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-gray-500 truncate max-w-[140px]">
                  {fileName}
                </span>
                <span className="text-xs font-medium text-blue-600">{progress}%</span>
              </div>
              <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-blue-600 to-blue-400 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          </>
        )}

        {state === 'success' && (
          <>
            <div className="flex items-center gap-2">
              <FileText className="w-5 h-5 text-emerald-600" />
              <span className="text-sm font-medium text-emerald-700 truncate max-w-[180px]">
                {fileName}
              </span>
              <CheckCircle className="w-4 h-4 text-emerald-500" />
            </div>
            <p className="text-xs text-emerald-600">
              Parsed successfully · Skills auto-populated
            </p>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                reset();
              }}
              className="absolute top-2 right-2 p-1 rounded-lg hover:bg-emerald-100 transition-colors"
              aria-label="Remove file"
            >
              <X className="w-4 h-4 text-emerald-500" />
            </button>
          </>
        )}

        {state === 'error' && (
          <>
            <AlertCircle className="w-8 h-8 text-red-500" />
            <p className="text-sm text-red-600 font-medium">{error}</p>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                reset();
              }}
              className="text-xs text-red-500 underline hover:text-red-700"
            >
              Try again
            </button>
          </>
        )}
      </div>
    </div>
  );
}
