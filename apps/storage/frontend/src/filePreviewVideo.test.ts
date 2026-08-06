import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const currentDir = dirname(fileURLToPath(import.meta.url));

function readSource(path: string) {
  return readFileSync(resolve(currentDir, path), 'utf8');
}

describe('storage video preview playback', () => {
  it('loads video previews paused and exposes the central playback toggle', () => {
    const source = readSource('videoPreview.tsx');

    expect(source).toContain('export function VideoPreview');
    expect(source).not.toContain('attemptAutoPlay');
    expect(source).not.toContain('onLoadedData');
    expect(source).not.toContain('onCanPlay');
    expect(source).toContain('fitPreviewMediaToBox(videoSize, frameSize)');
    expect(source).toContain(": { width: '100%', height: '100%' };");
    expect(source).toContain('loop');
    expect(source).toContain('preload="auto"');
    expect(source).toContain("'webkit-playsinline': 'true'");
    expect(source).toContain('{...inlineVideoPlaybackProps}');
    expect(source).toContain('onLoadedMetadata={(event) => updateVideoSize(event.currentTarget)}');
    expect(source).toContain("useState<VideoOverlayMode>('play')");
    expect(source).toContain('video.play()');
    expect(source).toContain('video.pause()');
    expect(source).toContain("setVideoOverlayMode('play')");
    expect(source).toContain("setVideoOverlayMode('pause')");
    expect(source).toContain('storage-video-control is-');
    expect(source).toContain('M29.0019 14.4751L4.54632');
    expect(source).toContain('M11.1712 0H3.66753');

    const videoStart = source.indexOf('<video');
    const videoMarkup = source.slice(videoStart, source.indexOf('/>', videoStart));
    expect(videoMarkup).not.toContain('controls');
  });

  it('styles the video overlay with the Loopino vform play and pause treatment', () => {
    const styles = readSource('styles/video-preview.css');
    const component = readSource('videoPreview.tsx');

    expect(component).toContain("import './styles/video-preview.css';");
    expect(styles).toContain('.storage-video-control.is-showing-play .storage-video-control-icon-play');
    expect(styles).toContain('.storage-video-control.is-showing-pause .storage-video-control-icon-pause');
    expect(styles).toMatch(/\.storage-video-preview > video \{[\s\S]*width: auto;[\s\S]*height: auto;/);
    expect(styles).toContain('filter: drop-shadow(0 10px 24px rgba(0, 0, 0, 0.72));');
    expect(styles).toContain('@keyframes storage-video-control-pop');
  });
});
