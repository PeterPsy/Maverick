import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as ReactPointerEvent, Ref, SyntheticEvent as ReactSyntheticEvent } from 'react';
import {
  ArrowDown,
  Check,
  ChevronLeft,
  Copy,
  Dumbbell,
  Library,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Save,
  Search,
  SkipForward,
  Timer,
  Trash2,
  Volume2,
  VolumeX,
  X
} from 'lucide-react';
import {
  bootstrapApp,
  completeWorkout,
  createExercise,
  createWorkout,
  currentStorageAppId,
  deleteExercise,
  deleteWorkout,
  duplicateWorkout,
  getWorkout,
  listExercises,
  listRuns,
  listWorkouts,
  openStorageVideoPicker,
  saveExercise,
  saveWorkout,
  startWorkout,
  storageMediaSelectionFromPickerParams,
  updateViewState
} from './api';
import { readBootstrapCache, writeBootstrapCache } from './bootstrapCache';
import { GradientBarsBackground } from './components/ui/gradient-bars-background';
import { cachedMediaPlayback, cancelMediaPlayback, clearMediaPlaybackCache, createLocalBlobFallback, driveMediaStreamUrl, initialMediaResolution, latestMediaPlaybackError, mediaCacheKey, preloadMediaPlayback, resolveMediaPlayback, retainMediaPlayback } from './mediaPlaybackResolver';
import { latestMediaResourceTiming, recordMediaPlaybackMetric } from './mediaPlaybackMetrics';
import { captureMediaThumbVideoFrame, mediaThumbPreviewFrameKey, readMediaThumbPreviewFrame } from './mediaThumbPreviewCache';
import { TagsInputField } from './components/ui/tags-input';
import type { AppBootstrapPayload, Exercise, ExerciseMediaRef, MediaPlaybackResolution, RestBlock, RuntimeSegment, SetupTab, StartWorkoutPayload, ViewState, WorkBlock, Workout, WorkoutBlock, WorkoutRunSummary } from './types';
import { useWorkoutBlockReorder, type ReorderItemProps } from './useWorkoutBlockReorder';
import { completeWorkoutAfterConfirmedStart } from './workoutCompletion';
import { PREPARATION_BLOCK_SECONDS, runtimeSegmentsForWorkout, segmentProgressRepeats, segmentProgressSeconds } from './workoutSegments';
import { validateWorkoutForStart } from './workoutValidation';
import countdownSoundSrc from './assets/count-down-fitness-coach.mp3';
import restIconSrc from './assets/rest-icon.svg';

const EMPTY_EXERCISE: Partial<Exercise> = {
  title: '',
  short_description: '',
  long_description: '',
  tags: [],
  primary_media: null,
  media: [],
  source_folder: null,
  source_display_path: null
};

type WorkoutBlockMode = 'timer' | 'reps' | 'rest';
type PlayerPlaybackOverlay = 'idle' | 'play' | 'pause';
type PlayerSession = {
  workout: Workout;
  startPromise: Promise<StartWorkoutPayload>;
};
const REST_ICON_SRC = restIconSrc;
const COUNTDOWN_SOUND_SRC = countdownSoundSrc;
const COUNTDOWN_SOUND_LEAD_MS = 3800;
const inlineVideoPlaybackProps = {
  playsInline: true,
  'webkit-playsinline': 'true'
} as const;

export function App() {
  const [workouts, setWorkouts] = useState<Workout[]>([]);
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [runs, setRuns] = useState<WorkoutRunSummary[]>([]);
  const [selectedWorkoutId, setSelectedWorkoutId] = useState<string | null>(null);
  const [setupTab, setSetupTab] = useState<SetupTab>('workout-settings');
  const [libraryQuery, setLibraryQuery] = useState('');
  const [libraryTag, setLibraryTag] = useState('');
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [playerSession, setPlayerSession] = useState<PlayerSession | null>(null);
  const [exercisePlayer, setExercisePlayer] = useState<Exercise | null>(null);
  const [exerciseDraft, setExerciseDraft] = useState<Partial<Exercise> | null>(null);
  const [libraryTargetBlockId, setLibraryTargetBlockId] = useState<string | null>(null);
  const [savedWorkoutId, setSavedWorkoutId] = useState<string | null>(null);
  const dirtyWorkoutIdsRef = useRef<Set<string>>(new Set());
  const lastSyncedViewStateRef = useRef<Pick<ViewState, 'selected_workout_id' | 'setup_tab'> | null>(null);

  const selectedWorkout = useMemo(
    () => selectedWorkoutId ? workouts.find((workout) => workout.id === selectedWorkoutId) || null : workouts[0] || null,
    [selectedWorkoutId, workouts]
  );
  const syncedSelectedWorkout = useMemo(() => syncWorkoutExerciseSnapshots(selectedWorkout, exercises), [selectedWorkout, exercises]);
  const validation = useMemo(() => validateWorkoutForStart(syncedSelectedWorkout), [syncedSelectedWorkout]);
  const tags = useMemo(() => Array.from(new Set(exercises.flatMap((exercise) => exercise.tags))).sort(), [exercises]);

  const applyBootstrapPayload = useCallback((payload: AppBootstrapPayload) => {
    const nextWorkouts = payload.workouts?.length
      ? payload.workouts
      : payload.selected_workout
        ? [payload.selected_workout]
        : [];
    const selectedId = payload.view_state?.selected_workout_id || payload.selected_workout?.id || nextWorkouts[0]?.id || null;
    const nextSetupTab = payload.view_state?.setup_tab === 'exercise-library' ? 'exercise-library' : 'workout-settings';
    setWorkouts((current) => mergeDirtyWorkouts(nextWorkouts, current, dirtyWorkoutIdsRef.current));
    setExercises(payload.exercises || []);
    if (payload.runs?.length) {
      setRuns(payload.runs);
    }
    lastSyncedViewStateRef.current = { selected_workout_id: selectedId, setup_tab: nextSetupTab };
    setSelectedWorkoutId(selectedId);
    setSetupTab(nextSetupTab);
  }, []);

  const refresh = useCallback(async () => {
    const [nextWorkouts, nextExercises] = await Promise.all([listWorkouts(), listExercises()]);
    setWorkouts((current) => mergeDirtyWorkouts(nextWorkouts, current, dirtyWorkoutIdsRef.current));
    setExercises(nextExercises);
    setSelectedWorkoutId((current) => current && nextWorkouts.some((workout) => workout.id === current) ? current : nextWorkouts[0]?.id || null);
  }, []);

  const markWorkoutDirty = useCallback((workout: Workout) => {
    dirtyWorkoutIdsRef.current.add(workout.id);
    setSavedWorkoutId(null);
    setWorkouts((items) => replaceById(items, workout));
  }, []);

  useEffect(() => {
    let isCurrent = true;
    const cached = readBootstrapCache();
    if (cached) {
      applyBootstrapPayload(cached);
      setIsInitialLoading(false);
    }
    bootstrapApp({ includeRuns: false })
      .then((payload) => {
        if (!isCurrent) return;
        writeBootstrapCache(payload);
        applyBootstrapPayload(payload);
        setNotice('');
      })
      .catch((error: Error) => {
        if (isCurrent) {
          setNotice(error.message);
        }
      })
      .finally(() => {
        if (isCurrent) {
          setIsInitialLoading(false);
        }
      });
    return () => {
      isCurrent = false;
    };
  }, [applyBootstrapPayload]);

  useEffect(() => {
    if (!selectedWorkoutId || isInitialLoading) return;
    let isCurrent = true;
    listRuns(selectedWorkoutId)
      .then((nextRuns) => {
        if (isCurrent) setRuns(nextRuns);
      })
      .catch(() => undefined);
    return () => {
      isCurrent = false;
    };
  }, [isInitialLoading, selectedWorkoutId]);

  useEffect(() => {
    if (!selectedWorkoutId || workouts.some((workout) => workout.id === selectedWorkoutId) || dirtyWorkoutIdsRef.current.has(selectedWorkoutId)) return;
    let isCurrent = true;
    getWorkout(selectedWorkoutId)
      .then((workout) => {
        if (isCurrent) setWorkouts((items) => replaceById(items, workout));
      })
      .catch((error: Error) => {
        if (isCurrent) setNotice(error.message);
      });
    return () => {
      isCurrent = false;
    };
  }, [selectedWorkoutId, workouts]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { type?: string; owner_app_id?: string; resource?: string; params?: Record<string, unknown>; app_page?: string };
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'fitness-coach') {
        const resource = String(payload.resource || '');
        if (resource !== 'view-state') {
          refresh().catch((error: Error) => setNotice(error.message));
        }
      }
      if (payload.type === 'maverick.app.navigate') {
        const params = payload.params || {};
        const appPage = String(params.app_page || payload.app_page || '');
        const workoutId = appPage.startsWith('workouts/') ? appPage.split('/')[1] : String(params.workout_id || '');
        const setupTabParam = String(params.setup_tab || '');
        if (workoutId) setSelectedWorkoutId(workoutId);
        if (setupTabParam === 'workout-settings' || setupTabParam === 'exercise-library') {
          setLibraryTargetBlockId(null);
          setSetupTab(setupTabParam);
        }
        const pickerSelection = storageMediaSelectionFromPickerParams(params);
        if (pickerSelection) {
          setLibraryTargetBlockId(null);
          setSetupTab('exercise-library');
          setExerciseDraft((current) => ({
            ...(current || EMPTY_EXERCISE),
            media: [pickerSelection.media],
            primary_media: pickerSelection.media,
            source_display_path: pickerSelection.sourceDisplayPath,
            source_folder: pickerSelection.sourceFolder
          }));
          setNotice('');
        }
        if (params.new_exercise) {
          setLibraryTargetBlockId(null);
          setSetupTab('exercise-library');
          setExerciseDraft({ ...EMPTY_EXERCISE });
        }
        if (params.new_workout) {
          setLibraryTargetBlockId(null);
          void handleCreateWorkout();
        }
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [refresh]);

  useEffect(() => {
    if (!selectedWorkout?.id) return;
    const lastSynced = lastSyncedViewStateRef.current;
    if (lastSynced?.selected_workout_id !== selectedWorkout.id || lastSynced?.setup_tab !== setupTab) {
      lastSyncedViewStateRef.current = { selected_workout_id: selectedWorkout.id, setup_tab: setupTab };
      updateViewState({ selected_workout_id: selectedWorkout.id, setup_tab: setupTab }).catch(() => undefined);
    }
    window.parent?.postMessage(
      {
        type: 'maverick.app.selection-changed',
        owner_app_id: 'fitness-coach',
        selection: { workout_id: selectedWorkout.id, app_page: `workouts/${selectedWorkout.id}`, setup_tab: setupTab }
      },
      window.location.origin
    );
  }, [selectedWorkout?.id, setupTab]);

  async function handleCreateWorkout() {
    setBusy('new-workout');
    try {
      const workout = await createWorkout('New workout');
      setWorkouts((items) => [workout, ...items]);
      setSelectedWorkoutId(workout.id);
      setSetupTab('workout-settings');
      setNotice('');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to create workout.');
    } finally {
      setBusy('');
    }
  }

  async function handleSaveWorkout(workout: Workout) {
    setBusy(`save:${workout.id}`);
    try {
      const saved = await saveWorkout(syncWorkoutExerciseSnapshots(workout, exercises) || workout);
      dirtyWorkoutIdsRef.current.delete(workout.id);
      setWorkouts((items) => replaceById(items, saved));
      setSavedWorkoutId(saved.id);
      setNotice('');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to save workout.');
    } finally {
      setBusy('');
    }
  }

  function handleStart() {
    const workoutToStart = syncWorkoutExerciseSnapshots(selectedWorkout, exercises);
    if (!workoutToStart || !validation.valid) return;
    setBusy('start');
    setExercisePlayer(null);
    const startPromise = startWorkout(workoutToStart.id, workoutToStart)
      .then((payload) => {
        dirtyWorkoutIdsRef.current.delete(payload.workout.id);
        setWorkouts((items) => replaceById(items, payload.workout));
        setSavedWorkoutId(payload.workout.id);
        setNotice('');
        return payload;
      })
      .catch((error) => {
        setPlayerSession((current) => current?.workout.id === workoutToStart.id ? null : current);
        setNotice(error instanceof Error ? error.message : 'Workout is not ready.');
        throw error;
      })
      .finally(() => {
        setBusy('');
      });
    void startPromise.catch(() => undefined);
    setPlayerSession({ workout: workoutToStart, startPromise });
  }

  async function handleDeleteWorkout(workout: Workout) {
    if (!window.confirm(`Delete workout "${workout.name}"?`)) return;
    await deleteWorkout(workout.id);
    dirtyWorkoutIdsRef.current.delete(workout.id);
    setWorkouts((items) => items.filter((item) => item.id !== workout.id));
    setSelectedWorkoutId((current) => (current === workout.id ? null : current));
  }

  async function handleDuplicateWorkout(workout: Workout) {
    const copy = await duplicateWorkout(workout.id);
    setWorkouts((items) => [copy, ...items]);
    setSelectedWorkoutId(copy.id);
  }

  async function handleSaveExercise(draft: Partial<Exercise>) {
    setBusy('save-exercise');
    try {
      const prepared = prepareExerciseForSave(draft);
      const saved = prepared.id ? await saveExercise(prepared as Exercise) : await createExercise(prepared);
      setExercises((items) => replaceById(items, saved));
      setExerciseDraft(null);
      setNotice('Exercise saved');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to save exercise.');
    } finally {
      setBusy('');
    }
  }

  async function handleDeleteExercise(exercise: Exercise) {
    setBusy('delete-exercise');
    try {
      await deleteExercise(exercise.id);
      setExercises((items) => items.filter((item) => item.id !== exercise.id));
      setExerciseDraft(null);
      setNotice('Exercise deleted');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to delete exercise.');
    } finally {
      setBusy('');
    }
  }

  async function handleAddExerciseToWorkout(exercise: Exercise) {
    if (!selectedWorkout) {
      setNotice('Create or select a workout first.');
      return;
    }
    const baseWorkout = syncWorkoutExerciseSnapshots(selectedWorkout, exercises) || selectedWorkout;
    const targetBlock = libraryTargetBlockId ? baseWorkout.blocks.find((block) => block.id === libraryTargetBlockId) : null;
    const block = workBlockFromExercise(exercise, baseWorkout, targetBlock || undefined);
    const next = targetBlock
      ? { ...baseWorkout, blocks: baseWorkout.blocks.map((candidate) => (candidate.id === targetBlock.id ? block : candidate)) }
      : { ...baseWorkout, blocks: [...baseWorkout.blocks, block] };
    setWorkouts((items) => replaceById(items, next));
    await handleSaveWorkout(next);
    setLibraryTargetBlockId(null);
    setSetupTab('workout-settings');
  }

  if (playerSession) {
    return <WorkPlayer workout={playerSession.workout} startPromise={playerSession.startPromise} onClose={() => setPlayerSession(null)} onComplete={(run) => setRuns((items) => [run, ...items].slice(0, 20))} />;
  }

  if (exercisePlayer) {
    return <ExercisePlayer exercise={exercisePlayer} onClose={() => setExercisePlayer(null)} />;
  }

  return (
    <main className="fitness-app">
      <section className="fitness-main">
        <section className="setup-panel">
          {notice ? <div className="notice">{notice}</div> : null}

          <div className="setup-content">
            {isInitialLoading ? (
              <FitnessMainSkeleton />
            ) : setupTab === 'workout-settings' ? (
              <WorkoutEditor
                workout={syncedSelectedWorkout}
                exercises={exercises}
                validation={validation}
                busy={busy}
                isDirty={syncedSelectedWorkout ? dirtyWorkoutIdsRef.current.has(syncedSelectedWorkout.id) : false}
                isSaved={Boolean(syncedSelectedWorkout && savedWorkoutId === syncedSelectedWorkout.id && !dirtyWorkoutIdsRef.current.has(syncedSelectedWorkout.id))}
                onChange={markWorkoutDirty}
                onSave={handleSaveWorkout}
                onStart={handleStart}
                onDelete={handleDeleteWorkout}
                onDuplicate={handleDuplicateWorkout}
                onOpenLibraryForBlock={(blockId) => {
                  setLibraryTargetBlockId(blockId);
                  setSetupTab('exercise-library');
                }}
                onOpenExercisePlayer={setExercisePlayer}
              />
            ) : (
              <ExerciseLibrary
                exercises={exercises}
                tags={tags}
                query={libraryQuery}
                tag={libraryTag}
                draft={exerciseDraft}
                busy={busy}
                onQuery={setLibraryQuery}
                onTag={setLibraryTag}
                onDraft={setExerciseDraft}
                onSave={handleSaveExercise}
                onDelete={handleDeleteExercise}
                onAddToWorkout={handleAddExerciseToWorkout}
                onOpenPlayer={setExercisePlayer}
                selectionMode={libraryTargetBlockId ? 'replace' : 'add'}
              />
            )}
          </div>
        </section>
      </section>
    </main>
  );
}

function FitnessMainSkeleton() {
  return (
    <div className="fitness-loading-skeleton fitness-main-skeleton" role="status" aria-label="Fitness Coach is loading">
      <header className="fitness-main-skeleton__header" aria-hidden="true">
        <span className="fitness-loading-skeleton__line fitness-loading-skeleton__line--title" />
        <span className="fitness-main-skeleton__badges">
          <span className="fitness-loading-skeleton__counter" />
          <span className="fitness-loading-skeleton__counter" />
        </span>
      </header>
      <div className="fitness-main-skeleton__separator" aria-hidden="true">
        <span className="fitness-loading-skeleton__icon" />
      </div>
      <div className="fitness-main-skeleton__blocks" aria-hidden="true">
        {Array.from({ length: 3 }).map((_, index) => (
          <article className="fitness-main-skeleton__block" key={index}>
            <span className="fitness-loading-skeleton__media" />
            <span className="fitness-main-skeleton__block-copy">
              <span className="fitness-loading-skeleton__line fitness-loading-skeleton__line--block-title" />
              <span className="fitness-loading-skeleton__line fitness-loading-skeleton__line--block-copy" />
              <span className="fitness-main-skeleton__block-controls">
                <span className="fitness-loading-skeleton__pill" />
                <span className="fitness-loading-skeleton__pill" />
                <span className="fitness-loading-skeleton__button" />
              </span>
            </span>
          </article>
        ))}
      </div>
      <div className="fitness-main-skeleton__actions" aria-hidden="true">
        <span className="fitness-loading-skeleton__button" />
        <span className="fitness-loading-skeleton__button" />
      </div>
    </div>
  );
}

function WorkoutEditor(props: {
  workout: Workout | null;
  exercises: Exercise[];
  validation: ReturnType<typeof validateWorkoutForStart>;
  busy: string;
  isDirty: boolean;
  isSaved: boolean;
  onChange: (workout: Workout) => void;
  onSave: (workout: Workout) => void;
  onStart: () => void;
  onDelete: (workout: Workout) => void;
  onDuplicate: (workout: Workout) => void;
  onOpenLibraryForBlock: (blockId: string) => void;
  onOpenExercisePlayer: (exercise: Exercise) => void;
}) {
  const { workout } = props;
  const [editingTitleId, setEditingTitleId] = useState<string | null>(null);
  const workoutRef = useRef(workout);
  const onChangeRef = useRef(props.onChange);

  useEffect(() => {
    workoutRef.current = workout;
    onChangeRef.current = props.onChange;
  }, [props.onChange, workout]);

  const blockReorder = useWorkoutBlockReorder(workout?.blocks ?? [], updateWorkoutBlocks);

  if (!workout) {
    return <div className="empty-state">Create a workout to begin.</div>;
  }
  const isEditingTitle = editingTitleId === workout.id;
  const summary = workoutSummary(workout);

  function update(patch: Partial<Workout>) {
    props.onChange({ ...workout!, ...patch });
  }

  function updateBlock(blockId: string, patch: Partial<WorkoutBlock>) {
    update({ blocks: workout!.blocks.map((block) => (block.id === blockId ? ({ ...block, ...patch } as WorkoutBlock) : block)) });
  }

  function replaceBlock(blockId: string, nextBlock: WorkoutBlock) {
    update({ blocks: workout!.blocks.map((block) => (block.id === blockId ? nextBlock : block)) });
  }

  function updateWorkoutBlocks(blocks: WorkoutBlock[]) {
    const current = workoutRef.current;
    if (!current) return;
    const nextWorkout = { ...current, blocks };
    workoutRef.current = nextWorkout;
    onChangeRef.current(nextWorkout);
  }

  function addBlock() {
    const block = blankWorkBlock('timer', workout!);
    update({ blocks: [...workout!.blocks, block] });
  }
  const saveState = props.isSaved ? 'saved' : props.isDirty ? 'dirty' : 'clean';
  const isSaving = props.busy === `save:${workout.id}`;
  const saveDisabled = isSaving || !props.isDirty;

  return (
    <div className="editor">
      <div className="workout-header">
        {isEditingTitle ? (
          <input
            className="workout-title-input"
            value={workout.name}
            onBlur={() => setEditingTitleId(null)}
            onChange={(event) => update({ name: event.target.value })}
            onFocus={(event) => event.currentTarget.select()}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === 'Escape') {
                event.currentTarget.blur();
              }
            }}
            aria-label="Workout name"
            autoFocus
          />
        ) : (
          <h1 className="workout-title">{workout.name || 'Untitled workout'}</h1>
        )}
        <div className="workout-title-toolbar">
          <div className="workout-summary-badges" aria-label="Workout summary">
            <span className="workout-summary-badge" title="Workout duration">
              <Timer size={14} aria-hidden="true" />
              <span>{summary.duration}</span>
            </span>
            <span className="workout-summary-badge" title="Total reps">
              <Dumbbell size={14} aria-hidden="true" />
              <span>{summary.reps}</span>
            </span>
          </div>
          <div className="header-actions">
            <button className="icon-button" type="button" onClick={() => setEditingTitleId(workout.id)} title="Edit title" aria-label="Edit workout title">
              <Pencil size={16} aria-hidden="true" />
            </button>
            <button className="icon-button" type="button" onClick={() => props.onDuplicate(workout)} title="Duplicate" aria-label="Duplicate workout">
              <Copy size={16} aria-hidden="true" />
            </button>
            <button className="icon-button danger" type="button" onClick={() => props.onDelete(workout)} title="Delete" aria-label="Delete workout">
              <Trash2 size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      <div className="workout-flow-separator" aria-hidden="true">
        <span>
          <ArrowDown size={16} />
        </span>
      </div>

      <div className={`block-list ${blockReorder.draggingItemId ? 'is-reordering' : ''}`} ref={blockReorder.listRef}>
        <PreparationBlockEditor index={0} />
        {workout.blocks.map((block, index) => (
          <BlockEditor
            block={block}
            exercises={props.exercises}
            key={block.id}
            index={index + 1}
            isDragging={blockReorder.draggingItemId === block.id}
            blockRef={(element) => blockReorder.setItemElement(block.id, element)}
            reorderItemProps={blockReorder.getItemProps(block.id)}
            onChange={(patch) => updateBlock(block.id, patch)}
            onModeChange={(mode) => replaceBlock(block.id, blockWithMode(block, mode, workout))}
            onOpenLibrary={() => props.onOpenLibraryForBlock(block.id)}
            onOpenPlayer={props.onOpenExercisePlayer}
            onDuplicate={() => update({ blocks: insertAfter(workout.blocks, block.id, { ...block, id: crypto.randomUUID() } as WorkoutBlock) })}
            onDelete={() => update({ blocks: workout.blocks.filter((candidate) => candidate.id !== block.id) })}
          />
        ))}
      </div>
      <div className="block-add-row">
        <button className="primary-action block-add-button" type="button" onClick={addBlock}>
          <Plus size={16} aria-hidden="true" />
          <span>Add new block</span>
        </button>
      </div>

      <div className="bottom-action-bar">
        <button className={`secondary-action save-button is-${saveState}`} type="button" onClick={() => props.onSave(workout)} disabled={saveDisabled}>
          {props.isSaved ? <Check size={16} aria-hidden="true" /> : <Save size={16} aria-hidden="true" />}
          <span>{props.isSaved ? 'Saved' : 'Save'}</span>
        </button>
        <button className="start-button" type="button" onClick={props.onStart} disabled={!props.validation.valid || props.busy === 'start'}>
          <Play size={16} aria-hidden="true" />
          <span>Start</span>
        </button>
      </div>
    </div>
  );
}

function PreparationBlockEditor({ index }: { index: number }) {
  return (
    <article className="block-editor is-rest is-preparation" aria-label={`Preparation block, ${PREPARATION_BLOCK_SECONDS} seconds`}>
      <div className="rest-block-layout">
        <div className="mode-value-row is-rest is-preparation">
          <span className="block-index">{index + 1}</span>
          <span className="rest-block-icon-frame" aria-hidden="true">
            <RestIconImage className="rest-block-icon" />
          </span>
          <span className="preparation-block-title">Preparation</span>
          <span className="preparation-block-duration">{PREPARATION_BLOCK_SECONDS} seconds</span>
        </div>
      </div>
    </article>
  );
}

function BlockEditor(props: {
  block: WorkoutBlock;
  exercises: Exercise[];
  index: number;
  isDragging: boolean;
  blockRef: (element: HTMLElement | null) => void;
  reorderItemProps: ReorderItemProps;
  onChange: (patch: Partial<WorkoutBlock>) => void;
  onModeChange: (mode: WorkoutBlockMode) => void;
  onOpenLibrary: () => void;
  onOpenPlayer: (exercise: Exercise) => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const { block } = props;
  const mode: WorkoutBlockMode = block.type === 'rest' ? 'rest' : block.mode;
  const exercise = block.type === 'work' && block.exercise_id ? props.exercises.find((item) => item.id === block.exercise_id) || null : null;
  const hasExercise = block.type === 'work' && Boolean(block.exercise_id);
  const title = block.type === 'work'
    ? hasExercise
      ? exercise?.title || block.title || 'Exercise unavailable'
      : 'No exercise selected'
    : '';
  const media = block.type === 'work' ? exercise?.primary_media || block.media : null;
  const description = block.type === 'work'
    ? hasExercise
      ? exerciseDescriptionPreview(exercise || block) || 'No description'
      : 'Choose an exercise from the library.'
    : '';
  const playerExercise = block.type === 'work' ? exerciseForPlayerFromBlock(block, exercise) : null;
  const controls = (
    <div className={`mode-value-row ${block.type === 'rest' ? 'is-rest' : ''}`}>
      {block.type === 'rest' ? (
        <>
          <span className="block-index">{props.index + 1}</span>
          <span className="rest-block-icon-frame" aria-hidden="true">
            <RestIconImage className="rest-block-icon" />
          </span>
        </>
      ) : null}
      <select className="block-mode-select" value={mode} onChange={(event) => props.onModeChange(event.target.value as WorkoutBlockMode)} aria-label="Block mode">
        <option value="timer">Timer</option>
        <option value="reps">Reps</option>
        <option value="rest">Rest</option>
      </select>
      {block.type === 'work' && block.mode === 'reps' ? (
        <NumberField label="Reps" value={block.reps || 0} onChange={(reps) => props.onChange({ reps, reps_label: null } as Partial<WorkoutBlock>)} />
      ) : (
        <NumberField label={block.type === 'rest' ? 'Rest seconds' : 'Seconds'} value={block.type === 'rest' ? block.seconds : block.seconds || 0} onChange={(seconds) => props.onChange({ seconds } as Partial<WorkoutBlock>)} />
      )}
      <div className="block-actions">
        <button className="mini-icon" type="button" onClick={props.onDuplicate} aria-label="Duplicate block" title="Duplicate"><Copy size={14} /></button>
        <button className="mini-icon danger" type="button" onClick={props.onDelete} aria-label="Delete block" title="Delete"><Trash2 size={14} /></button>
      </div>
    </div>
  );

  return (
    <article ref={props.blockRef} className={`block-editor ${block.type === 'work' ? 'is-work' : 'is-rest'} ${props.isDragging ? 'is-dragging' : ''}`} {...props.reorderItemProps}>
      {block.type === 'work' ? (
        <div className="block-work-layout">
          <button
            className="block-media-panel block-exercise-player-trigger"
            type="button"
            onClick={() => playerExercise ? props.onOpenPlayer(playerExercise) : undefined}
            disabled={!playerExercise}
            aria-label={playerExercise ? `Open ${title} player` : 'No playable exercise'}
          >
            <MediaThumb media={media} />
            <span className="block-index block-index-overlay">{props.index + 1}</span>
          </button>
          <div className="block-work-content">
            <div className="block-work-header">
              <div className="block-exercise-copy">
                <strong>{title}</strong>
                <span>{description}</span>
              </div>
              <div className="block-control-row">
                <button className="secondary-action compact block-change-button" type="button" onClick={props.onOpenLibrary}>
                  <Library size={15} aria-hidden="true" />
                  <span>{hasExercise ? 'Change' : 'Choose'}</span>
                </button>
              </div>
            </div>
            {controls}
          </div>
        </div>
      ) : (
        <div className="rest-block-layout">
          {controls}
        </div>
      )}
    </article>
  );
}

function ExerciseLibrary(props: {
  exercises: Exercise[];
  tags: string[];
  query: string;
  tag: string;
  draft: Partial<Exercise> | null;
  busy: string;
  onQuery: (value: string) => void;
  onTag: (value: string) => void;
  onDraft: (value: Partial<Exercise> | null) => void;
  onSave: (exercise: Partial<Exercise>) => void;
  onDelete: (exercise: Exercise) => void;
  onAddToWorkout: (exercise: Exercise) => void;
  onOpenPlayer: (exercise: Exercise) => void;
  selectionMode: 'add' | 'replace';
}) {
  const filtered = props.exercises.filter((exercise) => {
    const query = props.query.trim().toLowerCase();
    const tagOk = !props.tag || exercise.tags.includes(props.tag);
    const queryOk = !query || [exercise.title, exercise.short_description, exercise.long_description, exercise.tags.join(' ')].join(' ').toLowerCase().includes(query);
    return tagOk && queryOk;
  });
  const editingExerciseId = props.draft?.id || '';
  const visibleExercises = editingExerciseId ? filtered.filter((exercise) => exercise.id !== editingExerciseId) : filtered;
  return (
    <div className="library">
      <div className="library-toolbar">
        <label className="fitness-search compact">
          <Search size={15} aria-hidden="true" />
          <input value={props.query} onChange={(event) => props.onQuery(event.target.value)} placeholder="Search exercise" />
        </label>
        <select value={props.tag} onChange={(event) => props.onTag(event.target.value)} aria-label="Filter tag">
          <option value="">All tags</option>
          {props.tags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
        </select>
        <button className="primary-action inline" type="button" onClick={() => props.onDraft({ ...EMPTY_EXERCISE })}>
          <Plus size={16} aria-hidden="true" />
          <span>New exercise</span>
        </button>
      </div>

      {props.draft ? (
        <ExerciseEditor draft={props.draft} busy={props.busy} onDraft={props.onDraft} onSave={props.onSave} />
      ) : null}

      <div className="exercise-grid">
        {visibleExercises.map((exercise) => (
          <article key={exercise.id} className="exercise-row">
            <button className="exercise-preview-button" type="button" onClick={() => props.onOpenPlayer(exercise)} aria-label={`Open ${exercise.title || 'exercise'} player`}>
              <MediaThumb media={exercise.primary_media} />
            </button>
            <div className="exercise-main">
              <strong>{exercise.title}</strong>
              <span>{exerciseDescriptionPreview(exercise) || 'No description'}</span>
              <small>{exercise.tags.join(' · ') || 'No tags'}</small>
            </div>
            <div className="exercise-actions">
              <button type="button" onClick={() => props.onAddToWorkout(exercise)}>
                {props.selectionMode === 'replace' ? <Check size={15} aria-hidden="true" /> : <Plus size={15} aria-hidden="true" />}
                <span>{props.selectionMode === 'replace' ? 'Select' : 'Add'}</span>
              </button>
              <button type="button" onClick={() => props.onDraft(exercise)}>
                <Pencil size={15} aria-hidden="true" />
                <span>Edit</span>
              </button>
              <button className="icon-button danger" type="button" onClick={() => props.onDelete(exercise)} disabled={props.busy === 'delete-exercise'} aria-label="Delete exercise" title="Delete"><Trash2 size={15} /></button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function ExerciseEditor(props: {
  draft: Partial<Exercise>;
  busy: string;
  onDraft: (value: Partial<Exercise> | null) => void;
  onSave: (exercise: Partial<Exercise>) => void;
}) {
  const draft = props.draft;
  const update = (patch: Partial<Exercise>) => props.onDraft({ ...draft, ...patch });
  const description = exerciseDescriptionValue(draft);
  const preparedDraft = useMemo(() => prepareExerciseForSave(draft), [draft]);
  const draftSignature = useMemo(() => exerciseDraftSignature(preparedDraft), [preparedDraft]);
  const draftKey = draft.id || 'new-exercise';
  const baselineRef = useRef({ key: draftKey, signature: draftSignature });
  if (baselineRef.current.key !== draftKey) {
    baselineRef.current = { key: draftKey, signature: draftSignature };
  }
  const hasChanges = draftSignature !== baselineRef.current.signature;
  const canSave = Boolean((draft.title || '').trim() && description.trim());
  const saveDisabled = props.busy === 'save-exercise' || !canSave || !hasChanges;
  return (
    <section className="exercise-editor">
      <div className="exercise-editor-grid">
        <div className="exercise-media-column">
          <MediaPicker
            media={draft.primary_media || null}
            sourceFolder={draft.source_folder || null}
            onChange={(selection) => update({
              primary_media: selection?.media || null,
              media: selection?.media ? [selection.media] : [],
              source_display_path: selection?.sourceDisplayPath || null,
              source_folder: selection?.sourceFolder || null
            })}
          />
        </div>
        <div className="exercise-details-column">
          <div className="exercise-editor-heading">
            <label className="field-label">
              <span>Exercise title</span>
              <input value={draft.title || ''} onChange={(event) => update({ title: event.target.value })} placeholder="Exercise title" />
            </label>
          </div>
          <label className="field-label">
            <span>Description</span>
            <textarea
              value={description}
              onChange={(event) => update({ long_description: event.target.value })}
              placeholder="Explain how to perform the exercise, including setup, movement and cues."
            />
          </label>
          <TagsInputField
            label="Tags"
            value={draft.tags || []}
            onValueChange={(value) => update({ tags: value })}
            placeholder="mobility, shoulders, core"
          />
          <div className="editor-actions exercise-editor-actions">
            <button className={`secondary-action exercise-save-action ${hasChanges ? 'is-dirty' : 'is-clean'}`} type="button" onClick={() => props.onSave(draft)} disabled={saveDisabled}>
              <Check size={16} aria-hidden="true" />
              <span>Save exercise</span>
            </button>
            <button className="secondary-action exercise-close-action" type="button" onClick={() => props.onDraft(null)}>
              <X size={16} aria-hidden="true" />
              <span>Close</span>
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

function MediaPicker({ media, sourceFolder, onChange }: {
  media: ExerciseMediaRef | null;
  sourceFolder: Exercise['source_folder'];
  onChange: (selection: { media: ExerciseMediaRef; sourceDisplayPath: string | null; sourceFolder: Exercise['source_folder'] } | null) => void;
}) {
  const storageButtonLabel = media ? 'Change video' : 'Select video';
  return (
    <div className="media-picker">
      <div className="media-cover-panel">
        <MediaThumb media={media} variant="large" />
        <div className="media-current-copy">
          <strong>{media?.name || 'No media selected'}</strong>
          <span>{media?.display_path || 'Select a video from Storage.'}</span>
        </div>
      </div>
      <div className="media-actions">
        <button
          className={`media-select-action ${media ? 'is-selected' : 'is-empty'}`}
          type="button"
          onClick={() => openStorageVideoPicker(media, sourceFolder)}
        >
          <Library size={15} aria-hidden="true" />
          <span>{storageButtonLabel}</span>
        </button>
      </div>
    </div>
  );
}

function ExercisePlayer({ exercise, onClose }: { exercise: Exercise; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [paused, setPaused] = useState(false);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [playbackOverlay, setPlaybackOverlay] = useState<PlayerPlaybackOverlay>('idle');
  const [resolution, setResolution] = useState(initialMediaResolution());
  const [resolutionKey, setResolutionKey] = useState('');
  const [loadedMediaUrls, setLoadedMediaUrls] = useState<Set<string>>(() => new Set());
  const [retryNonce, setRetryNonce] = useState(0);
  const playbackOverlayTimerRef = useRef<number | null>(null);
  const media = exercise.primary_media || exercise.media[0] || null;
  const mediaKey = media ? mediaCacheKey(media) : '';
  const currentResolution = mediaKey && resolutionKey === mediaKey ? resolution : media ? cachedMediaPlayback(media) || initialMediaResolution() : initialMediaResolution();
  const currentMediaLoaded = currentResolution.status === 'ready' && Boolean(currentResolution.url) && loadedMediaUrls.has(currentResolution.url);
  const hasCurrentMediaLayer = currentResolution.status === 'ready'
    && Boolean(currentResolution.url)
    && (currentResolution.mediaKind === 'video' || currentResolution.mediaKind === 'image');
  const isPlayableVideo = hasCurrentMediaLayer && currentResolution.mediaKind === 'video';
  const fullDescription = exercise.long_description || exercise.short_description || '';
  const visibleDescription = descriptionExpanded && fullDescription ? fullDescription : exercise.short_description || exercise.long_description || '';
  const mediaPlaceholderLabel = currentResolution.status === 'blocked'
    ? currentResolution.detail
    : currentResolution.status === 'error'
      ? 'Exercise media could not be loaded'
      : currentResolution.status === 'localizing'
        ? 'Storage is preparing exercise media'
        : media
          ? 'Loading exercise media'
          : 'This exercise has no playable media';

  const clearPlaybackOverlayTimer = useCallback(() => {
    if (playbackOverlayTimerRef.current === null) return;
    window.clearTimeout(playbackOverlayTimerRef.current);
    playbackOverlayTimerRef.current = null;
  }, []);

  const showPlaybackOverlay = useCallback((mode: PlayerPlaybackOverlay) => {
    clearPlaybackOverlayTimer();
    setPlaybackOverlay(mode);
    if (mode === 'pause') {
      playbackOverlayTimerRef.current = window.setTimeout(() => {
        setPlaybackOverlay('idle');
        playbackOverlayTimerRef.current = null;
      }, 700);
    }
  }, [clearPlaybackOverlayTimer]);

  const markMediaLoaded = useCallback((url: string) => {
    if (!url) return;
    setLoadedMediaUrls((current) => {
      if (current.has(url)) return current;
      const next = new Set(current);
      next.add(url);
      return next;
    });
  }, []);

  const markVideoFrameLoaded = useCallback((video: HTMLVideoElement, url: string) => {
    if (!url) return;
    const requestFrame = (video as HTMLVideoElement & { requestVideoFrameCallback?: (callback: () => void) => number }).requestVideoFrameCallback;
    if (typeof requestFrame === 'function') {
      requestFrame.call(video, () => markMediaLoaded(url));
      window.setTimeout(() => {
        if (video.readyState >= 2) markMediaLoaded(url);
      }, 120);
      return;
    }
    if (video.readyState >= 2) markMediaLoaded(url);
  }, [markMediaLoaded]);

  useEffect(() => () => clearMediaPlaybackCache(), []);

  useEffect(() => clearPlaybackOverlayTimer, [clearPlaybackOverlayTimer]);

  useEffect(() => {
    if (media) retainMediaPlayback([media]);
  }, [media]);

  useEffect(() => {
    setLoadedMediaUrls(new Set());
    setDescriptionExpanded(false);
    setPaused(false);
    setPlaybackOverlay('idle');
  }, [mediaKey]);

  useEffect(() => {
    if (!media) {
      setResolutionKey('');
      setResolution({ status: 'blocked', url: '', mediaKind: 'none', detail: 'This exercise has no playable Storage media.' });
      return;
    }
    const key = mediaCacheKey(media);
    setResolutionKey(key);
    setResolution(cachedMediaPlayback(media) || initialMediaResolution());
    let canceled = false;
    resolveMediaPlayback(media).then((next) => {
      if (!canceled) {
        setResolutionKey(key);
        setResolution(next);
      }
    });
    return () => {
      canceled = true;
    };
  }, [media, mediaKey, retryNonce]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || currentResolution.status !== 'ready' || currentResolution.mediaKind !== 'video' || !currentResolution.url) return;
    if (video.readyState >= 2) {
      markMediaLoaded(currentResolution.url);
    } else {
      video.load();
    }
    if (paused) {
      video.pause();
      return;
    }
    const playPromise = video.play();
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise.catch((error: Error) => {
        if (error.name === 'AbortError') return;
        setPaused(true);
        showPlaybackOverlay('play');
      });
    }
  }, [currentMediaLoaded, currentResolution.mediaKind, currentResolution.status, currentResolution.url, markMediaLoaded, paused, showPlaybackOverlay]);

  function togglePlayback() {
    if (!isPlayableVideo) return;
    setPaused((current) => {
      const next = !current;
      showPlaybackOverlay(next ? 'play' : 'pause');
      return next;
    });
  }

  async function fallbackMedia() {
    if (!media) return;
    setResolution(await playerFallbackResolution(media, currentResolution));
  }

  return (
    <main className={`work-player exercise-player ${isPlayableVideo ? 'is-video' : ''}`}>
      <div className="player-media" onClick={togglePlayback}>
        {!hasCurrentMediaLayer ? (
          <GradientBarsBackground
            className={`player-media-backdrop is-${currentResolution.status}`}
            numBars={9}
            gradientFrom="rgba(224, 228, 230, 0.78)"
            gradientTo="rgba(5, 6, 5, 0)"
            animationDuration={2.2}
            backgroundColor="#050605"
            ariaLabel={mediaPlaceholderLabel}
          >
            {(currentResolution.status === 'blocked' || currentResolution.status === 'error') && currentResolution.detail ? <span className="player-media-backdrop-message">{currentResolution.detail}</span> : null}
          </GradientBarsBackground>
        ) : null}
        {hasCurrentMediaLayer && !currentMediaLoaded ? (
          <GradientBarsBackground
            className="player-media-backdrop is-frame-wait"
            numBars={9}
            gradientFrom="rgba(224, 228, 230, 0.78)"
            gradientTo="rgba(5, 6, 5, 0)"
            animationDuration={2.2}
            backgroundColor="#050605"
            ariaLabel="Loading exercise media"
          />
        ) : null}
        {hasCurrentMediaLayer ? (
          <PlayerMediaLayer
            key={currentResolution.url}
            resolution={currentResolution}
            mediaKey={mediaKey}
            role="current"
            isLoaded={currentMediaLoaded}
            paused={paused}
            videoRef={videoRef}
            onLoaded={markMediaLoaded}
            onVideoFrameLoaded={markVideoFrameLoaded}
            onError={fallbackMedia}
          />
        ) : null}
      </div>
      <div className="player-scrim" />
      {isPlayableVideo ? (
        <button
          className={`player-playback-control is-${playbackOverlay === 'idle' ? 'idle' : `showing-${playbackOverlay}`}`}
          type="button"
          onClick={togglePlayback}
          aria-label={paused ? 'Resume exercise' : 'Pause exercise'}
          title={paused ? 'Resume' : 'Pause'}
          tabIndex={playbackOverlay === 'idle' ? -1 : 0}
        >
          <Play className="player-playback-icon player-playback-icon-play" size={64} aria-hidden="true" />
          <Pause className="player-playback-icon player-playback-icon-pause" size={64} aria-hidden="true" />
        </button>
      ) : null}
      <div className={`player-header exercise-player-header ${descriptionExpanded ? 'is-expanded' : ''}`}>
        <div className="player-top">
          <div className="player-heading">
            <strong>{exercise.title || 'Untitled exercise'}</strong>
            {fullDescription ? (
              <button
                className={`player-description ${descriptionExpanded ? 'is-open' : ''}`}
                type="button"
                onClick={() => setDescriptionExpanded((value) => !value)}
                aria-expanded={descriptionExpanded}
                aria-label={descriptionExpanded ? 'Collapse description' : 'Expand description'}
              >
                <span>{visibleDescription}</span>
              </button>
            ) : null}
          </div>
          <div className="player-control-stack">
            <button className="player-icon player-close" type="button" onClick={onClose} aria-label="Close player"><X size={20} /></button>
          </div>
        </div>
      </div>
      {currentResolution.status === 'error' && media ? (
        <div className="player-error">
          <span>{currentResolution.detail}</span>
          {currentResolution.canRetry ? (
            <button type="button" onClick={() => setRetryNonce((value) => value + 1)}>
              <RotateCcw size={14} aria-hidden="true" />
              <span>Retry</span>
            </button>
          ) : null}
        </div>
      ) : null}
    </main>
  );
}

function WorkPlayer({ workout, startPromise, onClose, onComplete }: { workout: Workout; startPromise: Promise<StartWorkoutPayload>; onClose: () => void; onComplete: (run: WorkoutRunSummary) => void }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const startPromiseRef = useRef(startPromise);
  const segments = useMemo(() => runtimeSegmentsForWorkout(workout), [workout]);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [remaining, setRemaining] = useState(segments[0]?.type === 'work' && segments[0].mode === 'reps' ? 0 : segments[0]?.seconds || 0);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [playbackOverlay, setPlaybackOverlay] = useState<PlayerPlaybackOverlay>('idle');
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [resolution, setResolution] = useState(initialMediaResolution());
  const [resolutionKey, setResolutionKey] = useState('');
  const [nextPreviewResolution, setNextPreviewResolution] = useState(initialMediaResolution());
  const [nextPreviewResolutionKey, setNextPreviewResolutionKey] = useState('');
  const [loadedMediaUrls, setLoadedMediaUrls] = useState<Set<string>>(() => new Set());
  const [summary, setSummary] = useState<WorkoutRunSummary | null>(null);
  const [startedAt] = useState(new Date().toISOString());
  const [skipped, setSkipped] = useState(0);
  const [retryNonce, setRetryNonce] = useState(0);
  const [isFinishing, setIsFinishing] = useState(false);
  const [finishError, setFinishError] = useState('');
  const timerRemainingMsRef = useRef(0);
  const timerStartedAtRef = useRef(0);
  const countdownPlayedRef = useRef(false);
  const countdownAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const playbackOverlayTimerRef = useRef<number | null>(null);
  const pointerStartRef = useRef<{ x: number; y: number } | null>(null);
  const finishInFlightRef = useRef(false);
  const segment = segments[index];
  const nextPreviewCandidate = nextWorkSegment(segments, index);
  const activeWorkMediaKey = segment?.type === 'work' ? mediaCacheKey(segment.media) : '';
  const nextPreviewMediaKey = nextPreviewCandidate ? mediaCacheKey(nextPreviewCandidate.media) : '';
  const warmupMediaList = useMemo(() => workMediaWarmupWindow(segments, index), [segments, index]);
  const warmupMediaWindowKey = useMemo(() => warmupMediaList.map((media) => mediaCacheKey(media)).join('|'), [warmupMediaList]);

  const clearPlaybackOverlayTimer = useCallback(() => {
    if (playbackOverlayTimerRef.current === null) return;
    window.clearTimeout(playbackOverlayTimerRef.current);
    playbackOverlayTimerRef.current = null;
  }, []);

  const showPlaybackOverlay = useCallback((mode: PlayerPlaybackOverlay) => {
    clearPlaybackOverlayTimer();
    setPlaybackOverlay(mode);
    if (mode === 'pause') {
      playbackOverlayTimerRef.current = window.setTimeout(() => {
        setPlaybackOverlay('idle');
        playbackOverlayTimerRef.current = null;
      }, 700);
    }
  }, [clearPlaybackOverlayTimer]);

  const markMediaLoaded = useCallback((url: string) => {
    if (!url) return;
    setLoadedMediaUrls((current) => {
      if (current.has(url)) return current;
      const next = new Set(current);
      next.add(url);
      return next;
    });
  }, []);

  const markVideoFrameLoaded = useCallback((video: HTMLVideoElement, url: string) => {
    if (!url) return;
    const requestFrame = (video as HTMLVideoElement & { requestVideoFrameCallback?: (callback: () => void) => number }).requestVideoFrameCallback;
    if (typeof requestFrame === 'function') {
      requestFrame.call(video, () => markMediaLoaded(url));
      window.setTimeout(() => {
        if (video.readyState >= 2) markMediaLoaded(url);
      }, 120);
      return;
    }
    if (video.readyState >= 2) markMediaLoaded(url);
  }, [markMediaLoaded]);

  const applyWarmupResolution = useCallback((key: string, next: MediaPlaybackResolution) => {
    if (activeWorkMediaKey && key === activeWorkMediaKey) {
      setResolutionKey(key);
      setResolution(next);
    }
    if (nextPreviewMediaKey && key === nextPreviewMediaKey) {
      setNextPreviewResolutionKey(key);
      setNextPreviewResolution(next);
    }
  }, [activeWorkMediaKey, nextPreviewMediaKey]);

  const currentResolution = activeWorkMediaKey && resolutionKey === activeWorkMediaKey
    ? resolution
    : segment?.type === 'work'
      ? cachedMediaPlayback(segment.media) || initialMediaResolution()
      : initialMediaResolution();
  const nextPreviewResolved = nextPreviewMediaKey && nextPreviewResolutionKey === nextPreviewMediaKey
    ? nextPreviewResolution
    : nextPreviewCandidate
      ? cachedMediaPlayback(nextPreviewCandidate.media) || initialMediaResolution()
      : initialMediaResolution();
  const currentMediaLoaded = currentResolution.status === 'ready' && Boolean(currentResolution.url) && loadedMediaUrls.has(currentResolution.url);
  const nextPreviewMediaLoaded = nextPreviewResolved.status === 'ready' && Boolean(nextPreviewResolved.url) && loadedMediaUrls.has(nextPreviewResolved.url);

  useEffect(() => {
    rootRef.current?.requestFullscreen?.().catch(() => undefined);
  }, []);

  useEffect(() => {
    startPromiseRef.current = startPromise;
  }, [startPromise]);

  useEffect(() => () => clearMediaPlaybackCache(), []);

  useEffect(() => {
    const audio = new Audio(COUNTDOWN_SOUND_SRC);
    audio.preload = 'auto';
    countdownAudioRef.current = audio;
    return () => {
      audio.pause();
      countdownAudioRef.current = null;
    };
  }, []);

  useEffect(() => () => {
    audioContextRef.current?.close().catch(() => undefined);
    audioContextRef.current = null;
  }, []);

  useEffect(() => clearPlaybackOverlayTimer, [clearPlaybackOverlayTimer]);

  useEffect(() => {
    clearPlaybackOverlayTimer();
    setPlaybackOverlay(paused ? 'play' : 'idle');
    setDescriptionExpanded(false);
  }, [clearPlaybackOverlayTimer, index]);

  useEffect(() => {
    retainMediaPlayback(warmupMediaList);
  }, [warmupMediaList, warmupMediaWindowKey]);

  useEffect(() => {
    if (!segment || segment.type !== 'work') {
      setResolutionKey('');
      setResolution(initialMediaResolution());
      return;
    }
    const key = mediaCacheKey(segment.media);
    setResolutionKey(key);
    setResolution(cachedMediaPlayback(segment.media) || initialMediaResolution());
    let canceled = false;
    resolveMediaPlayback(segment.media).then((next) => {
      if (!canceled) {
        setResolutionKey(key);
        setResolution(next);
      }
    });
    return () => {
      canceled = true;
    };
  }, [activeWorkMediaKey, retryNonce, segment]);

  useEffect(() => {
    if (!nextPreviewCandidate) {
      setNextPreviewResolutionKey('');
      setNextPreviewResolution(initialMediaResolution());
      return;
    }
    const key = mediaCacheKey(nextPreviewCandidate.media);
    setNextPreviewResolutionKey(key);
    setNextPreviewResolution(cachedMediaPlayback(nextPreviewCandidate.media) || initialMediaResolution());
  }, [nextPreviewCandidate, nextPreviewMediaKey, retryNonce]);

  useEffect(() => {
    if (warmupMediaList.length === 0) return;
    let canceled = false;

    async function warmSequentially() {
      for (const media of warmupMediaList) {
        if (canceled) return;
        const key = mediaCacheKey(media);
        const cached = cachedMediaPlayback(media);
        if (cached) applyWarmupResolution(key, cached);

        const resolved = await resolveMediaPlayback(media);
        if (canceled) return;
        applyWarmupResolution(key, resolved);

        const preloaded = await preloadMediaPlayback(media);
        if (canceled) return;
        applyWarmupResolution(key, preloaded);
        if (preloaded.status === 'ready' && preloaded.url) {
          markMediaLoaded(preloaded.url);
        }
      }
    }

    void warmSequentially();
    return () => {
      canceled = true;
    };
  }, [applyWarmupResolution, markMediaLoaded, retryNonce, warmupMediaList, warmupMediaWindowKey]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || currentResolution.status !== 'ready' || currentResolution.mediaKind !== 'video' || !currentResolution.url) return;
    if (video.readyState >= 2) {
      markMediaLoaded(currentResolution.url);
    } else {
      video.load();
    }
    if (paused) {
      video.pause();
      return;
    }
    const playPromise = video.play();
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise.catch((error: Error) => {
        if (error.name === 'AbortError') return;
        setPaused(true);
        showPlaybackOverlay('play');
      });
    }
  }, [currentMediaLoaded, currentResolution.mediaKind, currentResolution.status, currentResolution.url, markMediaLoaded, paused, showPlaybackOverlay]);

  useEffect(() => {
    if (!segment || segment.type === 'work' && segment.mode === 'reps') {
      setRemaining(0);
      timerRemainingMsRef.current = 0;
      return;
    }
    const durationSeconds = segment.seconds || 0;
    setRemaining(durationSeconds);
    timerRemainingMsRef.current = durationSeconds * 1000;
    countdownPlayedRef.current = false;
  }, [index, segment]);

  useEffect(() => {
    if (!segment || paused || segment.type === 'work' && segment.mode === 'reps') return;
    timerStartedAtRef.current = performance.now();
    let completed = false;
    const timer = window.setInterval(() => {
      const elapsed = performance.now() - timerStartedAtRef.current;
      const remainingMs = Math.max(0, timerRemainingMsRef.current - elapsed);
      const next = Math.max(0, Math.ceil(remainingMs / 1000));
      setRemaining(next);
      if (audioEnabled && remainingMs <= COUNTDOWN_SOUND_LEAD_MS && remainingMs > 0 && !countdownPlayedRef.current) {
        countdownPlayedRef.current = true;
        playCountdownSound(countdownAudioRef.current);
      }
      if (next === 0) {
        if (audioEnabled) playTone(820, 0.16, audioContextRef.current);
        completed = true;
        window.clearInterval(timer);
        advance();
      }
    }, 160);
    return () => {
      window.clearInterval(timer);
      if (!completed) {
        timerRemainingMsRef.current = Math.max(0, timerRemainingMsRef.current - (performance.now() - timerStartedAtRef.current));
      }
    };
  }, [audioEnabled, index, paused, segment]);

  useEffect(() => {
    function onVisibility() {
      if (document.hidden) {
        setPaused(true);
        showPlaybackOverlay('play');
      }
    }
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, [showPlaybackOverlay]);

  async function finish() {
    if (finishInFlightRef.current) return;
    finishInFlightRef.current = true;
    setIsFinishing(true);
    setFinishError('');
    try {
      const run = await completeWorkoutAfterConfirmedStart({
        startPromise: startPromiseRef.current,
        completeWorkout,
        workoutId: workout.id,
        startedAt,
        completedSegments: segments.length,
        skippedSegments: skipped,
        exerciseCount: segments.filter((item) => item.type === 'work').length
      });
      setSummary(run);
      onComplete(run);
    } catch (error) {
      setPaused(true);
      showPlaybackOverlay('play');
      setFinishError(error instanceof Error ? error.message : 'Unable to save workout completion.');
    } finally {
      finishInFlightRef.current = false;
      setIsFinishing(false);
    }
  }

  function advance(skip = false) {
    if (skip) setSkipped((count) => count + 1);
    if (index >= segments.length - 1) {
      void finish();
      return;
    }
    setIndex((value) => value + 1);
  }

  function previous() {
    setIndex((value) => Math.max(0, value - 1));
  }

  function togglePlayback() {
    setPaused((current) => {
      const next = !current;
      showPlaybackOverlay(next ? 'play' : 'pause');
      return next;
    });
  }

  async function enableAudio() {
    const unlocked = await unlockWorkoutAudio(countdownAudioRef.current, audioContextRef);
    setAudioEnabled(unlocked);
  }

  function toggleAudio() {
    if (audioEnabled) {
      setAudioEnabled(false);
      disableWorkoutAudio(countdownAudioRef.current, audioContextRef);
      return;
    }
    void enableAudio();
  }

  function handlePointerUp(event: ReactPointerEvent) {
    const start = pointerStartRef.current;
    pointerStartRef.current = null;
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (Math.abs(dx) < 42 || Math.abs(dx) < Math.abs(dy)) return;
    if (dx < 0) advance(segment?.type !== 'work' || segment.mode !== 'reps');
    if (dx > 0) previous();
  }

  async function fallbackBlob() {
    if (!segment || segment.type !== 'work') return;
    setResolution(await playerFallbackResolution(segment.media, currentResolution));
  }

  if (summary) {
    return (
      <main className="work-player summary">
        <section className="summary-panel">
          <h1>Workout complete</h1>
          <p>{summary.exercise_count} exercises · {formatDuration(summary.elapsed_seconds)} · {summary.skipped_segments} skipped</p>
          <div className="summary-actions">
            <button type="button" onClick={() => { setSummary(null); setIndex(0); }}>
              <RotateCcw size={15} aria-hidden="true" />
              <span>Repeat</span>
            </button>
            <button type="button" onClick={onClose}>
              <Pencil size={15} aria-hidden="true" />
              <span>Edit workout</span>
            </button>
            <button type="button" onClick={onClose}>
              <X size={15} aria-hidden="true" />
              <span>Close</span>
            </button>
          </div>
        </section>
      </main>
    );
  }

  if (!segment) {
    return (
      <main className="work-player">
        <button className="secondary-action" type="button" onClick={onClose}>
          <X size={15} aria-hidden="true" />
          <span>Close</span>
        </button>
      </main>
    );
  }

  const isReps = segment.type === 'work' && segment.mode === 'reps';
  const shouldShowNextPreview = Boolean(nextPreviewCandidate) && (
    segment.type === 'rest'
      ? segment.showNextExercise
      : segment.mode === 'timer' && remaining <= 5 && remaining > 0
  );
  const nextSegmentPreview = shouldShowNextPreview ? nextPreviewCandidate : null;
  const nextPreviewDescription = nextSegmentPreview?.short_description || nextSegmentPreview?.long_description || '';
  const segmentModeLabel = segment.type === 'rest' ? (segment.phase === 'preparation' ? 'Preparation' : 'Rest') : isReps ? 'Reps' : 'Timer';
  const counter = isReps ? formatRepsCounter(segment.reps, segment.repsLabel) : formatClock(remaining);
  const segmentDescription = segment.short_description || segment.long_description || '';
  const fullDescription = segment.long_description || segment.short_description || '';
  const visibleDescription = descriptionExpanded && fullDescription ? fullDescription : segmentDescription;
  const audioToggleLabel = audioEnabled ? 'Turn workout audio off' : 'Turn workout audio on';
  const progressSeconds = Math.max(0.01, segmentProgressSeconds(segment));
  const progressRepeats = segmentProgressRepeats(segment);
  const progressFillStyle = {
    '--fitness-player-progress-duration': `${progressSeconds}s`,
    animationPlayState: paused ? 'paused' : 'running'
  } as CSSProperties;
  const mediaPlaceholderLabel = currentResolution.status === 'blocked'
    ? currentResolution.detail
    : currentResolution.status === 'error'
      ? 'Workout media could not be loaded'
      : currentResolution.status === 'localizing'
        ? 'Storage is preparing workout media'
        : 'Loading workout media';
  const hasCurrentMediaLayer = segment.type === 'work'
    && currentResolution.status === 'ready'
    && Boolean(currentResolution.url)
    && (currentResolution.mediaKind === 'video' || currentResolution.mediaKind === 'image');
  const hasNextPreloadLayer = nextPreviewResolved.status === 'ready'
    && Boolean(nextPreviewResolved.url)
    && (nextPreviewResolved.mediaKind === 'video' || nextPreviewResolved.mediaKind === 'image')
    && nextPreviewResolved.url !== currentResolution.url;
  return (
    <main
      className="work-player"
      ref={rootRef}
      onPointerDown={(event) => { pointerStartRef.current = { x: event.clientX, y: event.clientY }; }}
      onPointerUp={handlePointerUp}
    >
      <div className="player-media" onClick={togglePlayback}>
        {segment.type === 'rest' ? (
          <GradientBarsBackground
            className="player-media-backdrop is-rest-background"
            numBars={9}
            gradientFrom="rgba(224, 228, 230, 0.72)"
            gradientTo="rgba(5, 6, 5, 0)"
            animationDuration={2.4}
            backgroundColor="#050605"
          />
        ) : !hasCurrentMediaLayer ? (
          <GradientBarsBackground
            className={`player-media-backdrop is-${currentResolution.status}`}
            numBars={9}
            gradientFrom="rgba(224, 228, 230, 0.78)"
            gradientTo="rgba(5, 6, 5, 0)"
            animationDuration={2.2}
            backgroundColor="#050605"
            ariaLabel={mediaPlaceholderLabel}
          >
            {currentResolution.status === 'blocked' && currentResolution.detail ? <span className="player-media-backdrop-message">{currentResolution.detail}</span> : null}
          </GradientBarsBackground>
        ) : null}
        {hasCurrentMediaLayer && !currentMediaLoaded ? (
          <GradientBarsBackground
            className="player-media-backdrop is-frame-wait"
            numBars={9}
            gradientFrom="rgba(224, 228, 230, 0.78)"
            gradientTo="rgba(5, 6, 5, 0)"
            animationDuration={2.2}
            backgroundColor="#050605"
            ariaLabel="Loading workout media"
          />
        ) : null}
        {hasCurrentMediaLayer ? (
          <PlayerMediaLayer
            key={currentResolution.url}
            resolution={currentResolution}
            mediaKey={activeWorkMediaKey}
            role="current"
            isLoaded={currentMediaLoaded}
            paused={paused}
            videoRef={videoRef}
            onLoaded={markMediaLoaded}
            onVideoFrameLoaded={markVideoFrameLoaded}
            onError={fallbackBlob}
          />
        ) : null}
        {hasNextPreloadLayer ? (
          <PlayerMediaLayer
            key={nextPreviewResolved.url}
            resolution={nextPreviewResolved}
            mediaKey={nextPreviewMediaKey}
            role="preload"
            isLoaded={nextPreviewMediaLoaded}
            paused
            onLoaded={markMediaLoaded}
            onVideoFrameLoaded={markVideoFrameLoaded}
          />
        ) : null}
      </div>
      <div className="player-scrim" />
      {segment.type === 'rest' ? (
        <div className="player-rest-overlay" aria-hidden="true">
          <RestIconImage className="player-rest-icon" />
        </div>
      ) : null}
      <button
        className={`player-playback-control is-${playbackOverlay === 'idle' ? 'idle' : `showing-${playbackOverlay}`}`}
        type="button"
        onClick={togglePlayback}
        aria-label={paused ? 'Resume workout' : 'Pause workout'}
        title={paused ? 'Resume' : 'Pause'}
        tabIndex={playbackOverlay === 'idle' ? -1 : 0}
      >
        <Play className="player-playback-icon player-playback-icon-play" size={64} aria-hidden="true" />
        <Pause className="player-playback-icon player-playback-icon-pause" size={64} aria-hidden="true" />
      </button>
      <div className={`player-header ${descriptionExpanded ? 'is-expanded' : ''}`}>
        <div className="player-progress" aria-label="Workout progress">
          {segments.map((item, itemIndex) => {
            const className = itemIndex < index ? 'is-done' : itemIndex === index ? `is-current ${progressRepeats ? 'is-looping' : ''}` : '';
            return (
              <span key={`${item.blockId}-${itemIndex}`} className={className}>
                {itemIndex === index ? (
                  <span
                    key={`${item.blockId}-${itemIndex}-${progressSeconds}-${progressRepeats ? 'loop' : 'once'}`}
                    className="player-progress-fill"
                    style={progressFillStyle}
                  />
                ) : null}
              </span>
            );
          })}
        </div>
        <div className="player-top">
          <div className="player-heading">
            <strong>{segment.title}</strong>
            {segmentDescription ? (
              <button
                className={`player-description ${descriptionExpanded ? 'is-open' : ''}`}
                type="button"
                onClick={() => setDescriptionExpanded((value) => !value)}
                aria-expanded={descriptionExpanded}
                aria-label={descriptionExpanded ? 'Collapse description' : 'Expand description'}
              >
                <span>{visibleDescription}</span>
              </button>
            ) : null}
          </div>
          <div className="player-control-stack">
            <button
              className={`player-icon player-audio ${audioEnabled ? 'is-on' : 'is-off'}`}
              type="button"
              onClick={toggleAudio}
              aria-label={audioToggleLabel}
              aria-pressed={audioEnabled}
              title={audioEnabled ? 'Audio on' : 'Audio off'}
            >
              {audioEnabled ? <Volume2 size={20} aria-hidden="true" /> : <VolumeX size={20} aria-hidden="true" />}
            </button>
            <button className="player-icon player-close" type="button" onClick={onClose} aria-label="Close player"><X size={20} /></button>
          </div>
        </div>
        {nextSegmentPreview ? (
          <section className="player-next-preview" aria-label="Next exercise preview">
            <NextPreviewMedia resolution={nextPreviewResolved} mediaKey={nextPreviewMediaKey} isLoaded={nextPreviewMediaLoaded} onLoaded={markMediaLoaded} />
            <div className="player-next-preview-copy">
              <strong>{nextSegmentPreview.title}</strong>
              <span>{nextPreviewDescription || 'Next exercise'}</span>
            </div>
          </section>
        ) : null}
      </div>
      <div className="player-bottom-actions">
        <button type="button" onClick={previous}>
          <ChevronLeft size={17} aria-hidden="true" />
          <span>Prev</span>
        </button>
        <div className={`player-time ${isReps ? 'is-reps' : ''}`} aria-live="polite">
          {segmentModeLabel ? <span>{segmentModeLabel}</span> : null}
          <strong>{counter}</strong>
        </div>
        <button type="button" onClick={() => advance(!isReps)}>
          {isReps ? <Check size={17} aria-hidden="true" /> : <SkipForward size={17} aria-hidden="true" />}
          <span>{isReps ? 'Done' : 'Skip'}</span>
        </button>
      </div>
      {finishError ? (
        <div className="player-error">
          <span>{finishError}</span>
          <button type="button" onClick={() => void finish()} disabled={isFinishing}>
            <RotateCcw size={14} aria-hidden="true" />
            <span>{isFinishing ? 'Saving' : 'Retry'}</span>
          </button>
        </div>
      ) : null}
      {currentResolution.status === 'error' && segment.type === 'work' ? (
        <div className="player-error">
          <span>{currentResolution.detail}</span>
          {currentResolution.canRetry ? (
            <button type="button" onClick={() => setRetryNonce((value) => value + 1)}>
              <RotateCcw size={14} aria-hidden="true" />
              <span>Retry</span>
            </button>
          ) : null}
        </div>
      ) : null}
    </main>
  );
}

function RestIconImage({ className }: { className: string }) {
  return <img className={className} src={REST_ICON_SRC} alt="" aria-hidden="true" draggable={false} />;
}

function PlayerMediaLayer({
  resolution,
  mediaKey,
  role,
  isLoaded,
  paused,
  videoRef,
  onLoaded,
  onVideoFrameLoaded,
  onError
}: {
  resolution: MediaPlaybackResolution;
  mediaKey: string;
  role: 'current' | 'preload';
  isLoaded: boolean;
  paused: boolean;
  videoRef?: Ref<HTMLVideoElement>;
  onLoaded: (url: string) => void;
  onVideoFrameLoaded: (video: HTMLVideoElement, url: string) => void;
  onError?: () => void | Promise<void>;
}) {
  const className = role === 'preload' ? 'is-preload-layer' : isLoaded ? 'is-frame-ready' : 'is-awaiting-frame';
  const recordVideoMetric = (event: 'loadeddata' | 'canplay' | 'error', video: HTMLVideoElement) => {
    recordMediaPlaybackMetric({
      event: `media.video.${event}`,
      media_key: mediaKey,
      role,
      media_kind: resolution.mediaKind,
      status: resolution.status,
      ready_state: video.readyState,
      network_state: video.networkState,
      ...latestMediaResourceTiming(resolution.url)
    });
  };
  const handleError = () => {
    if (onError) void onError();
  };
  if (resolution.mediaKind === 'video') {
    return (
      <video
        ref={role === 'current' ? videoRef : undefined}
        className={className}
        data-player-media-role={role}
        src={resolution.url}
        muted
        autoPlay={role === 'current' && !paused}
        loop
        {...inlineVideoPlaybackProps}
        preload="auto"
        aria-hidden={role === 'preload' ? 'true' : undefined}
        onLoadedData={(event) => {
          recordVideoMetric('loadeddata', event.currentTarget);
          onVideoFrameLoaded(event.currentTarget, resolution.url);
        }}
        onCanPlay={(event) => {
          recordVideoMetric('canplay', event.currentTarget);
          onVideoFrameLoaded(event.currentTarget, resolution.url);
        }}
        onError={(event) => {
          recordVideoMetric('error', event.currentTarget);
          handleError();
        }}
      />
    );
  }
  return (
    <img
      className={className}
      data-player-media-role={role}
      src={resolution.url}
      alt=""
      decoding="async"
      aria-hidden={role === 'preload' ? 'true' : undefined}
      onLoad={() => onLoaded(resolution.url)}
      onError={handleError}
    />
  );
}

function NextPreviewMedia({ resolution, mediaKey, isLoaded, onLoaded }: { resolution: MediaPlaybackResolution; mediaKey: string; isLoaded: boolean; onLoaded: (url: string) => void }) {
  const recordPreviewVideoMetric = (event: 'loadeddata' | 'canplay' | 'error', video: HTMLVideoElement) => {
    recordMediaPlaybackMetric({
      event: `media.video.${event}`,
      media_key: mediaKey,
      role: 'preview',
      media_kind: resolution.mediaKind,
      status: resolution.status,
      ready_state: video.readyState,
      network_state: video.networkState,
      ...latestMediaResourceTiming(resolution.url)
    });
  };
  if (resolution.status === 'ready' && resolution.mediaKind === 'video') {
    return (
      <div className={`player-next-preview-media ${isLoaded ? 'is-ready' : 'is-loading'}`}>
        {!isLoaded ? <span className="player-next-preview-skeleton" /> : null}
        <video
          className={isLoaded ? 'is-frame-ready' : 'is-awaiting-frame'}
          src={resolution.url}
          muted
          autoPlay={isLoaded}
          loop
          {...inlineVideoPlaybackProps}
          preload="auto"
          onLoadedData={(event) => {
            recordPreviewVideoMetric('loadeddata', event.currentTarget);
            onLoaded(resolution.url);
          }}
          onCanPlay={(event) => {
            recordPreviewVideoMetric('canplay', event.currentTarget);
            onLoaded(resolution.url);
          }}
          onError={(event) => recordPreviewVideoMetric('error', event.currentTarget)}
        />
      </div>
    );
  }
  if (resolution.status === 'ready' && resolution.mediaKind === 'image') {
    return (
      <div className={`player-next-preview-media ${isLoaded ? 'is-ready' : 'is-loading'}`}>
        {!isLoaded ? <span className="player-next-preview-skeleton" /> : null}
        <img
          className={isLoaded ? 'is-frame-ready' : 'is-awaiting-frame'}
          src={resolution.url}
          alt=""
          decoding="async"
          onLoad={() => onLoaded(resolution.url)}
        />
      </div>
    );
  }
  return (
    <div className="player-next-preview-media is-loading" aria-hidden="true">
      <span className="player-next-preview-skeleton" />
    </div>
  );
}

async function playerFallbackResolution(media: ExerciseMediaRef, currentResolution: MediaPlaybackResolution): Promise<MediaPlaybackResolution> {
  if (media.kind === 'drive_file') {
    const detail = await drivePlaybackFailureDetail(media, currentResolution);
    cancelMediaPlayback(media);
    return {
      status: 'error',
      url: driveMediaStreamUrl(media),
      mediaKind: media.preview_kind,
      detail,
      canRetry: true
    };
  }
  return createLocalBlobFallback(media);
}

async function drivePlaybackFailureDetail(media: Extract<ExerciseMediaRef, { kind: 'drive_file' }>, currentResolution: MediaPlaybackResolution) {
  const cachedDetail = latestMediaPlaybackError(media);
  if (cachedDetail) return cachedDetail;
  if (currentResolution.warmup) {
    const warmed = await Promise.race([
      currentResolution.warmup,
      new Promise<null>((resolve) => window.setTimeout(() => resolve(null), 300))
    ]);
    if (warmed?.status === 'error' && warmed.detail) return warmed.detail;
  }
  return 'Storage could not play this Drive media yet. Retry after Drive localization is ready.';
}

function MediaThumb({ media, variant = 'small' }: { media: ExerciseMediaRef | null; variant?: 'small' | 'large' }) {
  const [previewFailed, setPreviewFailed] = useState(false);
  const [isVisible, setIsVisible] = useState(variant === 'large');
  const [resolvedPreviewUrl, setResolvedPreviewUrl] = useState('');
  const [previewFrameUrl, setPreviewFrameUrl] = useState('');
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const previewUrl = useMemo(() => mediaCoverUrl(media), [media]);
  const previewFrameKey = useMemo(() => media ? mediaThumbPreviewFrameKey(media) : '', [media]);

  useEffect(() => {
    const cachedPreviewFrame = previewFrameKey ? readMediaThumbPreviewFrame(previewFrameKey) : '';
    setPreviewFailed(false);
    setPreviewLoaded(false);
    setIsVisible(variant === 'large' || Boolean(cachedPreviewFrame));
    setResolvedPreviewUrl('');
    setPreviewFrameUrl(cachedPreviewFrame);
  }, [previewFrameKey, previewUrl, variant]);

  useEffect(() => {
    if (isVisible || !previewUrl) return;
    const element = frameRef.current;
    if (!element || typeof IntersectionObserver === 'undefined') {
      setIsVisible(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setIsVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: '160px' });
    observer.observe(element);
    return () => observer.disconnect();
  }, [isVisible, previewUrl]);

  useEffect(() => {
    if (!isVisible || !media || !previewUrl || previewFrameUrl) return;
    let canceled = false;
    resolveMediaPlayback(media).then((resolution) => {
      if (canceled) return;
      if (resolution.status === 'ready' && resolution.url) {
        setResolvedPreviewUrl(resolution.url);
      }
    }).catch(() => {
      if (!canceled) setResolvedPreviewUrl('');
    });
    return () => {
      canceled = true;
    };
  }, [isVisible, media, previewFrameUrl, previewUrl]);

  function cacheVideoFrame(event: ReactSyntheticEvent<HTMLVideoElement>) {
    const captured = captureMediaThumbVideoFrame(event.currentTarget, previewFrameKey);
    if (captured) setPreviewFrameUrl(captured);
    setPreviewLoaded(true);
  }

  const hasPreviewMedia = Boolean(previewUrl && media && !previewFailed);
  const className = `media-thumb ${variant === 'large' ? 'is-large' : ''} ${media ? '' : 'is-empty'} ${hasPreviewMedia ? previewLoaded ? 'is-media-ready' : 'is-preview-loading' : ''}`;
  const visiblePreviewUrl = isVisible ? (resolvedPreviewUrl || previewUrl) : '';
  if (previewUrl && media && !previewFailed) {
    const previewMedia = media;
    return (
      <div className={className} ref={frameRef}>
        {!previewLoaded ? <span className="media-thumb-skeleton" aria-hidden="true" /> : null}
        {previewMedia.preview_kind === 'video' && previewFrameUrl ? (
          <img src={previewFrameUrl} alt="" onLoad={() => setPreviewLoaded(true)} onError={() => { setPreviewFrameUrl(''); setPreviewFailed(true); }} />
        ) : previewMedia.preview_kind === 'video' ? (
          <video
            src={visiblePreviewUrl ? withVideoFrameHint(visiblePreviewUrl) : undefined}
            muted
            {...inlineVideoPlaybackProps}
            preload={isVisible ? 'metadata' : 'none'}
            aria-hidden="true"
            onLoadedMetadata={(event) => {
              try {
                event.currentTarget.currentTime = Math.min(0.12, event.currentTarget.duration || 0.12);
              } catch {
                // Some Storage streams do not allow seeking during metadata load.
              }
            }}
            onLoadedData={cacheVideoFrame}
            onSeeked={cacheVideoFrame}
            onError={() => { setPreviewLoaded(false); setPreviewFailed(true); }}
          />
        ) : (
          <img src={visiblePreviewUrl || undefined} alt="" onLoad={() => setPreviewLoaded(true)} onError={() => { setPreviewLoaded(false); setPreviewFailed(true); }} />
        )}
      </div>
    );
  }
  return (
    <div className={className}>
      {media?.preview_kind === 'video' ? <Play size={18} aria-hidden="true" /> : media ? <Library size={18} aria-hidden="true" /> : <MoreHorizontal size={18} aria-hidden="true" />}
    </div>
  );
}

function mediaCoverUrl(media: ExerciseMediaRef | null) {
  if (!media) return '';
  const storageAppId = currentStorageAppId();
  if (media.kind === 'local_file') {
    if (!media.file_id) return '';
    const params = new URLSearchParams();
    params.set('file_id', media.file_id);
    const sourceVersion = String(media.etag_or_version || media.sha256 || '').trim();
    if (sourceVersion) params.set('source_version', sourceVersion);
    return `/api/apps/${encodeURIComponent(storageAppId)}/media?${params.toString()}`;
  }
  if (!media.stable_storage_file_id || !media.connection_id || !media.drive_file_id) return '';
  return driveMediaStreamUrl(media, storageAppId);
}

function withVideoFrameHint(url: string) {
  if (!url || url.includes('#')) return url;
  return `${url}#t=0.1`;
}

function exerciseDescriptionValue(exercise: { long_description?: string | null; short_description?: string | null }) {
  return (exercise.long_description || exercise.short_description || '').trim();
}

function exerciseDescriptionPreview(exercise: { long_description?: string | null; short_description?: string | null }) {
  return shortDescriptionFrom(exerciseDescriptionValue(exercise), 160);
}

function prepareExerciseForSave(draft: Partial<Exercise>): Partial<Exercise> {
  const description = exerciseDescriptionValue(draft);
  return {
    ...draft,
    long_description: description,
    short_description: shortDescriptionFrom(description),
    tags: normalizeDraftTags(draft.tags || [])
  };
}

function exerciseDraftSignature(draft: Partial<Exercise>) {
  return JSON.stringify({
    title: (draft.title || '').trim(),
    description: exerciseDescriptionValue(draft),
    tags: normalizeDraftTags(draft.tags || []),
    primary_media: mediaSignature(draft.primary_media || null),
    source_folder: draft.source_folder || null,
    source_display_path: draft.source_display_path || null
  });
}

function mediaSignature(media: ExerciseMediaRef | null) {
  if (!media) return null;
  if (media.kind === 'local_file') {
    return {
      kind: media.kind,
      file_id: media.file_id,
      workspace_relative_path: media.workspace_relative_path,
      etag_or_version: media.etag_or_version || media.sha256 || ''
    };
  }
  return {
    kind: media.kind,
    stable_storage_file_id: media.stable_storage_file_id,
    connection_id: media.connection_id,
    drive_file_id: media.drive_file_id,
    source_version: media.source_version || media.etag_or_version || ''
  };
}

function normalizeDraftTags(tags: string[]) {
  const next: string[] = [];
  tags.forEach((tag) => {
    const value = tag.trim().toLowerCase();
    if (value && !next.includes(value)) next.push(value);
  });
  return next;
}

function shortDescriptionFrom(value: string, maxLength = 140) {
  const text = value.replace(/\s+/g, ' ').trim();
  if (text.length <= maxLength) return text;
  const clipped = text.slice(0, maxLength - 3).trimEnd();
  const lastSpace = clipped.lastIndexOf(' ');
  return `${(lastSpace > 48 ? clipped.slice(0, lastSpace) : clipped).trimEnd()}...`;
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  const unit = label.toLowerCase().includes('reps') ? 'reps' : 'seconds';
  return (
    <label className="number-field">
      <input aria-label={label} type="number" min={0} value={value} onChange={(event) => onChange(Math.max(0, Number(event.target.value) || 0))} />
      <span className="number-field-unit" aria-hidden="true">{unit}</span>
    </label>
  );
}

function workoutSummary(workout: Workout) {
  const totals = workout.blocks.reduce(
    (acc, block, index) => {
      if (block.type === 'rest') {
        const hasNextWork = workout.blocks.slice(index + 1).some((candidate) => candidate.type === 'work');
        if (block.skip_if_last && !hasNextWork) return acc;
        acc.seconds += Math.max(0, block.seconds || 0);
      } else if (block.mode === 'timer') {
        acc.seconds += Math.max(0, block.seconds || 0);
      } else {
        acc.reps += Math.max(0, block.reps || 0);
      }
      return acc;
    },
    { seconds: 0, reps: 0 }
  );
  if (workout.blocks.some((block) => block.type === 'work')) {
    totals.seconds += PREPARATION_BLOCK_SECONDS;
  }
  return {
    duration: formatWorkoutDuration(totals.seconds),
    reps: `${totals.reps} reps`
  };
}

function formatWorkoutDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes && remainder) return `${minutes}m ${remainder}s`;
  if (minutes) return `${minutes}m`;
  return `${remainder}s`;
}

function blockWithMode(block: WorkoutBlock, mode: WorkoutBlockMode, workout: Workout): WorkoutBlock {
  if (mode === 'rest') {
    if (block.type === 'rest') {
      return { ...block, title: 'Rest', seconds: block.seconds || workout.default_rest_seconds };
    }
    return {
      ...blankRestBlock(workout.default_rest_seconds),
      id: block.id,
      seconds: block.mode === 'timer' && block.seconds ? block.seconds : workout.default_rest_seconds
    };
  }

  if (block.type === 'work') {
    return {
      ...block,
      mode,
      seconds: mode === 'timer' ? block.seconds || workout.default_work_seconds : null,
      reps: mode === 'reps' ? block.reps || workout.default_reps : null,
      reps_label: null
    };
  }

  return {
    ...blankWorkBlock(mode, workout),
    id: block.id,
    seconds: mode === 'timer' ? block.seconds || workout.default_work_seconds : null,
    reps: mode === 'reps' ? workout.default_reps : null
  };
}

function blankWorkBlock(mode: 'timer' | 'reps', workout: Workout): WorkBlock {
  return {
    id: crypto.randomUUID(),
    type: 'work',
    exercise_id: null,
    exercise_snapshot_updated_at: null,
    title: '',
    short_description: '',
    long_description: '',
    tags: [],
    mode,
    seconds: mode === 'timer' ? workout.default_work_seconds : null,
    reps: mode === 'reps' ? workout.default_reps : null,
    reps_label: null,
    media: null,
    notes: null
  };
}

function blankRestBlock(seconds: number): RestBlock {
  return {
    id: crypto.randomUUID(),
    type: 'rest',
    title: 'Rest',
    short_description: 'Get ready for the next exercise.',
    long_description: 'Breathe, reset, and preview the next movement.',
    seconds,
    show_next_exercise: true,
    skip_if_last: true
  };
}

function workBlockFromExercise(exercise: Exercise, workout: Workout, existing?: WorkoutBlock): WorkBlock {
  const mode = existing?.type === 'work' ? existing.mode : 'timer';
  const description = exerciseDescriptionValue(exercise);
  return {
    id: existing?.id || crypto.randomUUID(),
    type: 'work',
    exercise_id: exercise.id,
    exercise_snapshot_updated_at: exercise.updated_at,
    title: exercise.title,
    short_description: shortDescriptionFrom(description),
    long_description: description,
    tags: exercise.tags,
    mode,
    seconds: mode === 'timer' ? (existing?.type === 'work' && existing.seconds ? existing.seconds : workout.default_work_seconds) : null,
    reps: mode === 'reps' ? (existing?.type === 'work' && existing.reps ? existing.reps : workout.default_reps) : null,
    reps_label: null,
    media: exercise.primary_media,
    notes: existing?.type === 'work' ? existing.notes : null
  };
}

function exerciseForPlayerFromBlock(block: WorkBlock, exercise: Exercise | null): Exercise | null {
  if (exercise?.primary_media || exercise?.media.length) return exercise;
  if (!block.media) return null;
  return {
    id: block.exercise_id || block.id,
    title: block.title || 'Untitled exercise',
    short_description: block.short_description || shortDescriptionFrom(block.long_description || ''),
    long_description: block.long_description || block.short_description || '',
    tags: block.tags,
    primary_media: block.media,
    media: [block.media],
    source_folder: null,
    source_display_path: block.media.display_path || null,
    created_at: block.exercise_snapshot_updated_at || '',
    updated_at: block.exercise_snapshot_updated_at || ''
  };
}

function syncWorkoutExerciseSnapshots(workout: Workout | null, exercises: Exercise[]): Workout | null {
  if (!workout || exercises.length === 0) return workout;
  const exercisesById = new Map(exercises.map((exercise) => [exercise.id, exercise]));
  let changed = false;
  const blocks = workout.blocks.map((block) => {
    if (block.type !== 'work' || !block.exercise_id) return block;
    const exercise = exercisesById.get(block.exercise_id);
    if (!exercise) return block;
    const description = exerciseDescriptionValue(exercise);
    changed = true;
    return {
      ...block,
      exercise_snapshot_updated_at: exercise.updated_at,
      title: exercise.title,
      short_description: shortDescriptionFrom(description),
      long_description: description,
      tags: exercise.tags,
      media: exercise.primary_media
    };
  });
  return changed ? { ...workout, blocks } : workout;
}

function replaceById<T extends { id: string }>(items: T[], next: T) {
  const exists = items.some((item) => item.id === next.id);
  return exists ? items.map((item) => (item.id === next.id ? next : item)) : [next, ...items];
}

function mergeDirtyWorkouts(nextWorkouts: Workout[], currentWorkouts: Workout[], dirtyIds: Set<string>) {
  if (dirtyIds.size === 0) return nextWorkouts;
  const localById = new Map(currentWorkouts.map((workout) => [workout.id, workout]));
  const serverIds = new Set(nextWorkouts.map((workout) => workout.id));
  const merged = nextWorkouts.map((workout) => {
    const local = localById.get(workout.id);
    return dirtyIds.has(workout.id) && local ? local : workout;
  });
  currentWorkouts.forEach((workout) => {
    if (dirtyIds.has(workout.id) && !serverIds.has(workout.id)) {
      merged.unshift(workout);
    }
  });
  return merged;
}

function insertAfter<T extends { id: string }>(items: T[], id: string, next: T) {
  const index = items.findIndex((item) => item.id === id);
  if (index < 0) return [...items, next];
  return [...items.slice(0, index + 1), next, ...items.slice(index + 1)];
}

function nextWorkSegment(segments: RuntimeSegment[], index: number): Extract<RuntimeSegment, { type: 'work' }> | null {
  const next = segments.slice(index + 1).find((item) => item.type === 'work');
  return next?.type === 'work' ? next : null;
}

function workMediaWarmupWindow(segments: RuntimeSegment[], index: number): ExerciseMediaRef[] {
  const mediaList: ExerciseMediaRef[] = [];
  const seen = new Set<string>();
  const limit = segments[index]?.type === 'work' ? 3 : 2;
  for (const segment of segments.slice(Math.max(0, index))) {
    if (segment.type !== 'work') continue;
    const key = mediaCacheKey(segment.media);
    if (seen.has(key)) continue;
    seen.add(key);
    mediaList.push(segment.media);
    if (mediaList.length >= limit) break;
  }
  return mediaList;
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (!minutes) return `${rest}s`;
  return `${minutes}m ${rest.toString().padStart(2, '0')}s`;
}

function formatClock(seconds: number) {
  const value = Math.max(0, seconds);
  return `${Math.floor(value / 60).toString().padStart(2, '0')}:${(value % 60).toString().padStart(2, '0')}`;
}

function formatRepsCounter(reps?: number, label?: string) {
  if (reps && reps > 0) return String(reps);
  const match = String(label || '').match(/\d+(?:[.,]\d+)?/);
  return match ? match[0] : '0';
}

function playTone(frequency: number, duration: number, context?: AudioContext | null) {
  try {
    const audioContext = context || new AudioContext();
    if (audioContext.state !== 'running') return;
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.frequency.value = frequency;
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    gain.gain.value = 0.04;
    oscillator.start();
    oscillator.stop(audioContext.currentTime + duration);
  } catch {
    // Audio can be blocked until a user gesture; visual state still works.
  }
}

async function unlockWorkoutAudio(audio: HTMLAudioElement | null, audioContextRef: { current: AudioContext | null }) {
  const mediaReady = await unlockCountdownAudio(audio);
  const toneReady = await unlockToneAudio(audioContextRef);
  return mediaReady && toneReady;
}

async function unlockCountdownAudio(audio: HTMLAudioElement | null) {
  if (!audio) return true;
  const previousMuted = audio.muted;
  const previousVolume = audio.volume;
  try {
    audio.pause();
    audio.currentTime = 0;
    audio.muted = true;
    audio.volume = 0;
    const playPromise = audio.play();
    if (playPromise && typeof playPromise.then === 'function') await playPromise;
    audio.pause();
    audio.currentTime = 0;
    return true;
  } catch {
    return false;
  } finally {
    audio.muted = previousMuted;
    audio.volume = previousVolume;
  }
}

async function unlockToneAudio(audioContextRef: { current: AudioContext | null }) {
  try {
    const audioContext = audioContextRef.current || new AudioContext();
    audioContextRef.current = audioContext;
    if (audioContext.state === 'suspended') await audioContext.resume();
    if (audioContext.state !== 'running') return false;
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    gain.gain.value = 0;
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + 0.01);
    return true;
  } catch {
    return false;
  }
}

function disableWorkoutAudio(audio: HTMLAudioElement | null, audioContextRef: { current: AudioContext | null }) {
  try {
    audio?.pause();
    if (audio) audio.currentTime = 0;
  } catch {
    // Disabling audio should never block the player UI.
  }
  audioContextRef.current?.suspend().catch(() => undefined);
}

function playCountdownSound(audio: HTMLAudioElement | null) {
  if (!audio) return;
  try {
    audio.pause();
    audio.currentTime = 0;
    const playPromise = audio.play();
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise.catch(() => undefined);
    }
  } catch {
    // Countdown audio is non-critical; timer advancement remains authoritative.
  }
}
