'use client';

import { useEffect } from 'react';
import { AlertTriangle, RotateCw } from 'lucide-react';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[ofe] unhandled error:', error);
  }, [error]);

  const isApiError = /^API \d+:/.test(error.message ?? '');
  const friendly = isApiError
    ? "We couldn't reach the matching service. It may be waking up — please try again in a few seconds."
    : "Something went wrong on this page.";

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
      <div className="bg-white border border-red-200 rounded-2xl p-8 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="shrink-0 w-12 h-12 rounded-full bg-red-50 flex items-center justify-center">
            <AlertTriangle className="w-6 h-6 text-red-600" aria-hidden="true" />
          </div>
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-semibold text-gray-900 mb-2">{friendly}</h1>
            <p className="text-sm text-gray-600 leading-relaxed mb-4">
              {error.digest ? (
                <>
                  Reference ID: <code className="px-1.5 py-0.5 bg-gray-100 rounded text-[12px]">{error.digest}</code>
                  {' — '}include this if you report the issue.
                </>
              ) : (
                'You can retry, or reload the page if the problem persists.'
              )}
            </p>
            <details className="mb-6">
              <summary className="text-[12px] text-gray-500 cursor-pointer hover:text-gray-700 select-none">
                Technical details
              </summary>
              <pre className="mt-2 p-3 bg-gray-50 border border-gray-200 rounded-lg text-[11px] text-gray-700 overflow-auto whitespace-pre-wrap break-words">
                {error.message}
              </pre>
            </details>
            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => reset()}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-[13px] font-medium transition-colors"
              >
                <RotateCw className="w-3.5 h-3.5" aria-hidden="true" />
                Try again
              </button>
              <a
                href="/"
                className="inline-flex items-center px-4 py-2 rounded-lg border border-gray-200 text-gray-700 hover:bg-gray-50 text-[13px] font-medium transition-colors"
              >
                Back home
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
