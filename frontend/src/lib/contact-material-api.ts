import { contactMaterialCodec } from './contact-material';
import { createMaterialApi } from './material-api';
import {
  readPendingContactMaterialAttempts as readPendingMaterialAttempts,
  prepareContactMaterialAttempt as prepareMaterialAttempt,
  readPendingContactMaterialDeletions as readPendingMaterialDeletions,
  beginContactMaterialDeletion as beginMaterialDeletion,
  settleContactMaterialAttempt as settleMaterialAttempt,
  settleContactMaterialDeletion as settleMaterialDeletion
} from './contact-material-storage';

const api = createMaterialApi('contact', contactMaterialCodec, { readPendingMaterialAttempts, prepareMaterialAttempt, readPendingMaterialDeletions, beginMaterialDeletion, settleMaterialAttempt, settleMaterialDeletion });
export const getContactMaterial = api.getMaterial;
export const getContactMaterials = api.getMaterials;
export const uploadContactMaterial = api.uploadMaterial;
export const deleteContactMaterial = api.deleteMaterial;
export const downloadContactMaterial = api.downloadMaterial;
