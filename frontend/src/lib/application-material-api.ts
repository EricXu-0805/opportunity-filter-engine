import { applicationMaterialCodec } from './application-material';
import { createMaterialApi } from './material-api';
import {
  readPendingApplicationMaterialAttempts as readPendingMaterialAttempts,
  prepareApplicationMaterialAttempt as prepareMaterialAttempt,
  readPendingApplicationMaterialDeletions as readPendingMaterialDeletions,
  beginApplicationMaterialDeletion as beginMaterialDeletion,
  settleApplicationMaterialAttempt as settleMaterialAttempt,
  settleApplicationMaterialDeletion as settleMaterialDeletion
} from './application-material-storage';

const api = createMaterialApi('application', applicationMaterialCodec, { readPendingMaterialAttempts, prepareMaterialAttempt, readPendingMaterialDeletions, beginMaterialDeletion, settleMaterialAttempt, settleMaterialDeletion });
export const getApplicationMaterial = api.getMaterial;
export const getApplicationMaterials = api.getMaterials;
export const uploadApplicationMaterial = api.uploadMaterial;
export const deleteApplicationMaterial = api.deleteMaterial;
export const downloadApplicationMaterial = api.downloadMaterial;
