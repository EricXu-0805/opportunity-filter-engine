'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { Upload, FileText, CheckCircle, AlertCircle, Loader2, X } from 'lucide-react';
import Link from 'next/link';
import { parseResumePDF } from '@/lib/pdf-parser';
import type { ResumeParseResponse } from '@/lib/types';
import { useT } from '@/i18n/client';

interface ResumeUploadProps {
  onParsed: (data: ResumeParseResponse) => void;
  /** Called when the user removes the résumé on file. The parent MUST act
   *  on it — clearing this component's own badge while the profile keeps
   *  the extracted text means matching, Tailor and cold email all go on
   *  using a résumé the user believes they deleted. */
  onRemove: () => void;
  alreadyUploaded?: boolean;
}

type UploadState = 'idle' | 'uploading' | 'success' | 'error';

export default function ResumeUpload({ onParsed, onRemove, alreadyUploaded }: ResumeUploadProps) {
  const { t } = useT();
  const [state, setState] = useState<UploadState>('idle');
  const [fileName, setFileName] = useState<string | null>(null);

  // Set by a removal, cleared by the next upload: without it the effect
  // below immediately re-renders "résumé on file" from the parent prop that
  // has not been re-rendered yet, and the remove button looks broken.
  const removedRef = useRef(false);

  useEffect(() => {
    if (alreadyUploaded && state === 'idle' && !removedRef.current) {
      // alreadyUploaded arrives async from the parent's loadProfile(), so
      // the value isn't available at mount for a useState initializer.
      // Both setState calls flush together so the UI flips from "drop your
      // resume here" to "✓ resume on file" in one paint.
      setState('success');
      setFileName(t('resume.savedFallback'));
    }
  }, [alreadyUploaded, state, t]);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [progress, setProgress] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Latest file wins. The dropzone refuses CLICKS while uploading, but a
  // drop still lands, so two parses can overlap — and the slower, earlier
  // one would otherwise finish last and hand the parent its text, its
  // coursework and its skills as if it were the file the user is looking
  // at. Only the newest parse may touch state or call onParsed.
  const parseRequestRef = useRef(0);
  const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const processFile = useCallback(
    async (file: File) => {
      // Bumped for EVERY attempt, before the file is even validated: a
      // rejected .txt is still the user telling us the previous PDF is not
      // the one they want. Leaving the old parse live would let it resolve
      // later and paint success over the error they are looking at.
      parseRequestRef.current += 1;
      const request = parseRequestRef.current;
      removedRef.current = false;
      if (progressIntervalRef.current) {
        clearInterval(progressIntervalRef.current);
        progressIntervalRef.current = null;
      }
      setProgress(0);

      if (file.type !== 'application/pdf') {
        setError(t('resume.errOnlyPdf'));
        setState('error');
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        setError(t('resume.errTooBig'));
        setState('error');
        return;
      }

      setFileName(file.name);
      setState('uploading');
      setError(null);

      const progressInterval = setInterval(() => {
        // A superseded attempt's timer must not keep advancing the bar the
        // current one owns (or tick forever if its parse never settles).
        if (request !== parseRequestRef.current) {
          clearInterval(progressInterval);
          return;
        }
        setProgress((p) => Math.min(p + 15, 85));
      }, 300);
      progressIntervalRef.current = progressInterval;

      try {
        const data = await parseResumePDF(file);
        clearInterval(progressInterval);
        if (request !== parseRequestRef.current) return;
        setProgress(100);
        if (data.success) {
          setState('success');
          onParsed(data);
        } else {
          setError(data.message || t('resume.errParse'));
          setState('error');
        }
      } catch (err) {
        clearInterval(progressInterval);
        if (request !== parseRequestRef.current) return;
        setProgress(0);
        setError(err instanceof Error ? err.message : t('resume.errFailed'));
        setState('error');
      }
    },
    [onParsed, t],
  );

  // A parse that outlives this component must not keep a progress timer
  // ticking, and its result has nothing left to write to.
  useEffect(() => () => {
    parseRequestRef.current += 1;
    if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
  }, []);

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

  function reset(removeFromProfile = false) {
    // Whatever is parsing no longer has a file on screen to describe.
    parseRequestRef.current += 1;
    if (removeFromProfile) {
      removedRef.current = true;
      onRemove();
    }
    if (progressIntervalRef.current) {
      clearInterval(progressIntervalRef.current);
      progressIntervalRef.current = null;
    }
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
              ? 'border-indigo-400 bg-indigo-50/80 scale-[1.01]'
              : state === 'success'
                ? 'border-emerald-300 bg-emerald-50/50'
                : state === 'error'
                  ? 'border-red-300 bg-red-50/50'
                  : 'border-gray-300 bg-gray-50/50 hover:border-indigo-300 hover:bg-indigo-50/30'
          }`}
      >
        {state === 'idle' && (
          <>
            <div className="w-12 h-12 rounded-xl bg-indigo-50 flex items-center justify-center">
              <Upload className="w-6 h-6 text-indigo-500" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-gray-700">
                {t('resume.dropHere')}{' '}
                <span className="text-indigo-600">{t('resume.browse')}</span>
              </p>
              <p className="mt-1 text-xs text-gray-400">{t('resume.pdfOnly')}</p>
            </div>
          </>
        )}

        {state === 'uploading' && (
          <>
            <Loader2 className="w-8 h-8 text-indigo-500 animate-spin" />
            <div className="w-full max-w-[200px]">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs text-gray-500 truncate max-w-[140px]">
                  {fileName}
                </span>
                <span className="text-xs font-medium text-indigo-600">{progress}%</span>
              </div>
              <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-indigo-600 to-indigo-400 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                reset();
              }}
              aria-label={t('resume.cancelAria')}
              className="text-xs text-gray-500 hover:text-gray-700 underline underline-offset-2"
            >
              {t('resume.cancel')}
            </button>
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
              {t('resume.success')}
            </p>
            <p className="text-[11px] text-gray-500 text-center max-w-[260px]">
              {t('resume.removeNote')}{' '}
              <Link
                href="/privacy"
                onClick={(e) => e.stopPropagation()}
                className="underline underline-offset-2 hover:text-gray-700"
              >
                {t('resume.privacyLink')}
              </Link>
            </p>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                reset(true);
              }}
              className="absolute top-2 right-2 p-1 rounded-lg hover:bg-emerald-100 transition-colors"
              aria-label={t('resume.removeAria')}
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
              {t('resume.tryAgain')}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
