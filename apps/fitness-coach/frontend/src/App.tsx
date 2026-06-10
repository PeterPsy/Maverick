import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react';
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
  completeWorkout,
  createExercise,
  createWorkout,
  currentStorageAppId,
  deleteExercise,
  deleteWorkout,
  duplicateWorkout,
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
import { GradientBarsBackground } from './components/ui/gradient-bars-background';
import { createLocalBlobFallback, driveMediaStreamUrl, initialMediaResolution, resolveMediaPlayback } from './mediaPlaybackResolver';
import { TagsInputField } from './components/ui/tags-input';
import type { Exercise, ExerciseMediaRef, MediaPlaybackResolution, RestBlock, RuntimeSegment, SetupTab, WorkBlock, Workout, WorkoutBlock, WorkoutRunSummary } from './types';
import { useWorkoutBlockReorder, type ReorderItemProps } from './useWorkoutBlockReorder';
import { runtimeSegmentsForWorkout, segmentProgressRepeats, segmentProgressSeconds } from './workoutSegments';
import { validateWorkoutForStart } from './workoutValidation';

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
const REST_ICON_SRC = 'rest-icon.svg';
const COUNTDOWN_SOUND_SRC = '/apps/fitness-coach/count-down-fitness-coach.mp3';
const COUNTDOWN_SOUND_LEAD_MS = 3800;

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
  const [playerWorkout, setPlayerWorkout] = useState<Workout | null>(null);
  const [exerciseDraft, setExerciseDraft] = useState<Partial<Exercise> | null>(null);
  const [libraryTargetBlockId, setLibraryTargetBlockId] = useState<string | null>(null);
  const [savedWorkoutId, setSavedWorkoutId] = useState<string | null>(null);
  const dirtyWorkoutIdsRef = useRef<Set<string>>(new Set());

  const selectedWorkout = useMemo(
    () => workouts.find((workout) => workout.id === selectedWorkoutId) || workouts[0] || null,
    [selectedWorkoutId, workouts]
  );
  const syncedSelectedWorkout = useMemo(() => syncWorkoutExerciseSnapshots(selectedWorkout, exercises), [selectedWorkout, exercises]);
  const validation = useMemo(() => validateWorkoutForStart(syncedSelectedWorkout), [syncedSelectedWorkout]);
  const tags = useMemo(() => Array.from(new Set(exercises.flatMap((exercise) => exercise.tags))).sort(), [exercises]);

  const refresh = useCallback(async () => {
    const [nextWorkouts, nextExercises, nextRuns] = await Promise.all([listWorkouts(), listExercises(libraryQuery, libraryTag), listRuns(selectedWorkoutId || undefined)]);
    setWorkouts((current) => mergeDirtyWorkouts(nextWorkouts, current, dirtyWorkoutIdsRef.current));
    setExercises(nextExercises);
    setRuns(nextRuns);
    setSelectedWorkoutId((current) => current || nextWorkouts[0]?.id || null);
  }, [libraryQuery, libraryTag, selectedWorkoutId]);

  const markWorkoutDirty = useCallback((workout: Workout) => {
    dirtyWorkoutIdsRef.current.add(workout.id);
    setSavedWorkoutId(null);
    setWorkouts((items) => replaceById(items, workout));
  }, []);

  useEffect(() => {
    let isCurrent = true;
    refresh()
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
  }, [refresh]);

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
    updateViewState({ selected_workout_id: selectedWorkout.id, setup_tab: setupTab }).catch(() => undefined);
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

  async function handleStart() {
    const workoutToStart = syncWorkoutExerciseSnapshots(selectedWorkout, exercises);
    if (!workoutToStart || !validation.valid) return;
    setBusy('start');
    try {
      const saved = await saveWorkout(workoutToStart);
      dirtyWorkoutIdsRef.current.delete(saved.id);
      setWorkouts((items) => replaceById(items, saved));
      setSavedWorkoutId(saved.id);
      const payload = await startWorkout(saved.id);
      setPlayerWorkout(payload.workout);
      setNotice('');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Workout is not ready.');
    } finally {
      setBusy('');
    }
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
    if (!window.confirm(`Delete exercise "${exercise.title}"?`)) return;
    try {
      await deleteExercise(exercise.id);
      setExercises((items) => items.filter((item) => item.id !== exercise.id));
      setExerciseDraft(null);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to delete exercise.');
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

  if (playerWorkout) {
    return <WorkPlayer workout={playerWorkout} onClose={() => setPlayerWorkout(null)} onComplete={(run) => setRuns((items) => [run, ...items].slice(0, 20))} />;
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
        {workout.blocks.map((block, index) => (
          <BlockEditor
            block={block}
            exercises={props.exercises}
            key={block.id}
            index={index}
            isDragging={blockReorder.draggingItemId === block.id}
            blockRef={(element) => blockReorder.setItemElement(block.id, element)}
            reorderItemProps={blockReorder.getItemProps(block.id)}
            onChange={(patch) => updateBlock(block.id, patch)}
            onModeChange={(mode) => replaceBlock(block.id, blockWithMode(block, mode, workout))}
            onOpenLibrary={() => props.onOpenLibraryForBlock(block.id)}
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
          <div className="block-media-panel">
            <MediaThumb media={media} />
            <span className="block-index block-index-overlay">{props.index + 1}</span>
          </div>
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
            <MediaThumb media={exercise.primary_media} />
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
              <button className="icon-button danger" type="button" onClick={() => props.onDelete(exercise)} aria-label="Delete exercise" title="Delete"><Trash2 size={15} /></button>
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
        {media ? (
          <button type="button" onClick={() => onChange(null)}>
            <X size={15} aria-hidden="true" />
            <span>Clear</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

function WorkPlayer({ workout, onClose, onComplete }: { workout: Workout; onClose: () => void; onComplete: (run: WorkoutRunSummary) => void }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const segments = useMemo(() => runtimeSegmentsForWorkout(workout), [workout]);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [remaining, setRemaining] = useState(segments[0]?.type === 'work' && segments[0].mode === 'reps' ? 0 : segments[0]?.seconds || 0);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [playbackOverlay, setPlaybackOverlay] = useState<PlayerPlaybackOverlay>('idle');
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [resolution, setResolution] = useState(initialMediaResolution());
  const [nextPreviewResolution, setNextPreviewResolution] = useState(initialMediaResolution());
  const [summary, setSummary] = useState<WorkoutRunSummary | null>(null);
  const [startedAt] = useState(new Date().toISOString());
  const [skipped, setSkipped] = useState(0);
  const [retryNonce, setRetryNonce] = useState(0);
  const timerRemainingMsRef = useRef(0);
  const timerStartedAtRef = useRef(0);
  const countdownPlayedRef = useRef(false);
  const countdownAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const playbackOverlayTimerRef = useRef<number | null>(null);
  const pointerStartRef = useRef<{ x: number; y: number } | null>(null);
  const segment = segments[index];

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

  useEffect(() => {
    rootRef.current?.requestFullscreen?.().catch(() => undefined);
  }, []);

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
    setResolution(initialMediaResolution());
    if (!segment || segment.type !== 'work') return;
    let canceled = false;
    resolveMediaPlayback(segment.media).then((next) => {
      if (!canceled) setResolution(next);
    });
    return () => {
      canceled = true;
    };
  }, [index, retryNonce, segment, segments]);

  useEffect(() => {
    setNextPreviewResolution(initialMediaResolution());
    if (!segment) return;
    const nextPreview = nextWorkSegment(segments, index);
    if (!nextPreview) return;
    let canceled = false;
    resolveMediaPlayback(nextPreview.media).then((next) => {
      if (!canceled) setNextPreviewResolution(next);
    });
    return () => {
      canceled = true;
    };
  }, [index, retryNonce, segment, segments]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || resolution.mediaKind !== 'video') return;
    if (paused) {
      video.pause();
      return;
    }
    const playPromise = video.play();
    if (playPromise && typeof playPromise.catch === 'function') {
      playPromise.catch(() => {
        setPaused(true);
        showPlaybackOverlay('play');
      });
    }
  }, [paused, resolution.mediaKind, resolution.url, showPlaybackOverlay]);

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
    const elapsed = Math.max(0, Math.round((Date.now() - Date.parse(startedAt)) / 1000));
    const run = await completeWorkout({
      workout_id: workout.id,
      started_at: startedAt,
      elapsed_seconds: elapsed,
      completed_segments: segments.length,
      skipped_segments: skipped,
      exercise_count: segments.filter((item) => item.type === 'work').length
    });
    setSummary(run);
    onComplete(run);
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
    const next = await createLocalBlobFallback(segment.media);
    setResolution((current) => {
      current.revoke?.();
      return next;
    });
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
  const nextPreviewCandidate = nextWorkSegment(segments, index);
  const shouldShowNextPreview = Boolean(nextPreviewCandidate) && (
    segment.type === 'rest'
      ? segment.showNextExercise
      : segment.mode === 'timer' && remaining <= 5 && remaining > 0
  );
  const nextSegmentPreview = shouldShowNextPreview ? nextPreviewCandidate : null;
  const nextPreviewDescription = nextSegmentPreview?.short_description || nextSegmentPreview?.long_description || '';
  const segmentModeLabel = segment.type === 'rest' ? 'Rest' : isReps ? 'Reps' : 'Timer';
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
  const mediaPlaceholderLabel = resolution.status === 'blocked'
    ? resolution.detail
    : resolution.status === 'error'
      ? 'Workout media could not be loaded'
      : resolution.status === 'localizing'
        ? 'Storage is preparing workout media'
        : 'Loading workout media';
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
        ) : resolution.status === 'ready' && resolution.mediaKind === 'video' ? (
          <video ref={videoRef} src={resolution.url} muted autoPlay={!paused} loop playsInline onError={fallbackBlob} />
        ) : resolution.status === 'ready' && resolution.mediaKind === 'image' ? (
          <img src={resolution.url} alt="" onError={fallbackBlob} />
        ) : (
          <GradientBarsBackground
            className={`player-media-backdrop is-${resolution.status}`}
            numBars={9}
            gradientFrom="rgba(224, 228, 230, 0.78)"
            gradientTo="rgba(5, 6, 5, 0)"
            animationDuration={2.2}
            backgroundColor="#050605"
            ariaLabel={mediaPlaceholderLabel}
          >
            {resolution.status === 'blocked' && resolution.detail ? <span className="player-media-backdrop-message">{resolution.detail}</span> : null}
          </GradientBarsBackground>
        )}
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
            <NextPreviewMedia resolution={nextPreviewResolution} />
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
      {resolution.status === 'error' && segment.type === 'work' ? (
        <div className="player-error">
          <span>{resolution.detail}</span>
          {resolution.canRetry ? (
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

function NextPreviewMedia({ resolution }: { resolution: MediaPlaybackResolution }) {
  if (resolution.status === 'ready' && resolution.mediaKind === 'video') {
    return (
      <div className="player-next-preview-media">
        <video src={resolution.url} muted autoPlay loop playsInline />
      </div>
    );
  }
  if (resolution.status === 'ready' && resolution.mediaKind === 'image') {
    return (
      <div className="player-next-preview-media">
        <img src={resolution.url} alt="" />
      </div>
    );
  }
  return (
    <div className="player-next-preview-media is-loading" aria-hidden="true">
      <span className="player-next-preview-skeleton" />
    </div>
  );
}

function MediaThumb({ media, variant = 'small' }: { media: ExerciseMediaRef | null; variant?: 'small' | 'large' }) {
  const [previewFailed, setPreviewFailed] = useState(false);
  const previewUrl = useMemo(() => mediaCoverUrl(media), [media]);

  useEffect(() => {
    setPreviewFailed(false);
  }, [previewUrl]);

  const className = `media-thumb ${variant === 'large' ? 'is-large' : ''} ${media ? '' : 'is-empty'}`;
  if (previewUrl && media && !previewFailed) {
    return (
      <div className={className}>
        {media.preview_kind === 'video' ? (
          <video
            src={withVideoFrameHint(previewUrl)}
            muted
            playsInline
            preload="metadata"
            aria-hidden="true"
            onLoadedMetadata={(event) => {
              try {
                event.currentTarget.currentTime = Math.min(0.12, event.currentTarget.duration || 0.12);
              } catch {
                // Some Storage streams do not allow seeking during metadata load.
              }
            }}
            onError={() => setPreviewFailed(true)}
          />
        ) : (
          <img src={previewUrl} alt="" onError={() => setPreviewFailed(true)} />
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
