import { describe, expect, it } from 'vitest';
import { parseResumeSupplementDraft, RESUME_SUPPLEMENT_DRAFT_MAX_LENGTH } from './resume-supplement-draft';
const sample = () => ({version:1,opportunityId:'target',targetKey:'wt1:original',entryId:'entry-one',activityId:'activity-one',answers:{task:'  Exact task.\n王😀',method:'Private unselected answer',personalRole:'I did not lead.',outcome:'',outcomeBasis:''},selected:['task','personalRole']});
describe('unconfirmed supplement recovery snapshot',()=>{
 it('preserves all selected and unselected text verbatim in an owned copy',()=>{const original=sample();const parsed=parseResumeSupplementDraft(original)!;expect(parsed).toEqual(original);parsed.answers.task='Changed';expect(original.answers.task).toContain('Exact');});
 it.each(['confirmed','accepted','owner','profile','permission'])('refuses an added %s authority field',key=>expect(parseResumeSupplementDraft({...sample(),[key]:true})).toBeNull());
 it.each(['\0','\ud800'])('rejects invalid Unicode without repairing it',bad=>{const s=sample();s.answers.method=bad;expect(parseResumeSupplementDraft(s)).toBeNull();});
 it('rejects duplicate and sparse selections',()=>{expect(parseResumeSupplementDraft({...sample(),selected:['task','task']})).toBeNull();expect(parseResumeSupplementDraft({...sample(),selected:new Array(1)})).toBeNull();});
 it('rejects overflow instead of slicing private answers',()=>{const s=sample();s.answers.task='x'.repeat(RESUME_SUPPLEMENT_DRAFT_MAX_LENGTH);expect(parseResumeSupplementDraft(s)).toBeNull();expect(s.answers.task.length).toBe(RESUME_SUPPLEMENT_DRAFT_MAX_LENGTH);});
 it('never reads an accessor selection',()=>{let read=false;const s=sample();Object.defineProperty(s.selected,'0',{get(){read=true;return 'task'},enumerable:true});expect(parseResumeSupplementDraft(s)).toBeNull();expect(read).toBe(false);});
 it('never reads an accessor answer',()=>{let read=false;const s=sample();Object.defineProperty(s.answers,'task',{get(){read=true;return 'hidden'},enumerable:true});expect(parseResumeSupplementDraft(s)).toBeNull();expect(read).toBe(false);});
});
