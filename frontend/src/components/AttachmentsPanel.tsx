'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Paperclip, Trash2, Upload, ExternalLink, Loader2, AlertCircle } from 'lucide-react';
import {
  ATTACHMENTS_ALLOWED_MIME,
  ATTACHMENTS_MAX_BYTES,
  deleteAttachment,
  getAttachmentSignedUrl,
  listAttachments,
  uploadAttachment,
  type Attachment,
} from '@/lib/supabase';
import { useT } from '@/i18n/client';

type Replier = (path: string, vars?: Record<string, string | number>) => string;

interface Props {
  opportunityId: string;
}

function formatBytes(n: number, t: Replier): string {
  if (n < 1024) return t('detail.attachments.sizeBytes', { n });
  if (n < 1024 * 1024) return t('detail.attachments.sizeKB', { n: Math.round(n / 1024) });
  return t('detail.attachments.sizeMB', { n: (n / 1024 / 1024).toFixed(1) });
}

export default function AttachmentsPanel({ opportunityId }: Props) {
  const { t } = useT();
  const [files, setFiles] = useState<Attachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openingName, setOpeningName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    const next = await listAttachments(opportunityId);
    setFiles(next);
    setLoading(false);
  }, [opportunityId]);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- refresh() sets loading + files; called on mount and also re-called after upload/delete, so extracting the inline fetch would duplicate the setState pair into two places
  useEffect(() => { refresh(); }, [refresh]);

  const handleSelect = useCallback(async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setUploading(file.name);
    const result = await uploadAttachment(opportunityId, file);
    setUploading(null);
    if (!result.ok) {
      if (result.reason === 'too_large') setError(t('detail.attachments.errTooLarge'));
      else if (result.reason === 'wrong_type') setError(t('detail.attachments.errWrongType'));
      else if (result.reason === 'duplicate') setError(t('detail.attachments.errDuplicate', { name: file.name }));
      else if (result.reason === 'unauthenticated') setError(t('detail.attachments.errUnauth'));
      else setError(t('detail.attachments.errUpload', { msg: result.message ?? '' }));
      return;
    }
    await refresh();
  }, [opportunityId, t, refresh]);

  const handleDelete = useCallback(async (name: string) => {
    setError(null);
    const ok = await deleteAttachment(opportunityId, name);
    if (!ok) {
      setError(t('detail.attachments.errDelete', { name }));
      return;
    }
    setFiles((prev) => prev.filter((f) => f.name !== name));
  }, [opportunityId, t]);

  const handleOpen = useCallback(async (name: string) => {
    setError(null);
    setOpeningName(name);
    const url = await getAttachmentSignedUrl(opportunityId, name);
    setOpeningName(null);
    if (!url) {
      setError(t('detail.attachments.errOpen', { name }));
      return;
    }
    window.open(url, '_blank', 'noopener,noreferrer');
  }, [opportunityId, t]);

  const acceptString = Array.from(ATTACHMENTS_ALLOWED_MIME).join(',');
  const maxMb = Math.round(ATTACHMENTS_MAX_BYTES / 1024 / 1024);

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[12px] text-gray-600">
        <Paperclip className="w-3.5 h-3.5 text-gray-400" aria-hidden="true" />
        <span className="font-medium">{t('detail.attachments.label')}</span>
        <span className="text-[10px] text-gray-400">
          {t('detail.attachments.hint', { mb: maxMb })}
        </span>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={!!uploading}
          className="ml-auto inline-flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-wait transition-colors"
        >
          {uploading ? (
            <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
          ) : (
            <Upload className="w-3 h-3" aria-hidden="true" />
          )}
          {uploading
            ? t('detail.attachments.uploading', { name: uploading })
            : t('detail.attachments.addButton')}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept={acceptString}
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = '';
            handleSelect(f);
          }}
          className="hidden"
        />
      </div>

      {error && (
        <div className="flex items-start gap-1.5 px-2 py-1 text-[11px] text-red-700 bg-red-50 border border-red-100 rounded">
          <AlertCircle className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <p className="text-[11px] text-gray-400 italic">{t('detail.attachments.loading')}</p>
      ) : files.length === 0 ? (
        <p className="text-[11px] text-gray-400 italic">{t('detail.attachments.empty')}</p>
      ) : (
        <ul className="space-y-1">
          {files.map((f) => (
            <li
              key={f.name}
              className="flex items-center gap-2 px-2 py-1.5 text-[12px] bg-white border border-gray-100 rounded-md hover:border-gray-200 group"
            >
              <button
                type="button"
                onClick={() => handleOpen(f.name)}
                disabled={openingName === f.name}
                className="flex-1 flex items-center gap-2 min-w-0 text-left disabled:opacity-50"
                aria-label={t('detail.attachments.openAria', { name: f.name })}
              >
                {openingName === f.name ? (
                  <Loader2 className="w-3 h-3 text-gray-400 animate-spin shrink-0" aria-hidden="true" />
                ) : (
                  <ExternalLink className="w-3 h-3 text-gray-400 shrink-0" aria-hidden="true" />
                )}
                <span className="truncate text-gray-700 group-hover:text-indigo-700">{f.name}</span>
                <span className="ml-auto text-[10px] text-gray-400 shrink-0 tabular-nums">
                  {formatBytes(f.sizeBytes, t)}
                </span>
              </button>
              <button
                type="button"
                onClick={() => handleDelete(f.name)}
                className="text-gray-300 hover:text-red-500 transition-colors p-1 -mr-1 rounded"
                aria-label={t('detail.attachments.deleteAria', { name: f.name })}
              >
                <Trash2 className="w-3 h-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
