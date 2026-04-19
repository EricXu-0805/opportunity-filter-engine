import Link from 'next/link';
import { Search } from 'lucide-react';

export default function OpportunityNotFound() {
  return (
    <div className="max-w-xl mx-auto px-4 sm:px-6 lg:px-8 py-16 text-center">
      <div className="w-12 h-12 mx-auto mb-4 rounded-2xl bg-gray-100 flex items-center justify-center">
        <Search className="w-6 h-6 text-gray-400" aria-hidden="true" />
      </div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2 tracking-tight">
        Opportunity not found
      </h1>
      <p className="text-[14px] text-gray-500 mb-6 max-w-md mx-auto leading-relaxed">
        This opportunity may have expired, been removed, or the link is wrong.
        Try finding a match that fits your profile instead.
      </p>
      <Link
        href="/results"
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 text-white text-[14px] font-semibold hover:bg-blue-700 transition-colors"
      >
        Browse matches
      </Link>
    </div>
  );
}
