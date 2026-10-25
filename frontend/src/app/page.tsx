import { selfReferencingMetadata } from '@/lib/site';
import HomePage from './home/HomePage';

// A server module only so the homepage can declare its own canonical; the
// page itself is the client component it re-exports.
export const generateMetadata = selfReferencingMetadata('/');

export default HomePage;
