import type { Metadata } from 'next';
import { decodeRouteId } from '@/lib/api-server';
import PrivateImportDetail from './PrivateImportDetail';
export const metadata: Metadata = { title: 'Private import — JoinALab', robots: { index: false, follow: false } };
export default async function PrivateImportPage({ params }: { params: Promise<{ id: string }> }) {
  const id = decodeRouteId((await params).id);
  return <PrivateImportDetail id={id} />;
}
