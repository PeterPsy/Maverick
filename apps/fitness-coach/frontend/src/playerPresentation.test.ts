import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';

describe('work player presentation', () => {
  const styles = readFileSync(new URL('./styles.css', import.meta.url), 'utf8');
  const appSource = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
  const gradientBarsSource = readFileSync(new URL('./components/ui/gradient-bars-background.tsx', import.meta.url), 'utf8');
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

  it('opens the exercise player from workout and library previews without extra play badges', () => {
    expect(appSource).toContain('const [exercisePlayer, setExercisePlayer] = useState<Exercise | null>(null);');
    expect(appSource).toContain('return <ExercisePlayer exercise={exercisePlayer} onClose={() => setExercisePlayer(null)} />;');
    expect(appSource).toContain('onOpenExercisePlayer={setExercisePlayer}');
    expect(appSource).toContain('onOpenPlayer={setExercisePlayer}');
    expect(appSource).toContain('function ExercisePlayer');
    const exercisePlayerStart = appSource.indexOf('function ExercisePlayer');
    const workPlayerStart = appSource.indexOf('function WorkPlayer', exercisePlayerStart);
    const exercisePlayerSource = appSource.slice(exercisePlayerStart, workPlayerStart);
    expect(exercisePlayerSource).not.toContain('requestFullscreen');
    expect(appSource).toContain('function exerciseForPlayerFromBlock');
    expect(appSource).toContain('className="exercise-preview-button"');
    expect(appSource).toContain('className="block-media-panel block-exercise-player-trigger"');
    expect(appSource).not.toContain('className="block-exercise-copy block-exercise-title-button"');
    expect(appSource).not.toContain('exercise-player-trigger-icon');
    expect(appSource).toContain('playerFallbackResolution(media, currentResolution)');
    expect(appSource).toContain('playerFallbackResolution(segment.media, currentResolution)');
    expect(styles).toContain('.exercise-player-header .player-top');
    expect(styles).toContain('.exercise-preview-button');
    expect(styles).toContain('.block-exercise-player-trigger:disabled');
    expect(styles).not.toContain('.exercise-player-trigger-icon');
  });

  it('shows skeleton-backed media previews and contains loaded media without a background', () => {
    expect(appSource).toContain('const [previewLoaded, setPreviewLoaded] = useState(false);');
    expect(appSource).toContain('className="media-thumb-skeleton"');
    expect(appSource).toContain("previewLoaded ? 'is-media-ready' : 'is-preview-loading'");
    expect(appSource).toContain('onLoad={() => setPreviewLoaded(true)}');
    expect(styles).toMatch(/\.media-thumb\.is-media-ready\s*{[\s\S]*background:\s*transparent;/);
    expect(styles).toMatch(/\.media-thumb video,\s*\.media-thumb img\s*{[\s\S]*object-fit:\s*contain;/);
    expect(styles).toContain('.media-thumb.is-preview-loading video');
    expect(styles).toContain('.media-thumb-skeleton::after');
    expect(styles).not.toMatch(/\.media-thumb video,\s*\.media-thumb img\s*{[\s\S]*object-fit:\s*cover;/);
  });

  it('places exercise title and close action above centered bottom timing controls', () => {
    expect(appSource).toContain('className="player-heading"');
    expect(appSource).toContain('{segment.title}');
    expect(appSource).toContain('const segmentDescription = segment.short_description || segment.long_description ||');
    expect(appSource).toContain('className="player-icon player-close"');
    expect(appSource).toContain("className={`player-time ${isReps ? 'is-reps' : ''}`}");
    expect(appSource).not.toContain('counter-pill');
  });

  it('uses a larger inline title and expands descriptions without opening a dialog', () => {
    expect(appSource).toContain("className={`player-header ${descriptionExpanded ? 'is-expanded' : ''}`}");
    expect(styles).toMatch(/\.player-heading strong\s*{[\s\S]*font-size:\s*1\.42rem;/);
    expect(appSource).toContain('const [descriptionExpanded, setDescriptionExpanded] = useState(false);');
    expect(appSource).toContain('const visibleDescription = descriptionExpanded && fullDescription ? fullDescription : segmentDescription;');
    expect(appSource).toContain('setDescriptionExpanded((value) => !value)');
    expect(appSource).toContain('<span>{visibleDescription}</span>');
    expect(appSource).not.toContain('sheet-backdrop');
    expect(appSource).not.toContain('description-sheet');
    expect(appSource).not.toContain('role="dialog" aria-modal="true"');
    expect(styles).toMatch(/\.player-description\.is-open span\s*{[\s\S]*-webkit-line-clamp:\s*unset;/);
  });

  it('wraps progress and exercise copy in a full-width fading header', () => {
    expect(styles).toMatch(/--fitness-player-heading-gap:\s*0\.74rem;/);
    expect(styles).toMatch(/\.player-header\s*{[\s\S]*top:\s*var\(--fitness-player-progress-top\);[\s\S]*right:\s*0;[\s\S]*left:\s*0;[\s\S]*border:\s*0;[\s\S]*background:\s*linear-gradient/);
    expect(styles).toMatch(/\.player-header\.is-expanded\s*{[\s\S]*padding-bottom:\s*1\.6rem;/);
    expect(styles).toMatch(/\.player-top\s*{[\s\S]*margin-top:\s*var\(--fitness-player-heading-gap\);/);
  });

  it('renders the player close action as a white shadowed X without a visible button frame', () => {
    expect(styles).toMatch(/\.player-close\s*{[\s\S]*border:\s*0;[\s\S]*background:\s*transparent;[\s\S]*box-shadow:\s*none;[\s\S]*color:\s*#fff;[\s\S]*filter:\s*drop-shadow/);
  });

  it('shows reps player segments with the same mode label treatment as timers', () => {
    expect(appSource).toContain('const counter = isReps ? formatRepsCounter(segment.reps, segment.repsLabel) : formatClock(remaining);');
    expect(appSource).toContain("const segmentModeLabel = segment.type === 'rest' ? (segment.phase === 'preparation' ? 'Preparation' : 'Rest') : isReps ? 'Reps' : 'Timer';");
    expect(appSource).toContain("className={`player-time ${isReps ? 'is-reps' : ''}`}");
    expect(appSource).toContain('{segmentModeLabel ? <span>{segmentModeLabel}</span> : null}');
    expect(appSource).not.toContain("segment.repsLabel || 'reps'");
  });

  it('places a default-off audio unlock toggle to the left of the close action', () => {
    expect(appSource).toContain('Volume2,');
    expect(appSource).toContain('VolumeX,');
    expect(appSource).toContain('const [audioEnabled, setAudioEnabled] = useState(false);');
    expect(appSource).toContain('const audioContextRef = useRef<AudioContext | null>(null);');
    expect(appSource).toContain('const unlocked = await unlockWorkoutAudio(countdownAudioRef.current, audioContextRef);');
    expect(appSource).toContain("const audioToggleLabel = audioEnabled ? 'Turn workout audio off' : 'Turn workout audio on';");
    expect(appSource).toContain('className="player-control-stack"');
    expect(appSource).toContain("className={`player-icon player-audio ${audioEnabled ? 'is-on' : 'is-off'}`}");
    expect(appSource).toContain('aria-pressed={audioEnabled}');
    expect(appSource).toContain('onClick={toggleAudio}');
    const workPlayerStart = appSource.indexOf('function WorkPlayer');
    const controlsStart = appSource.indexOf('className="player-control-stack"', workPlayerStart);
    const audioPosition = appSource.indexOf('player-audio', controlsStart);
    const closePosition = appSource.indexOf('player-close', controlsStart);
    expect(audioPosition).toBeGreaterThan(controlsStart);
    expect(audioPosition).toBeLessThan(closePosition);
    expect(styles).toContain('.player-control-stack');
    expect(styles).toMatch(/\.player-control-stack\s*{[\s\S]*display:\s*inline-flex;[\s\S]*justify-content:\s*flex-end;/);
    expect(styles).toContain('.player-audio.is-off');
  });

  it('uses animated rest background with a skeleton-backed next-exercise preview', () => {
    expect(appSource).toContain("className=\"player-media-backdrop is-rest-background\"");
    expect(appSource).toContain('const [nextPreviewResolution, setNextPreviewResolution] = useState(initialMediaResolution());');
    expect(appSource).toContain('const nextPreviewCandidate = nextWorkSegment(segments, index);');
    expect(appSource).toContain("className=\"player-next-preview\"");
    expect(appSource).toContain('<NextPreviewMedia resolution={nextPreviewResolved} isLoaded={nextPreviewMediaLoaded} onLoaded={markMediaLoaded} />');
    expect(appSource).toContain('function NextPreviewMedia');
    expect(appSource).toContain('className="player-next-preview-media is-loading"');
    expect(appSource).toContain('className="player-next-preview-skeleton"');
    expect(appSource).not.toContain('player-rest-preview-placeholder');
    const previewStart = appSource.indexOf('function NextPreviewMedia');
    const previewSource = appSource.slice(previewStart, appSource.indexOf('function MediaThumb', previewStart));
    expect(previewSource).not.toContain('GradientBarsBackground');
    expect(styles).toContain('.player-next-preview');
    expect(styles).toMatch(/\.player-next-preview-media video,\s*\.player-next-preview-media img,\s*\.player-next-preview-skeleton\s*{[\s\S]*object-fit:\s*contain;/);
    expect(styles).toContain('.player-next-preview-skeleton::after');
    expect(styles).not.toContain('.player-rest-preview-placeholder');
  });

  it('preloads the next workout media from preparation and keeps cached media off the black frame path', () => {
    expect(appSource).toContain('resolveMediaPlayback(nextPreviewCandidate.media)');
    expect(appSource).toContain('const hasNextPreloadLayer = nextPreviewResolved.status ===');
    expect(appSource).toContain('function PlayerMediaLayer');
    expect(appSource).toContain('role="preload"');
    expect(appSource).toContain('data-player-media-role={role}');
    expect(appSource).toContain('key={nextPreviewResolved.url}');
    expect(appSource).toContain('key={currentResolution.url}');
    expect(appSource).toContain('requestVideoFrameCallback');
    expect(appSource).toContain('cachedMediaPlayback(segment.media) || initialMediaResolution()');
    expect(appSource).toContain('const currentMediaLoaded = currentResolution.status ===');
    expect(appSource).toContain("currentResolution.status !== 'ready'");
    expect(appSource).toContain('video.readyState >= 2');
    expect(appSource).toContain('video.load();');
    expect(appSource).toContain("autoPlay={role === 'current' && !paused}");
    expect(appSource).not.toContain("if (!video || currentResolution.mediaKind !== 'video' || !currentMediaLoaded) return;");
    expect(appSource).toContain("preload=\"auto\"");
    expect(appSource).toContain("const className = role === 'preload' ? 'is-preload-layer' : isLoaded ? 'is-frame-ready' : 'is-awaiting-frame';");
    expect(styles).toContain('.player-media-backdrop.is-frame-wait');
    expect(styles).toContain('.player-media .is-awaiting-frame');
    expect(styles).toContain('.player-media .is-preload-layer');
  });

  it('shows the next exercise preview during the final five seconds of timed work blocks', () => {
    expect(appSource).toContain('const shouldShowNextPreview = Boolean(nextPreviewCandidate) && (');
    expect(appSource).toContain("segment.type === 'rest'");
    expect(appSource).toContain('? segment.showNextExercise');
    expect(appSource).toContain("segment.mode === 'timer' && remaining <= 5 && remaining > 0");
    expect(appSource).toContain('const nextSegmentPreview = shouldShowNextPreview ? nextPreviewCandidate : null;');
  });

  it('keeps bottom action labels on desktop and hides them on mobile', () => {
    expect(styles).toMatch(/\.player-bottom-actions\s*{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\) auto minmax\(0, 1fr\);/);
    expect(styles).toMatch(/\.player-time span\s*{[\s\S]*font-size:\s*0\.86rem;/);
    expect(styles).toMatch(/@media \(max-width: 920px\)[\s\S]*\.player-bottom-actions button span\s*{[\s\S]*display:\s*none;/);
  });

  it('anchors top player controls below the mobile shell without double-counting safe area', () => {
    expect(styles).toMatch(/--fitness-player-top-offset:\s*var\(--maverick-shell-mobile-content-top-offset,\s*env\(safe-area-inset-top,\s*0px\)\);/);
    expect(styles).toMatch(/--fitness-player-progress-top:\s*calc\(0\.62rem \+ var\(--fitness-player-top-offset\)\);/);
    expect(styles).toMatch(/\.player-header\s*{[\s\S]*top:\s*var\(--fitness-player-progress-top\);/);
    expect(styles).toMatch(/\.player-top\s*{[\s\S]*margin-top:\s*var\(--fitness-player-heading-gap\);/);
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

  it('renders a fixed preparation block before editable workout blocks', () => {
    expect(appSource).toContain('function PreparationBlockEditor');
    expect(appSource).toContain('<PreparationBlockEditor index={0} />');
    const preparationStart = appSource.indexOf('function PreparationBlockEditor');
    const preparationSource = appSource.slice(preparationStart, appSource.indexOf('function BlockEditor', preparationStart));
    expect(preparationSource).toContain('className="block-editor is-rest is-preparation"');
    expect(preparationSource).toContain('Preparation');
    expect(preparationSource).toContain('{PREPARATION_BLOCK_SECONDS} seconds');
    expect(preparationSource).toContain('<RestIconImage className="rest-block-icon" />');
    expect(preparationSource).not.toContain('reorderItemProps');
    expect(preparationSource).not.toContain('onDelete');
    expect(preparationSource).not.toContain('onDuplicate');
    expect(preparationSource).not.toContain('<select');
    expect(preparationSource).not.toContain('NumberField');
    const fixedBlockPosition = appSource.indexOf('<PreparationBlockEditor index={0} />');
    const editableBlocksPosition = appSource.indexOf('{workout.blocks.map', fixedBlockPosition);
    expect(editableBlocksPosition).toBeGreaterThan(fixedBlockPosition);
    expect(styles).toContain('.block-editor.is-preparation');
    expect(styles).toContain('.preparation-block-duration');
  });

  it('replaces the resolving media text placeholder with animated gradient bars', () => {
    expect(appSource).toContain('GradientBarsBackground');
    expect(appSource).toContain('className={`player-media-backdrop is-${currentResolution.status}`}');
    expect(appSource).not.toContain('Resolving Storage media');
    expect(styles).toContain('.player-media-backdrop');
    expect(styles).toContain('.player-media-backdrop-message');
    expect(gradientBarsSource).toContain('fitnessGradientBarPulse');
    expect(gradientBarsSource).toContain("gradientFrom = 'rgb(215, 219, 220)'");
    expect(gradientBarsSource).toContain("backgroundColor = '#050605'");
  });

  it('uses the bundled countdown sound for timed work and rest segments', () => {
    const countdownSound = readFileSync(new URL('../public/count-down-fitness-coach.mp3', import.meta.url));
    const checksum = createHash('sha256').update(countdownSound).digest('hex');
    expect(countdownSound.byteLength).toBe(60654);
    expect(checksum).toBe('7f8814b4d5a6136bd21725e22fd362cf707967c8c808e155678f4d2258e952aa');
    expect(appSource).toContain("const COUNTDOWN_SOUND_SRC = '/apps/fitness-coach/count-down-fitness-coach.mp3';");
    expect(appSource).toContain('const COUNTDOWN_SOUND_LEAD_MS = 3800;');
    expect(appSource).toContain('const audio = new Audio(COUNTDOWN_SOUND_SRC);');
    expect(appSource).toContain("if (!segment || paused || segment.type === 'work' && segment.mode === 'reps') return;");
    expect(appSource).toContain('audioEnabled && remainingMs <= COUNTDOWN_SOUND_LEAD_MS');
    expect(appSource).toContain('countdownPlayedRef.current = true;');
    expect(appSource).toContain('playCountdownSound(countdownAudioRef.current);');
    expect(appSource).toContain('if (audioEnabled) playTone(820, 0.16, audioContextRef.current);');
    expect(appSource).toContain('async function unlockWorkoutAudio');
    expect(appSource).toContain('async function unlockCountdownAudio');
    expect(appSource).toContain('async function unlockToneAudio');
    expect(appSource).toContain('function disableWorkoutAudio');
    expect(appSource).not.toContain('playTone(520, 0.08);');
  });
});
