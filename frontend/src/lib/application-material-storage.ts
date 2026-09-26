import { applicationMaterialCodec } from './application-material';
import { createMaterialStorage } from './material-storage';
import { STORAGE_KEYS } from './storage-keys';

const storage = createMaterialStorage(applicationMaterialCodec, { uploadPrefix: STORAGE_KEYS.APPLICATION_MATERIAL_ATTEMPT_PREFIX,
  deletePrefix: STORAGE_KEYS.APPLICATION_MATERIAL_DELETE_PREFIX, lockName: 'ofe-application-material-v1' });
export const readPendingApplicationMaterialAttempts = storage.readPendingMaterialAttempts;
export const prepareApplicationMaterialAttempt = storage.prepareMaterialAttempt;
export const readPendingApplicationMaterialDeletions = storage.readPendingMaterialDeletions;
export const beginApplicationMaterialDeletion = storage.beginMaterialDeletion;
export const settleApplicationMaterialAttempt = storage.settleMaterialAttempt;
export const settleApplicationMaterialDeletion = storage.settleMaterialDeletion;
export type PrepareApplicationMaterialResult = Awaited<ReturnType<typeof prepareApplicationMaterialAttempt>>;
