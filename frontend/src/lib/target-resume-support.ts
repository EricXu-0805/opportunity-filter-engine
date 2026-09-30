import type { TargetResumeLine, TargetResumeV1 } from './target-resume';
export interface TargetResumeSupportGroup { unit_id: string; support_unit_ids: string[]; confirmed: true }
export interface TargetResumeSupportEvidence { unit_id: string; start: number; end: number; quote: string }
export interface TargetResumeSupportActivity { id: string; label: string; lines: TargetResumeLine[] }
/** Only uniquely linked current experience lines in one activity can share sources. */
export function targetResumeSupportActivities(draft: TargetResumeV1): TargetResumeSupportActivity[] {
  const counts = new Map<string, number>();
  for (const record of [...draft.base_snapshot.resume_master.activities, ...draft.base_snapshot.resume_master.education, ...draft.base_snapshot.resume_master.publications]) {
    for (const ref of record.details) counts.set(ref.id, (counts.get(ref.id) ?? 0) + 1);
  }
  return draft.document.sections.filter(section => section.kind === 'activities').flatMap(section => section.blocks.map(block => ({
    id: block.id,
    label: block.lines.find(line => line.role === 'title')?.original || block.lines.find(line => line.role === 'organization')?.original || '',
    lines: block.lines.filter(line => line.evidence.kind === 'experience' && counts.get(line.evidence.id) === 1),
  }))).filter(block => block.lines.length > 1);
}
export function parseTargetResumeSupportGroups(draft: TargetResumeV1, value: unknown): TargetResumeSupportGroup[] | null {
  try {
    if (!Array.isArray(value) || value.length > 24) return null;
    const activities = targetResumeSupportActivities(draft), seen = new Set<string>();
    const result: TargetResumeSupportGroup[] = [];
    for (const item of value) {
      if (!item || typeof item !== 'object' || Array.isArray(item) || Object.keys(item).length !== 3
        || !['unit_id','support_unit_ids','confirmed'].every(key => Object.hasOwn(item,key)) || item.confirmed !== true
        || typeof item.unit_id !== 'string' || seen.has(item.unit_id) || !Array.isArray(item.support_unit_ids)
        || !item.support_unit_ids.length || item.support_unit_ids.length > 24 || new Set(item.support_unit_ids).size !== item.support_unit_ids.length) return null;
      const activity = activities.find(block => block.lines.some(line => line.id === item.unit_id));
      if (!activity || item.support_unit_ids.some((id: unknown) => typeof id !== 'string' || id === item.unit_id || !activity.lines.some(line => line.id === id))) return null;
      seen.add(item.unit_id); result.push({unit_id:item.unit_id,support_unit_ids:[...item.support_unit_ids],confirmed:true});
    }
    return result;
  } catch { return null; }
}
export function supportGroupsForUnits(groups: readonly TargetResumeSupportGroup[] | undefined, ids: readonly string[]): TargetResumeSupportGroup[] {
  const selected = new Set(ids); return (groups ?? []).filter(group => selected.has(group.unit_id));
}
export function targetResumeSupportEvidence(draft: TargetResumeV1, group: TargetResumeSupportGroup): TargetResumeSupportEvidence[] {
  const lines = new Map(draft.document.sections.flatMap(section=>section.blocks.flatMap(block=>block.lines.map(line=>[line.id,line] as const))));
  return [group.unit_id,...group.support_unit_ids].map(id=>{const line=lines.get(id)!;return {unit_id:id,start:0,end:Array.from(line.original).length,quote:line.original};});
}
export function supportSourceIds(ids: readonly string[], groups: readonly TargetResumeSupportGroup[] | undefined): string[] {
  return [...new Set([...ids,...supportGroupsForUnits(groups,ids).flatMap(group=>group.support_unit_ids)])];
}
