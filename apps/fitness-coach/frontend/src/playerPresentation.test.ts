import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('work player presentation', () => {
  const styles = readFileSync(new URL('./styles.css', import.meta.url), 'utf8');
  const appSource = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
  const restIcon = readFileSync(new URL('../public/rest-icon.svg', import.meta.url), 'utf8');

  it('contains workout media instead of cropping it', () => {
    expect(styles).toMatch(/\.player-media video,\s*\.player-media img\s*{[\s\S]*object-fit:\s*contain;/);
    expect(styles).toMatch(/\.player-media video,\s*\.player-media img\s*{[\s\S]*object-position:\s*center top;/);
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
    expect(styles).toMatch(/\.player-time span\s*{[\s\S]*font-size:\s*0\.86rem;/);
    expect(styles).toMatch(/@media \(max-width: 920px\)[\s\S]*\.player-bottom-actions button span\s*{[\s\S]*display:\s*none;/);
  });

  it('anchors top player controls below the mobile shell without double-counting safe area', () => {
    expect(styles).toMatch(/--fitness-player-top-offset:\s*var\(--maverick-shell-mobile-content-top-offset,\s*env\(safe-area-inset-top,\s*0px\)\);/);
    expect(styles).toMatch(/--fitness-player-progress-top:\s*calc\(0\.62rem \+ var\(--fitness-player-top-offset\)\);/);
    expect(styles).toMatch(/\.player-progress\s*{[\s\S]*top:\s*var\(--fitness-player-progress-top\);/);
    expect(styles).toMatch(/\.player-top\s*{[\s\S]*top:\s*var\(--fitness-player-heading-top\);/);
    expect(styles).not.toContain('env(safe-area-inset-top) + var(--fitness-shell-top-offset)');
  });

  it('keeps workout media from rendering above the progress indicator under the shell header', () => {
    expect(styles).toMatch(/\.player-media,\s*\.player-scrim\s*{[\s\S]*top:\s*var\(--fitness-player-progress-top\);/);
  });

  it('uses the rest icon in workout rest blocks and the active rest player overlay', () => {
    expect(restIcon).toContain('<svg width="40" height="40"');
    expect(appSource).toContain("const REST_ICON_SRC = 'rest-icon.svg';");
    expect(appSource).toContain('className="rest-block-layout"');
    expect(appSource).toContain('className="player-rest-overlay"');
    expect(appSource).toContain('<RestIconImage className="player-rest-icon" />');
    const restControlsStart = appSource.indexOf('className={`mode-value-row ${block.type ===');
    const restIndexPosition = appSource.indexOf('className="block-index"', restControlsStart);
    const restIconPosition = appSource.indexOf('className="rest-block-icon-frame"', restControlsStart);
    expect(restIconPosition).toBeGreaterThan(restIndexPosition);
    expect(styles).toContain('.rest-block-icon-frame');
    expect(styles).toContain('.player-rest-overlay');
    expect(styles).toContain('.player-rest-icon');
  });
});
