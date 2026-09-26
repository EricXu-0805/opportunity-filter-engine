import { contactMaterialCodec } from './contact-material';
import { createMaterialStorage } from './material-storage';
import { STORAGE_KEYS } from './storage-keys';

const storage = createMaterialStorage(contactMaterialCodec, { uploadPrefix: STORAGE_KEYS.CONTACT_MATERIAL_ATTEMPT_PREFIX,
  deletePrefix: STORAGE_KEYS.CONTACT_MATERIAL_DELETE_PREFIX, lockName: 'ofe-contact-material-v1' });
export const readPendingContactMaterialAttempts = storage.readPendingMaterialAttempts;
export const prepareContactMaterialAttempt = storage.prepareMaterialAttempt;
export const readPendingContactMaterialDeletions = storage.readPendingMaterialDeletions;
export const beginContactMaterialDeletion = storage.beginMaterialDeletion;
export const settleContactMaterialAttempt = storage.settleMaterialAttempt;
export const settleContactMaterialDeletion = storage.settleMaterialDeletion;
export type PrepareContactMaterialResult = Awaited<ReturnType<typeof prepareContactMaterialAttempt>>;
