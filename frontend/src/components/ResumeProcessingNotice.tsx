import { useT } from '@/i18n/client';
import type { ResumeProcessingCoverage } from '@/lib/types';
import { RESUME_AI_CHUNK_CHARACTERS, resumeTextCharacters } from '@/lib/resume-input';

/** Kept beside the extraction action and its result, not hidden in a toast. */
export default function ResumeProcessingNotice({
  text, processing, warnings = [],
}: {
  text: string;
  processing?: ResumeProcessingCoverage;
  warnings?: string[];
}) {
  const { t } = useT();
  return (
    <div className="text-xs text-gray-500 space-y-1 max-w-prose" data-testid="resume-processing-notice">
      <p>{t('resume.processingScope')}</p>
      {resumeTextCharacters(text) > RESUME_AI_CHUNK_CHARACTERS && !processing && (
        <p>{t('resume.processingLong')}</p>
      )}
      {processing && (
        <p role="status" className={processing.heuristic_chunks ? 'text-amber-700' : undefined}>
          {t('resume.processingCoverage', {
            ai: processing.ai_chunks,
            total: processing.chunks.length,
            local: processing.heuristic_chunks,
          })}
        </p>
      )}
      {warnings.includes('bullet_selection_limited') && (
        <p className="text-amber-700">{t('resume.processingSelectionLimited')}</p>
      )}
    </div>
  );
}
