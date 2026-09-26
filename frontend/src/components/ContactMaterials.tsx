'use client';

import RecordedMaterials from './RecordedMaterials';
import type { ContactMaterialScope } from '@/lib/contact-material';
import {
  getContactMaterial as getMaterial,
  getContactMaterials as getMaterials,
  uploadContactMaterial as uploadMaterial,
  downloadContactMaterial as downloadMaterial,
  deleteContactMaterial as deleteMaterial
} from '@/lib/contact-material-api';
import {
  readPendingContactMaterialAttempts as readPendingMaterialAttempts,
  readPendingContactMaterialDeletions as readPendingMaterialDeletions,
  prepareContactMaterialAttempt as prepareMaterialAttempt,
  settleContactMaterialAttempt as settleMaterialAttempt,
  settleContactMaterialDeletion as settleMaterialDeletion
} from '@/lib/contact-material-storage';

const services = { getMaterial, getMaterials, uploadMaterial, downloadMaterial, deleteMaterial, readPendingMaterialAttempts, readPendingMaterialDeletions, prepareMaterialAttempt, settleMaterialAttempt, settleMaterialDeletion };
export default function ContactMaterials(scope: ContactMaterialScope) {
  return <RecordedMaterials kind="contact" scope={scope} services={services} />;
}
