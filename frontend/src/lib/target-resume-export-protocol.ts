import type { TargetResumeSection } from './target-resume';

export const TARGET_RESUME_EXPORT_TEMPLATE = 'standard-v1' as const;
export const TARGET_RESUME_EXPORT_MAX_BODY_BYTES = 2 * 1024 * 1024 + 64 * 1024;
export const TARGET_RESUME_EXPORT_MAX_FILE_BYTES = 64 * 1024 * 1024;
export type TargetResumeExportFormat = 'pdf' | 'docx';
export type TargetResumeExportLocale = 'en' | 'zh';
export type TargetResumeExportPageSize = 'letter' | 'a4';
/** Only the current selected wording belongs in the render request. IDs,
 * originals, raw source, evidence quotes, and unselected content stay local. */
export interface TargetResumeExportProjection {
  version: 1;
  template: typeof TARGET_RESUME_EXPORT_TEMPLATE;
  locale: TargetResumeExportLocale;
  page_size: TargetResumeExportPageSize;
  sections: Array<{
    kind: TargetResumeSection['kind'];
    heading: string;
    blocks: Array<{ lines: Array<{ role: string; label: string; text: string }> }>;
  }>;
}
export interface TargetResumeExportRequest {
  version: 1;
  request_id: string;
  format: TargetResumeExportFormat;
  /** Whole draft hash is echoed for the browser's version check, not proof
   * that the renderer has received or verified the student's source facts. */
  document_signature: string;
  export_signature: string;
  projection: TargetResumeExportProjection;
}
export interface PreparedTargetResumeExport {
  projection: TargetResumeExportProjection;
  canonical_draft: string;
  document_signature: string;
  export_signature: string;
}
export const TARGET_RESUME_EXPORT_MIME: Record<TargetResumeExportFormat, string> = {
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
};
export const TARGET_RESUME_EXPORT_HEADERS = {
  request: 'x-ofe-export-request',
  document: 'x-ofe-document-signature',
  projection: 'x-ofe-export-signature',
  template: 'x-ofe-export-template',
} as const;
