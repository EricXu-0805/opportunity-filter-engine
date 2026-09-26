'use client';

import RecordedMaterials from './RecordedMaterials';
import type { ApplicationMaterialScope } from '@/lib/application-material';
import {
  getApplicationMaterial as getMaterial,
  getApplicationMaterials as getMaterials,
  uploadApplicationMaterial as uploadMaterial,
  downloadApplicationMaterial as downloadMaterial,
  deleteApplicationMaterial as deleteMaterial
} from '@/lib/application-material-api';
import {
  readPendingApplicationMaterialAttempts as readPendingMaterialAttempts,
  readPendingApplicationMaterialDeletions as readPendingMaterialDeletions,
  prepareApplicationMaterialAttempt as prepareMaterialAttempt,
  settleApplicationMaterialAttempt as settleMaterialAttempt,
  settleApplicationMaterialDeletion as settleMaterialDeletion
} from '@/lib/application-material-storage';

const services = { getMaterial, getMaterials, uploadMaterial, downloadMaterial, deleteMaterial, readPendingMaterialAttempts, readPendingMaterialDeletions, prepareMaterialAttempt, settleMaterialAttempt, settleMaterialDeletion };
export default function ApplicationMaterials(scope: ApplicationMaterialScope) {
  return <RecordedMaterials kind="application" scope={scope} services={services} />;
}
