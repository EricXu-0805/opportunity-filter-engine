import { createMaterialCodec, type MaterialScope, type MaterialAttempt, type MaterialDeletion, type MaterialRecord, type MaterialPage } from './material-core';
export { materialExactKeys, materialUuid,
  MATERIAL_MAX_BYTES as CONTACT_MATERIAL_MAX_BYTES,
  MATERIAL_MIME as CONTACT_MATERIAL_MIME,
  MaterialError as ContactMaterialError,
  assertMaterialOwner as assertContactMaterialOwner,
  validMaterialFilename as validContactMaterialFilename,
  snapshotMaterialInput as snapshotContactMaterialInput,
  materialInputMatches as contactMaterialInputMatches,
  withMaterialOperation as withContactMaterialOperation,
  inspectMaterialFile as inspectContactMaterialFile,
  materialRecordMatchesInput as contactMaterialRecordMatchesInput,
  snapshotMaterialCursor as snapshotContactMaterialCursor,
  materialBefore as contactMaterialBefore } from './material-core';
export type { MaterialInput as ContactMaterialInput, MaterialErrorCode as ContactMaterialErrorCode, MaterialOperation as ContactMaterialOperation, MaterialCursor as ContactMaterialCursor } from './material-core';
export type ContactMaterialScope = MaterialScope<'contactEventId'>;
export type ContactMaterialAttempt = MaterialAttempt<'contactEventId'>;
export type ContactMaterialDeletion = MaterialDeletion<'contactEventId'>;
export type ContactMaterialRecord = MaterialRecord<'contactEventId'>;
export type ContactMaterialPage = MaterialPage<'contactEventId'>;
export const contactMaterialCodec = createMaterialCodec('contactEventId', 'contact_event_id');
export const snapshotContactMaterialScope = contactMaterialCodec.snapshotScope;
export const snapshotContactMaterialAttempt = contactMaterialCodec.snapshotAttempt;
export const snapshotContactMaterialRecord = contactMaterialCodec.snapshotRecord;
export const parseContactMaterialRecord = contactMaterialCodec.parseRecord;
