'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Star,
  ArrowLeft,
  Loader2,
  Mail,
  ExternalLink,
  Globe,
  DollarSign,
  MapPin,
  Building2,
  Clock,
  ChevronDown,
  FileText,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { getFavorites, toggleFavorite } from '@/lib/supabase';
import { getOpportunitiesByIds } from '@/lib/api';
import Badge from '@/components/Badge';
import ColdEmailModal from '@/components/ColdEmailModal';
import type { ProfileData } from '@/lib/types';

interface Opp {
  id: string;
  title: string;
  organization?: string;
  department?: string;
  opportunity_type?: string;
  paid?: string;
  location?: string;
  url?: string;
  source?: string;
  on_campus?: boolean;
  deadline?: string;
  description_clean?: string;
  description_raw?: string;
  keywords?: string[];
  pi_name?: string;
  lab_or_program?: string;
  eligibility?: {
    international_friendly?: string;
    skills_required?: string[];
    years?: string[];
  };
}

function DeadlineBadge({ deadline }: { deadline?: string }) {
  if (!deadline) return null;
  const dl = new Date(deadline + 'T00:00:00');
  const now = new Date();
  const daysLeft = Math.ceil((dl.getTime() - now.getTime()) / 86400000);
  if (daysLeft < 0) return <Badge variant="red"><Clock className="w-3 h-3" />Deadline passed</Badge>;
  if (daysLeft <= 14) return <Badge variant="orange"><Clock className="w-3 h-3" />Due in {daysLeft}d</Badge>;
  return <Badge variant="gray"><Clock className="w-3 h-3" />{deadline}</Badge>;
}

export default function FavoritesPage() {
  const router = useRouter();
  const [opportunities, setOpportunities] = useState<Opp[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [emailModal, setEmailModal] = useState<{ open: boolean; id: string; title: string }>({
    open: false, id: '', title: '',
  });

  useEffect(() => {
    const raw = localStorage.getItem('ofe_profile');
    if (raw) {
      try { setProfile(JSON.parse(raw)); } catch { /* ignore */ }
    }
  }, []);

  useEffect(() => {
    async function load() {
      try {
        const favSet = await getFavorites();
        const ids = Array.from(favSet);
        if (ids.length === 0) { setLoading(false); return; }
        const opps = await getOpportunitiesByIds(ids);
        setOpportunities(opps as unknown as Opp[]);
      } catch { /* ignore */ }
      finally { setLoading(false); }
    }
    load();
  }, []);

  const handleRemove = useCallback(async (oppId: string) => {
    await toggleFavorite(oppId, true);
    setOpportunities(prev => prev.filter(o => o.id !== oppId));
  }, []);

  const toggleExpand = useCallback((id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
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
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
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
          {opportunities.length === 0
            ? 'No favorites yet.'
            : `${opportunities.length} saved opportunity${opportunities.length > 1 ? 'ies' : ''}`}
        </p>
      </div>

      {opportunities.length === 0 ? (
        <div className="text-center py-20">
          <Star className="w-10 h-10 text-gray-200 mx-auto mb-4" />
          <p className="text-[15px] text-gray-400 mb-2">
            Star opportunities from the results page to save them here.
          </p>
          <p className="text-[13px] text-gray-300 mb-6">
            You can compare, draft emails, and track your applications.
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
        <div className="space-y-4">
          {opportunities.map((opp) => {
            const isExpanded = expanded.has(opp.id);
            const intlFriendly = opp.eligibility?.international_friendly;
            const desc = opp.description_clean || opp.description_raw || '';

            return (
              <div
                key={opp.id}
                className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] overflow-hidden transition-shadow hover:shadow-[0_4px_20px_rgba(0,0,0,0.08)]"
              >
                <div className="p-6">
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <div className="flex-1 min-w-0">
                      <h3 className="text-[17px] font-semibold text-gray-900 leading-snug line-clamp-2">
                        {opp.title}
                      </h3>
                      <div className="flex items-center gap-3 mt-2 text-[13px] text-gray-400">
                        {opp.organization && (
                          <span className="inline-flex items-center gap-1">
                            <Building2 className="w-3.5 h-3.5" />
                            {opp.organization}
                          </span>
                        )}
                        {opp.location && (
                          <span className="inline-flex items-center gap-1">
                            <MapPin className="w-3.5 h-3.5" />
                            {opp.location}
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleRemove(opp.id)}
                      className="p-1.5 rounded-lg hover:bg-red-50 transition-colors shrink-0"
                      aria-label="Remove from favorites"
                    >
                      <Star className="w-4.5 h-4.5 fill-amber-400 text-amber-400" />
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5 mb-4">
                    {opp.opportunity_type && <Badge variant="indigo">{opp.opportunity_type}</Badge>}
                    {intlFriendly && (
                      <Badge variant={intlFriendly === 'yes' ? 'green' : intlFriendly === 'no' ? 'red' : 'orange'} dot>
                        <Globe className="w-3 h-3" />
                        {intlFriendly === 'yes' ? 'Intl OK' : intlFriendly === 'no' ? 'US Only' : 'Verify'}
                      </Badge>
                    )}
                    {opp.paid && (
                      <Badge variant={opp.paid === 'yes' || opp.paid === 'stipend' ? 'green' : 'gray'} dot>
                        <DollarSign className="w-3 h-3" />
                        {opp.paid === 'yes' ? 'Paid' : opp.paid === 'stipend' ? 'Stipend' : 'Unpaid'}
                      </Badge>
                    )}
                    {opp.source && <Badge variant="gray">{opp.source}</Badge>}
                    <DeadlineBadge deadline={opp.deadline} />
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    {profile && (
                      <button
                        type="button"
                        onClick={() => setEmailModal({ open: true, id: opp.id, title: opp.title })}
                        className="inline-flex items-center gap-2 px-5 py-2.5 text-[13px] font-semibold text-white bg-gradient-to-r from-blue-600 to-blue-500 rounded-xl hover:from-blue-700 hover:to-blue-600 shadow-sm hover:shadow transition-all duration-200"
                      >
                        <Mail className="w-3.5 h-3.5" />
                        Draft Email
                      </button>
                    )}
                    {opp.url && (
                      <a
                        href={opp.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 px-4 py-2 text-[13px] font-medium text-gray-600 bg-black/[0.04] rounded-xl hover:bg-black/[0.08] transition-colors duration-200"
                      >
                        <FileText className="w-3.5 h-3.5" />
                        View Details
                      </a>
                    )}
                  </div>
                </div>

                <div className="border-t border-black/[0.04]">
                  <button
                    type="button"
                    onClick={() => toggleExpand(opp.id)}
                    className="flex items-center justify-between w-full px-6 py-3 text-[13px] font-medium text-gray-400 hover:text-gray-600 transition-colors"
                  >
                    <span>{isExpanded ? 'Hide details' : 'Show details'}</span>
                    <ChevronDown className={`w-4 h-4 transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`} />
                  </button>

                  {isExpanded && (
                    <div className="px-6 pb-6 space-y-4 animate-in">
                      {(opp.pi_name || opp.lab_or_program || opp.department) && (
                        <div className="flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
                          {opp.pi_name && (
                            <span className="text-gray-500"><span className="font-medium text-gray-700">PI:</span> {opp.pi_name}</span>
                          )}
                          {opp.lab_or_program && (
                            <span className="text-gray-500"><span className="font-medium text-gray-700">Lab:</span> {opp.lab_or_program}</span>
                          )}
                          {opp.department && (
                            <span className="text-gray-500"><span className="font-medium text-gray-700">Dept:</span> {opp.department}</span>
                          )}
                        </div>
                      )}

                      {desc && (
                        <p className="text-[13px] text-gray-500 leading-relaxed line-clamp-4">
                          {desc}
                        </p>
                      )}

                      {opp.eligibility?.skills_required && opp.eligibility.skills_required.length > 0 && (
                        <div>
                          <span className="text-[11px] font-semibold text-indigo-600 uppercase tracking-widest">Required skills</span>
                          <div className="flex flex-wrap gap-1.5 mt-1.5">
                            {opp.eligibility.skills_required.map((s) => (
                              <span key={s} className="px-2.5 py-1 rounded-lg bg-indigo-50 text-indigo-700 text-[12px] font-medium">{s}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {opp.keywords && opp.keywords.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {opp.keywords.slice(0, 8).map((kw) => (
                            <span key={kw} className="px-2 py-0.5 rounded-md bg-gray-100 text-[11px] text-gray-500">{kw}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {profile && (
        <ColdEmailModal
          isOpen={emailModal.open}
          onClose={() => setEmailModal({ open: false, id: '', title: '' })}
          profile={profile}
          opportunityId={emailModal.id}
          opportunityTitle={emailModal.title}
        />
      )}
    </div>
  );
}
