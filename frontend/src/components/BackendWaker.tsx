'use client';

import { useEffect } from 'react';
import { wakeBackend } from '@/lib/api';

export default function BackendWaker() {
  useEffect(() => {
    wakeBackend();
  }, []);
  return null;
}
