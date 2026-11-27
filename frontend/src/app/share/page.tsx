import type { Metadata } from 'next';
import { SharePage } from './share-page';

export const metadata: Metadata = { title: 'Profile sharing', robots: { index: false, follow: false }, referrer: 'no-referrer' };
export default SharePage;
