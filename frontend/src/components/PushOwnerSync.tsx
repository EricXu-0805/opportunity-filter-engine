'use client';

import { useEffect } from 'react';
import { isPushSupported, synchronizePushOwner } from '@/lib/push';
import { supabase } from '@/lib/supabase';

export default function PushOwnerSync() {
  useEffect(() => {
    if (!isPushSupported()) return;
    let timer: ReturnType<typeof setTimeout>;
    // Supabase holds its auth lock during the callback. Read the latest
    // session after it returns, including INITIAL_SESSION after a cold start.
    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        void synchronizePushOwner().catch(() => {
          // Retry on the next auth or connectivity event; the toggle also has a retry.
        });
      }, 0);
    };
    const { data } = supabase.auth.onAuthStateChange(schedule);
    window.addEventListener('online', schedule);
    window.addEventListener('pageshow', schedule);
    return () => {
      clearTimeout(timer);
      data.subscription.unsubscribe();
      window.removeEventListener('online', schedule);
      window.removeEventListener('pageshow', schedule);
    };
  }, []);
  return null;
}
