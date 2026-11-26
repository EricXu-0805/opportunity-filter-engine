import { supabase } from './supabase';
import { decodeSelectedShare } from './profile-share';

export const managedSharesEnabled = process.env.NEXT_PUBLIC_MANAGED_PROFILE_SHARES === 'true';
export const fields = ['college', 'major', 'grade', 'intl', 'interests', 'skills', 'seeking', 'weight', 'courses'] as const;
export type ShareField = typeof fields[number];
export type ShareSnapshot = Partial<Record<ShareField, string | number | boolean | string[] | { n: string; l: string }[]>>;
export interface PublishedShare {
  token: string;
  version: number;
  fields: ShareField[];
  expires_at: string;
  revoked_at: string | null;
}

export const shareFieldLabels: Record<ShareField, [string, string]> = {
  college: ['College', '学院'], major: ['Major', '专业'], grade: ['Class year', '年级'],
  intl: ['International student status', '国际生身份'], interests: ['Research interests', '研究兴趣'],
  skills: ['Skill names and levels', '技能名称和等级'], seeking: ['Opportunity types', '机会类别'],
  weight: ['Search preference', '搜索偏好'], courses: ['Course names', '课程名称'],
};

export function sharePreviewValue(value: ShareSnapshot[ShareField], zh: boolean): string {
  if (typeof value === 'boolean') return value ? (zh ? '是' : 'Yes') : (zh ? '否' : 'No');
  if (Array.isArray(value)) return value.map(item => typeof item === 'string' ? item : item.n + ' (' + item.l + ')').join(', ');
  return String(value ?? '');
}

function snapshot(value: unknown): ShareSnapshot {
  decodeSelectedShare(value);
  return value as ShareSnapshot;
}

export async function previewShare(uid: string, selected: ShareField[]) {
  const { data, error } = await supabase.rpc('preview_profile_share', { p_expected_owner: uid, p_fields: selected });
  if (error || !Number.isInteger(data?.profile_revision)) throw new Error(error?.message ?? 'invalid_preview');
  return { profileRevision: data.profile_revision as number, snapshot: snapshot(data.snapshot) };
}

const sharePageSize = 50;

export async function listShares(uid: string, page: number) {
  const { data, error } = await supabase.from('profile_shares').select('token,version,fields,expires_at,revoked_at')
    .eq('owner_id', uid).order('updated_at', { ascending: false }).order('token')
    .range(page * sharePageSize, (page + 1) * sharePageSize);
  if (error) throw error;
  return { items: (data as PublishedShare[]).slice(0, sharePageSize), hasNext: data.length > sharePageSize };
}

export async function publishShare(uid: string, token: string, version: number, selected: ShareField[], expiresAt: string, profileRevision: number) {
  const { data, error } = await supabase.rpc('publish_profile_share', {
    p_expected_owner: uid, p_token: token, p_expected_version: version, p_fields: selected, p_expires_at: expiresAt, p_profile_revision: profileRevision,
  });
  if (error) throw error;
  return data.status as string;
}

export async function revokeShare(share: PublishedShare) {
  const { data, error } = await supabase.rpc('revoke_profile_share', { p_token: share.token, p_expected_version: share.version });
  if (error) throw error;
  return data.status as string;
}

type Resolved = { status: 'active'; version: number; snapshot: ShareSnapshot; expiresAt: string }
  | { status: 'changed' | 'unavailable' };
export async function resolveShare(token: string, version: number | null = null): Promise<Resolved> {
  const { data, error } = await supabase.rpc('resolve_profile_share', { p_token: token, p_expected_version: version });
  if (error) throw error;
  if (data?.status === 'changed' || data?.status === 'unavailable') return { status: data.status };
  if (data?.status !== 'active' || !Number.isInteger(data.version) || !Number.isFinite(Date.parse(data.expires_at))) throw new Error('invalid_share');
  return { status: 'active', version: data.version, snapshot: snapshot(data.snapshot), expiresAt: data.expires_at };
}
