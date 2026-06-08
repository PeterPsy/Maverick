import { useCallback, useEffect, useRef, useState } from 'react';
import { fitPreviewMediaToBox, type PreviewMediaSize } from './previewSizing';
import type { StorageFile } from './types';

type VideoOverlayMode = 'idle' | 'play' | 'pause';

function VideoPlaybackIcon({ mode }: { mode: Exclude<VideoOverlayMode, 'idle'> }) {
  return (
    <svg className={`storage-video-control-icon storage-video-control-icon-${mode}`} width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      {mode === 'play' ? (
        <path d="M29.0019 14.4751L4.54632 0.357228C3.20341 -0.41894 2.08875 0.114031 1.93089 1.52664C1.91845 1.63899 1.90991 1.75526 1.90991 1.87934V30.1215C1.90991 31.7947 3.09603 32.4792 4.5449 31.6436L28.5354 17.7896L29.0033 17.5197C30.4525 16.6838 30.4525 15.3135 29.0019 14.4751Z" fill="currentColor" />
      ) : (
        <>
          <path d="M11.1712 0H3.66753C2.9609 0 2.35522 0.572029 2.35522 1.3123V30.6877C2.35522 31.3943 2.92725 32 3.66753 32H11.1376C11.8442 32 12.4499 31.428 12.4499 30.6877V1.3123C12.4499 0.572029 11.8778 0 11.1712 0Z" fill="currentColor" />
          <path d="M28.366 0H20.8624C20.1557 0 19.55 0.572029 19.55 1.3123V30.6877C19.55 31.3943 20.1221 32 20.8624 32H28.3324C29.039 32 29.6447 31.428 29.6447 30.6877V1.3123C29.6447 0.572029 29.0727 0 28.366 0Z" fill="currentColor" />
        </>
      )}
    </svg>
  );
}

export function VideoPreview({ file, src }: { file: StorageFile; src: string }) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const overlayTimerRef = useRef<number | null>(null);
  const autoPlayAttemptedRef = useRef(false);
  const userToggledRef = useRef(false);
  const suppressNextPlayOverlayRef = useRef(false);
  const [frameSize, setFrameSize] = useState<PreviewMediaSize | null>(null);
  const [videoSize, setVideoSize] = useState<PreviewMediaSize | null>(null);
  const [overlayMode, setOverlayMode] = useState<VideoOverlayMode>('idle');
  const fittedSize = videoSize && frameSize ? fitPreviewMediaToBox(videoSize, frameSize) : null;
  const videoStyle = fittedSize
    ? { width: `${fittedSize.width}px`, height: `${fittedSize.height}px` }
    : { width: '100%', height: '100%' };

  const clearOverlayTimer = useCallback(() => {
    if (overlayTimerRef.current === null) return;
    window.clearTimeout(overlayTimerRef.current);
    overlayTimerRef.current = null;
  }, []);

  const setVideoOverlayMode = useCallback((mode: VideoOverlayMode) => {
    clearOverlayTimer();
    setOverlayMode(mode);
    if (mode === 'pause') {
      overlayTimerRef.current = window.setTimeout(() => {
        setOverlayMode('idle');
        overlayTimerRef.current = null;
      }, 700);
    }
  }, [clearOverlayTimer]);

  const playVideo = useCallback((showPauseOverlay: boolean) => {
    const video = videoRef.current;
    if (!video) return;
    if (video.ended) {
      try {
        video.currentTime = 0;
      } catch (_error) {
        // Some browsers reject currentTime updates before metadata is ready.
      }
    }
    if (showPauseOverlay) {
      setVideoOverlayMode('pause');
    }
    const playPromise = video.play();
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise.catch(() => {
        suppressNextPlayOverlayRef.current = false;
        setVideoOverlayMode('play');
      });
    }
  }, [setVideoOverlayMode]);

  const attemptAutoPlay = useCallback(() => {
    const video = videoRef.current;
    if (!video || autoPlayAttemptedRef.current || userToggledRef.current || video.readyState < 2) return;
    autoPlayAttemptedRef.current = true;
    suppressNextPlayOverlayRef.current = true;
    playVideo(false);
  }, [playVideo]);

  useEffect(() => {
    setVideoSize(null);
    clearOverlayTimer();
    autoPlayAttemptedRef.current = false;
    userToggledRef.current = false;
    suppressNextPlayOverlayRef.current = false;
    setOverlayMode('idle');
    const video = videoRef.current;
    if (video) {
      try {
        video.currentTime = 0;
      } catch (_error) {
        // Some browsers reject currentTime updates before metadata is ready.
      }
      if (video.readyState >= 2) {
        attemptAutoPlay();
      }
    }
    return clearOverlayTimer;
  }, [attemptAutoPlay, clearOverlayTimer, file.id, src]);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const observedFrame = frame;

    function updateFrameSize() {
      const rect = observedFrame.getBoundingClientRect();
      const nextSize = {
        width: Math.max(0, Math.floor(rect.width)),
        height: Math.max(0, Math.floor(rect.height))
      };
      setFrameSize((current) => (
        current?.width === nextSize.width && current?.height === nextSize.height ? current : nextSize
      ));
    }

    updateFrameSize();
    const observer = new ResizeObserver(updateFrameSize);
    observer.observe(observedFrame);
    return () => observer.disconnect();
  }, []);

  const updateVideoSize = (video: HTMLVideoElement) => {
    if (video.videoWidth <= 0 || video.videoHeight <= 0) return;
    const nextSize = {
      width: video.videoWidth,
      height: video.videoHeight
    };
    setVideoSize((current) => (
      current?.width === nextSize.width && current?.height === nextSize.height ? current : nextSize
    ));
  };

  const handleTogglePlayback = () => {
    const video = videoRef.current;
    if (!video) return;
    userToggledRef.current = true;
    if (video.paused || video.ended) {
      suppressNextPlayOverlayRef.current = false;
      playVideo(true);
      return;
    }
    video.pause();
    setVideoOverlayMode('play');
  };

  const handlePlay = () => {
    if (suppressNextPlayOverlayRef.current) {
      suppressNextPlayOverlayRef.current = false;
      setVideoOverlayMode('idle');
      return;
    }
    setVideoOverlayMode('pause');
  };

  const handlePause = () => {
    if (videoRef.current?.ended) return;
    setVideoOverlayMode('play');
  };

  const overlayLabel = overlayMode === 'play' ? 'Play video' : 'Pause video';

  return (
    <div className="storage-video-preview" ref={frameRef}>
      <video
        ref={videoRef}
        src={src}
        controls
        loop
        playsInline
        preload="auto"
        style={videoStyle}
        onLoadedMetadata={(event) => updateVideoSize(event.currentTarget)}
        onLoadedData={attemptAutoPlay}
        onCanPlay={attemptAutoPlay}
        onPlay={handlePlay}
        onPause={handlePause}
      />
      <button
        className={`storage-video-control is-${overlayMode === 'idle' ? 'idle' : `showing-${overlayMode}`}`}
        type="button"
        onClick={handleTogglePlayback}
        aria-label={overlayLabel}
        title={overlayLabel}
        tabIndex={overlayMode === 'idle' ? -1 : 0}
      >
        <VideoPlaybackIcon mode="play" />
        <VideoPlaybackIcon mode="pause" />
      </button>
    </div>
  );
}
