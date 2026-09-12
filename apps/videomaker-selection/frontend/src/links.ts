import type { Candidate } from './types';

const LINK_PATTERN = /(?:https?:\/\/|www\.)[^\s<>"'`]+|(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?:\/[^\s<>"'`]*)?/gi;

export function extractLinks(value: string): string[] {
  const found = value.match(LINK_PATTERN) || [];
  const unique = new Map<string, string>();
  for (const raw of found) {
    const cleaned = raw.replace(/[.,;:!?]+$/, '').replace(/\)+$/, '');
    const href = /^https?:\/\//i.test(cleaned) ? cleaned : `https://${cleaned}`;
    try {
      const parsed = new URL(href);
      const key = `${parsed.hostname.toLowerCase()}${parsed.pathname.replace(/\/$/, '')}?${parsed.searchParams}`;
      if (parsed.hostname.includes('.') && !unique.has(key)) unique.set(key, href);
    } catch {
      continue;
    }
  }
  return [...unique.values()];
}

export function portfolioLinks(candidate: Candidate): string[] {
  return candidate.portfolio_links?.length ? candidate.portfolio_links : extractLinks(candidate.portfolio_url || '');
}

export function instagramLinks(candidate: Candidate): string[] {
  if (candidate.instagram_links?.length) return candidate.instagram_links;
  const source = [
    candidate.portfolio_url, candidate.bio, candidate.profile_answer, candidate.social_usage,
    candidate.workflow, candidate.opportunity, candidate.additional_info,
  ].filter(Boolean).join(' ');
  const profiles = new Map<string, string>();
  for (const href of extractLinks(source)) {
    try {
      const url = new URL(href);
      const host = url.hostname.toLowerCase().replace(/^www\./, '');
      const segments = url.pathname.split('/').filter(Boolean);
      const reserved = new Set(['about','accounts','challenge','developer','direct','explore','legal','p','reel','reels','share','stories','tv','web']);
      if (host !== 'instagram.com' || segments.length !== 1 || reserved.has(segments[0].toLowerCase())) continue;
      const canonical = `https://www.instagram.com/${segments[0]}/`;
      profiles.set(canonical.toLowerCase(), canonical);
    } catch {
      continue;
    }
  }
  return [...profiles.values()];
}

export function linkLabel(value: string): string {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase().replace(/^www\./, '');
    const firstPath = url.pathname.split('/').filter(Boolean)[0]?.toLowerCase();
    if (host === 'instagram.com') {
      if (firstPath === 'reel' || firstPath === 'reels') return 'Instagram Reel';
      if (firstPath === 'p') return 'Instagram Post';
      return 'Profilo Instagram';
    }
    if (host.includes('drive.google.com')) return 'Google Drive';
    if (host.includes('docs.google.com')) return 'Google Docs';
    if (host.includes('youtube.com') || host === 'youtu.be') return 'YouTube';
    if (host.includes('canva.')) return 'Canva';
    if (host.includes('behance.net')) return 'Behance';
    if (host.includes('myportfolio.com')) return 'Adobe Portfolio';
    if (host.includes('tiktok.com')) return 'TikTok';
    if (host.includes('linktr.ee')) return 'Linktree';
    if (host.includes('swisstransfer.com')) return 'SwissTransfer';
    return host;
  } catch {
    return 'Portfolio';
  }
}

export function linkPreview(value: string): string {
  try {
    const url = new URL(value);
    const host = url.hostname.replace(/^www\./, '');
    const path = decodeURIComponent(url.pathname).replace(/\/$/, '');
    const preview = `${host}${path}`;
    return preview.length > 58 ? `${preview.slice(0, 55)}…` : preview;
  } catch {
    return value;
  }
}

export function instagramHandle(value: string): string {
  try {
    return `@${new URL(value).pathname.split('/').filter(Boolean)[0] || 'Instagram'}`;
  } catch {
    return 'Profilo Instagram';
  }
}
