import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('work player presentation', () => {
  const styles = readFileSync(new URL('./styles.css', import.meta.url), 'utf8');
  const appSource = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');

  it('contains workout media instead of cropping it', () => {
    expect(styles).toMatch(/\.player-media video,\s*\.player-media img\s*{[\s\S]*object-fit:\s*contain;/);
  });

  it('animates the current progress segment with a per-step duration variable', () => {
    expect(styles).toContain('@keyframes fitness-player-progress-fill');
    expect(styles).toMatch(/\.player-progress-fill\s*{[\s\S]*animation:\s*fitness-player-progress-fill var\(--fitness-player-progress-duration, 60s\) linear forwards;/);
    expect(styles).toMatch(/\.player-progress > span\.is-current\.is-looping \.player-progress-fill\s*{[\s\S]*animation-iteration-count:\s*infinite;/);
  });

  it('uses a storage-style central playback overlay', () => {
    expect(appSource).toContain('player-playback-control');
    expect(appSource).toContain('player-playback-icon-play');
    expect(appSource).toContain('player-playback-icon-pause');
    expect(styles).toContain('.player-playback-control.is-showing-play .player-playback-icon-play');
    expect(styles).toContain('.player-playback-control.is-showing-pause .player-playback-icon-pause');
    expect(styles).toContain('@keyframes player-playback-control-pop');
  });

  it('places exercise title and close action above centered bottom timing controls', () => {
    expect(appSource).toContain('className="player-heading"');
    expect(appSource).toContain('{segment.title}');
    expect(appSource).toContain('const segmentDescription = segment.short_description || segment.long_description ||');
    expect(appSource).toContain('className="player-icon player-close"');
    expect(appSource).toContain('className="player-time"');
    expect(appSource).not.toContain('counter-pill');
  });

  it('keeps bottom action labels on desktop and hides them on mobile', () => {
    expect(styles).toMatch(/\.player-bottom-actions\s*{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\) auto minmax\(0, 1fr\);/);
    expect(styles).toMatch(/@media \(max-width: 920px\)[\s\S]*\.player-bottom-actions button span\s*{[\s\S]*display:\s*none;/);
  });
});
