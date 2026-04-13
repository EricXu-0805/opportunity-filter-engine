'use client';

import { useState, useEffect, useCallback } from 'react';
import { Star, ArrowLeft, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { getFavorites, toggleFavorite } from '@/lib/supabase';
import { getOpportunities } from '@/lib/api';

interface Opportunity {
  id: string;
  title: string;
  organization?: string;
  opportunity_type?: string;
  url?: string;
}

export default function FavoritesPage() {
  const router = useRouter();
  const [favIds, setFavIds] = useState<Set<string>>(new Set());
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [favSet, oppsData] = await Promise.all([getFavorites(), getOpportunities()]);
        setFavIds(favSet);
        const allOpps = oppsData.opportunities || [];
        setOpportunities(allOpps.filter((o: Opportunity) => favSet.has(o.id)));
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const handleRemove = useCallback(async (oppId: string) => {
    await toggleFavorite(oppId, true);
    setFavIds(prev => { const n = new Set(prev); n.delete(oppId); return n; });
    setOpportunities(prev => prev.filter(o => o.id !== oppId));
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
        <p className="text-[13px] text-gray-400">Loading favorites...</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
      <button
        type="button"
        onClick={() => router.back()}
        className="inline-flex items-center gap-2 text-[13px] text-gray-400 hover:text-gray-600 mb-8 transition-colors duration-300"
      >
        <ArrowLeft className="w-4 h-4" />
        Back
      </button>

      <div className="mb-10">
        <h1 className="text-4xl font-bold text-gray-900 tracking-tight">Favorites</h1>
        <p className="mt-2 text-[15px] text-gray-400">
          {opportunities.length === 0 ? 'No favorites yet.' : `${opportunities.length} saved opportunities.`}
        </p>
      </div>

      {opportunities.length === 0 ? (
        <div className="text-center py-20">
          <Star className="w-10 h-10 text-gray-200 mx-auto mb-4" />
          <p className="text-[15px] text-gray-400 mb-4">
            Star opportunities from the results page to save them here.
          </p>
          <button
            type="button"
            onClick={() => router.push('/')}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-blue-600 text-white text-[13px] font-medium hover:bg-blue-700 transition-colors duration-300"
          >
            Find Matches
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {opportunities.map((opp) => (
            <div
              key={opp.id}
              className="flex items-center justify-between bg-white rounded-xl shadow-[0_1px_4px_rgba(0,0,0,0.04)] px-5 py-4"
            >
              <div className="flex-1 min-w-0 mr-4">
                <h3 className="text-[15px] font-semibold text-gray-900 truncate">{opp.title}</h3>
                <div className="flex items-center gap-2 mt-1">
                  {opp.organization && <span className="text-[12px] text-gray-400">{opp.organization}</span>}
                  {opp.opportunity_type && (
                    <span className="px-2 py-0.5 rounded-md bg-gray-100 text-[11px] text-gray-500">{opp.opportunity_type}</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {opp.url && (
                  <a
                    href={opp.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 rounded-lg bg-black/[0.03] text-[12px] font-medium text-gray-500 hover:bg-black/[0.06] transition-colors duration-300"
                  >
                    View
                  </a>
                )}
                <button
                  type="button"
                  onClick={() => handleRemove(opp.id)}
                  className="p-1.5 rounded-lg hover:bg-red-50 transition-colors duration-200"
                  aria-label="Remove from favorites"
                >
                  <Star className="w-4 h-4 fill-amber-400 text-amber-400" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
