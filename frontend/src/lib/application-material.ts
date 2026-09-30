import { createMaterialCodec, type MaterialScope, type MaterialAttempt, type MaterialDeletion, type MaterialRecord, type MaterialPage } from './material-core';
export { materialExactKeys, materialUuid,
  MATERIAL_MAX_BYTES as APPLICATION_MATERIAL_MAX_BYTES,
  MATERIAL_MIME as APPLICATION_MATERIAL_MIME,
  MaterialError as ApplicationMaterialError,
  assertMaterialOwner as assertApplicationMaterialOwner,
  validMaterialFilename as validApplicationMaterialFilename,
  snapshotMaterialInput as snapshotApplicationMaterialInput,
  materialInputMatches as applicationMaterialInputMatches,
  withMaterialOperation as withApplicationMaterialOperation,
  inspectMaterialFile as inspectApplicationMaterialFile,
  materialRecordMatchesInput as applicationMaterialRecordMatchesInput,
  snapshotMaterialCursor as snapshotApplicationMaterialCursor,
  materialBefore as applicationMaterialBefore } from './material-core';
export type { MaterialInput as ApplicationMaterialInput, MaterialErrorCode as ApplicationMaterialErrorCode, MaterialOperation as ApplicationMaterialOperation, MaterialCursor as ApplicationMaterialCursor } from './material-core';
export type ApplicationMaterialScope = MaterialScope<'applicationEventId'>;
export type ApplicationMaterialAttempt = MaterialAttempt<'applicationEventId'>;
export type ApplicationMaterialDeletion = MaterialDeletion<'applicationEventId'>;
export type ApplicationMaterialRecord = MaterialRecord<'applicationEventId'>;
export type ApplicationMaterialPage = MaterialPage<'applicationEventId'>;
export const applicationMaterialCodec = createMaterialCodec('applicationEventId', 'application_event_id');
export const snapshotApplicationMaterialScope = applicationMaterialCodec.snapshotScope;
export const snapshotApplicationMaterialAttempt = applicationMaterialCodec.snapshotAttempt;
export const snapshotApplicationMaterialRecord = applicationMaterialCodec.snapshotRecord;
export const parseApplicationMaterialRecord = applicationMaterialCodec.parseRecord;
