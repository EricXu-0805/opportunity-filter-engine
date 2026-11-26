'use client';

import Link from 'next/link';
import { useT } from '@/i18n/client';

export function WalkthroughDemo() {
  const { locale } = useT();
  const zh = locale === 'zh';
  return (
    <details className="mt-5 rounded-2xl border border-gray-200 bg-white">
      <summary className="cursor-pointer px-5 py-4 font-semibold text-indigo-700 focus-visible:outline-indigo-600">
        {zh ? '观看如何查找并收藏匹配机会' : 'Watch how to find and save a match'}
      </summary>
      <figure className="px-4 pb-4">
        <video
          controls playsInline preload="none"
          width={980} height={630}
          poster="/demo/student-match.webp"
          aria-label={zh ? '学生匹配操作演示' : 'Student matching demo'}
          className="aspect-[14/9] w-full rounded-lg bg-gray-100"
        >
          <source src="/demo/student-match.mp4" type="video/mp4" />
          <track kind="captions" srcLang="en" label="English" src="/demo/student-match.en.vtt" default={!zh} />
          <track kind="captions" srcLang="zh" label="中文" src="/demo/student-match.zh.vtt" default={zh} />
        </video>
        <figcaption className="mt-3 flex flex-wrap items-baseline justify-between gap-x-5 gap-y-2 text-sm text-gray-600">
          <span>{zh ? '演示中的学生和机会均为虚构。' : 'The student and opportunity in this demo are fictional.'}</span>
          <Link href="/" className="font-medium text-indigo-700 underline">{zh ? '开始我的匹配' : 'Start my match'}</Link>
        </figcaption>
      </figure>
    </details>
  );
}
