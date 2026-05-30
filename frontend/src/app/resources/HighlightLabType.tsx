'use client';

import { useEffect } from 'react';

const VALID_LAB_TYPES = new Set(['wet', 'dry', 'humanities']);
const RING_CLASSES = ['ring-2', 'ring-blue-400', 'ring-offset-2', 'ring-offset-white'];

export default function HighlightLabType() {
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const lab = params.get('lab');
    if (!lab || !VALID_LAB_TYPES.has(lab)) return;

    const el = document.getElementById(`tips-card-${lab}`);
    if (!el) return;

    el.classList.add(...RING_CLASSES);
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });

    const timer = setTimeout(() => {
      el.classList.remove(...RING_CLASSES);
    }, 2400);

    return () => {
      clearTimeout(timer);
      el.classList.remove(...RING_CLASSES);
    };
  }, []);

  return null;
}
