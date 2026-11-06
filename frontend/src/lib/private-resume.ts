import { isPrivateResumeContext, type PrivateResumeContext } from './private-resume-context';
import { privateImportResumeContextRequest, PrivateTargetError } from './private-import-target-api';
import { targetResumeContextSignature } from './target-resume';
import { type OwnerToken } from './identity-owner';

/** Read-only preparation. This receipt neither starts a model nor authorizes a send. */
export async function getPrivateResumeContext(id: string, options: { owner: OwnerToken; signal?: AbortSignal; expectedVersion?: string }): Promise<PrivateResumeContext> {
  const owner = { ...options.owner }, expected = options.expectedVersion;
  let context: PrivateResumeContext | undefined;
  await privateImportResumeContextRequest(id, { ...options, owner, verify: async (data, wait) => {
    if (Object.keys(data).length !== 5 || !['version','target_scope','verification','context','target_signature'].every(key => Object.hasOwn(data, key))
      || data.version !== 1 || data.target_scope !== 'private_import' || data.verification !== 'unverified'
      || !isPrivateResumeContext(data.context) || data.context.opportunity_id !== id
      || data.context.private_source.owner_id !== owner.uid || expected !== undefined && data.context.private_source.source_version !== expected) {
      throw new PrivateTargetError('invalid_receipt');
    }
    try {
      if (await wait(targetResumeContextSignature(data.context)) !== data.target_signature) throw new Error('Invalid signature');
    } catch (error) {
      throw new PrivateTargetError(error instanceof Error && 'code' in error && error.code === 'document_too_large' ? 'too_large' : 'invalid_receipt');
    }
    context = data.context;
  } });
  return context!;
}
