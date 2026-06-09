import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Check,
  Copy,
  Dumbbell,
  Library,
  ListPlus,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  Timer,
  Trash2,
  X
} from 'lucide-react';
import {
  completeWorkout,
  createExercise,
  createWorkout,
  deleteExercise,
  deleteWorkout,
  duplicateWorkout,
  listExercises,
  listRuns,
  listStorageMedia,
  listWorkouts,
  openStorageForMedia,
  saveExercise,
  saveWorkout,
  startWorkout,
  storageFileToMediaRef,
  updateViewState
} from './api';
import { createLocalBlobFallback, initialMediaResolution, resolveMediaPlayback } from './mediaPlaybackResolver';
import type { Exercise, ExerciseMediaRef, RestBlock, RuntimeSegment, SetupTab, StorageFile, WorkBlock, Workout, WorkoutBlock, WorkoutRunSummary } from './types';
import { runtimeSegmentsForWorkout } from './workoutSegments';
import { estimateWorkoutSeconds, validateWorkoutForStart } from './workoutValidation';

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

export function App() {
  const [workouts, setWorkouts] = useState<Workout[]>([]);
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [runs, setRuns] = useState<WorkoutRunSummary[]>([]);
  const [selectedWorkoutId, setSelectedWorkoutId] = useState<string | null>(null);
  const [setupTab, setSetupTab] = useState<SetupTab>('workout-settings');
  const [query, setQuery] = useState('');
  const [libraryQuery, setLibraryQuery] = useState('');
  const [libraryTag, setLibraryTag] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [playerWorkout, setPlayerWorkout] = useState<Workout | null>(null);
  const [exerciseDraft, setExerciseDraft] = useState<Partial<Exercise> | null>(null);

  const selectedWorkout = useMemo(
    () => workouts.find((workout) => workout.id === selectedWorkoutId) || workouts[0] || null,
    [selectedWorkoutId, workouts]
  );
  const validation = useMemo(() => validateWorkoutForStart(selectedWorkout), [selectedWorkout]);
  const tags = useMemo(() => Array.from(new Set(exercises.flatMap((exercise) => exercise.tags))).sort(), [exercises]);

  const refresh = useCallback(async () => {
    const [nextWorkouts, nextExercises, nextRuns] = await Promise.all([listWorkouts(query), listExercises(libraryQuery, libraryTag), listRuns(selectedWorkoutId || undefined)]);
    setWorkouts(nextWorkouts);
    setExercises(nextExercises);
    setRuns(nextRuns);
    setSelectedWorkoutId((current) => current || nextWorkouts[0]?.id || null);
  }, [libraryQuery, libraryTag, query, selectedWorkoutId]);

  useEffect(() => {
    refresh().catch((error: Error) => setNotice(error.message));
  }, [refresh]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== 'object') return;
      const payload = event.data as { type?: string; owner_app_id?: string; resource?: string; params?: Record<string, unknown>; app_page?: string };
      if (payload.type === 'maverick.app.data-changed' && payload.owner_app_id === 'fitness-coach') {
        refresh().catch((error: Error) => setNotice(error.message));
      }
      if (payload.type === 'maverick.app.navigate') {
        const params = payload.params || {};
        const appPage = String(params.app_page || payload.app_page || '');
        const workoutId = appPage.startsWith('workouts/') ? appPage.split('/')[1] : String(params.workout_id || '');
        if (workoutId) setSelectedWorkoutId(workoutId);
        if (params.new_exercise) {
          setSetupTab('exercise-library');
          setExerciseDraft({ ...EMPTY_EXERCISE });
        }
        if (params.new_workout) void handleCreateWorkout();
      }
    }
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [refresh]);

  useEffect(() => {
    if (!selectedWorkout?.id) return;
    updateViewState({ selected_workout_id: selectedWorkout.id, setup_tab: setupTab, sidebar_query: query }).catch(() => undefined);
    window.parent?.postMessage(
      {
        type: 'maverick.app.selection-changed',
        owner_app_id: 'fitness-coach',
        selection: { workout_id: selectedWorkout.id, app_page: `workouts/${selectedWorkout.id}` }
      },
      window.location.origin
    );
  }, [query, selectedWorkout?.id, setupTab]);

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
      const saved = await saveWorkout(workout);
      setWorkouts((items) => replaceById(items, saved));
      setNotice('Saved');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to save workout.');
    } finally {
      setBusy('');
    }
  }

  async function handleStart() {
    if (!selectedWorkout || !validation.valid) return;
    setBusy('start');
    try {
      const saved = await saveWorkout(selectedWorkout);
      setWorkouts((items) => replaceById(items, saved));
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
      const saved = draft.id ? await saveExercise(draft as Exercise) : await createExercise(draft);
      setExercises((items) => replaceById(items, saved));
      setExerciseDraft(saved);
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
    const block = workBlockFromExercise(exercise, selectedWorkout);
    const next = { ...selectedWorkout, blocks: [...selectedWorkout.blocks, block] };
    setWorkouts((items) => replaceById(items, next));
    await handleSaveWorkout(next);
    setSetupTab('workout-settings');
  }

  if (playerWorkout) {
    return <WorkPlayer workout={playerWorkout} onClose={() => setPlayerWorkout(null)} onComplete={(run) => setRuns((items) => [run, ...items].slice(0, 20))} />;
  }

  return (
    <main className="fitness-app">
      <header className="fitness-topbar">
        <div className="fitness-title">
          <Dumbbell size={20} aria-hidden="true" />
          <span>Fitness Coach</span>
        </div>
        <label className="fitness-search" aria-label="Search workouts">
          <Search size={16} aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search workouts" />
        </label>
        <button className="icon-button" type="button" onClick={() => refresh()} title="Refresh" aria-label="Refresh">
          <RefreshCw size={16} aria-hidden="true" />
        </button>
      </header>

      <section className="fitness-layout">
        <aside className="workout-list" aria-label="Workout list">
          <button className="primary-action" type="button" onClick={handleCreateWorkout} disabled={busy === 'new-workout'}>
            <Plus size={16} aria-hidden="true" />
            <span>New workout</span>
          </button>
          {workouts.length === 0 ? (
            <div className="empty-state">No workouts yet.</div>
          ) : (
            workouts.map((workout) => (
              <button
                key={workout.id}
                type="button"
                className={`workout-row ${selectedWorkout?.id === workout.id ? 'is-active' : ''}`}
                onClick={() => setSelectedWorkoutId(workout.id)}
              >
                <span>{workout.name}</span>
                <small>
                  {workout.blocks.filter((block) => block.type === 'work').length} exercises · {formatDuration(estimateWorkoutSeconds(workout))}
                </small>
              </button>
            ))
          )}
        </aside>

        <section className="setup-panel">
          <div className="setup-switch" role="tablist" aria-label="Setup mode">
            <button type="button" className={setupTab === 'workout-settings' ? 'is-active' : ''} onClick={() => setSetupTab('workout-settings')}>
              <Timer size={16} aria-hidden="true" />
              <span>Workout settings</span>
            </button>
            <button type="button" className={setupTab === 'exercise-library' ? 'is-active' : ''} onClick={() => setSetupTab('exercise-library')}>
              <Library size={16} aria-hidden="true" />
              <span>Exercise library</span>
            </button>
          </div>

          {notice ? <div className="notice">{notice}</div> : null}

          {setupTab === 'workout-settings' ? (
            <WorkoutEditor
              workout={selectedWorkout}
              exercises={exercises}
              validation={validation}
              busy={busy}
              onChange={(workout) => setWorkouts((items) => replaceById(items, workout))}
              onSave={handleSaveWorkout}
              onStart={handleStart}
              onDelete={handleDeleteWorkout}
              onDuplicate={handleDuplicateWorkout}
              onOpenLibrary={() => setSetupTab('exercise-library')}
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
            />
          )}
        </section>
      </section>
    </main>
  );
}

function WorkoutEditor(props: {
  workout: Workout | null;
  exercises: Exercise[];
  validation: ReturnType<typeof validateWorkoutForStart>;
  busy: string;
  onChange: (workout: Workout) => void;
  onSave: (workout: Workout) => void;
  onStart: () => void;
  onDelete: (workout: Workout) => void;
  onDuplicate: (workout: Workout) => void;
  onOpenLibrary: () => void;
}) {
  const { workout } = props;
  if (!workout) {
    return <div className="empty-state">Create a workout to begin.</div>;
  }

  function update(patch: Partial<Workout>) {
    props.onChange({ ...workout!, ...patch });
  }

  function updateBlock(blockId: string, patch: Partial<WorkoutBlock>) {
    update({ blocks: workout!.blocks.map((block) => (block.id === blockId ? ({ ...block, ...patch } as WorkoutBlock) : block)) });
  }

  function moveBlock(blockId: string, direction: -1 | 1) {
    const index = workout!.blocks.findIndex((block) => block.id === blockId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= workout!.blocks.length) return;
    const blocks = [...workout!.blocks];
    const [item] = blocks.splice(index, 1);
    blocks.splice(target, 0, item);
    update({ blocks });
  }

  function addBlock(type: 'timer' | 'reps' | 'rest') {
    const block = type === 'rest' ? blankRestBlock(workout!.default_rest_seconds) : blankWorkBlock(type, workout!);
    update({ blocks: [...workout!.blocks, block] });
  }

  return (
    <div className="editor">
      <div className="workout-header">
        <input className="workout-name-input" value={workout.name} onChange={(event) => update({ name: event.target.value })} aria-label="Workout name" />
        <div className="header-actions">
          <button className="icon-text-button" type="button" onClick={() => props.onDuplicate(workout)} title="Duplicate">
            <Copy size={16} aria-hidden="true" />
            <span>Duplicate</span>
          </button>
          <button className="icon-button danger" type="button" onClick={() => props.onDelete(workout)} title="Delete" aria-label="Delete workout">
            <Trash2 size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="settings-grid">
        <NumberField label="Work sec" value={workout.default_work_seconds} onChange={(value) => update({ default_work_seconds: value })} />
        <NumberField label="Rest sec" value={workout.default_rest_seconds} onChange={(value) => update({ default_rest_seconds: value })} />
        <NumberField label="Reps" value={workout.default_reps} onChange={(value) => update({ default_reps: value })} />
      </div>

      <div className="block-toolbar">
        <button type="button" onClick={props.onOpenLibrary}>
          <ListPlus size={16} aria-hidden="true" />
          <span>Add from library</span>
        </button>
        <button type="button" onClick={() => addBlock('timer')}>Timer</button>
        <button type="button" onClick={() => addBlock('reps')}>Reps</button>
        <button type="button" onClick={() => addBlock('rest')}>Rest</button>
      </div>

      <div className="block-list">
        {workout.blocks.map((block, index) => (
          <BlockEditor
            block={block}
            key={block.id}
            index={index}
            onChange={(patch) => updateBlock(block.id, patch)}
            onMove={(direction) => moveBlock(block.id, direction)}
            onDuplicate={() => update({ blocks: insertAfter(workout.blocks, block.id, { ...block, id: crypto.randomUUID() } as WorkoutBlock) })}
            onDelete={() => update({ blocks: workout.blocks.filter((candidate) => candidate.id !== block.id) })}
          />
        ))}
      </div>

      <div className="bottom-action-bar">
        <div className="validation-summary">
          {props.validation.valid ? <span className="ok">Ready · {formatDuration(props.validation.estimated_seconds)}</span> : <span>{props.validation.errors[0]?.message || 'Workout is incomplete.'}</span>}
        </div>
        <button className="secondary-action" type="button" onClick={() => props.onSave(workout)} disabled={props.busy === `save:${workout.id}`}>
          <Check size={16} aria-hidden="true" />
          <span>Save</span>
        </button>
        <button className="start-button" type="button" onClick={props.onStart} disabled={!props.validation.valid || props.busy === 'start'}>
          <Play size={16} aria-hidden="true" />
          <span>Avvia</span>
        </button>
      </div>
    </div>
  );
}

function BlockEditor(props: {
  block: WorkoutBlock;
  index: number;
  onChange: (patch: Partial<WorkoutBlock>) => void;
  onMove: (direction: -1 | 1) => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const { block } = props;
  return (
    <article className={`block-editor ${block.type === 'rest' ? 'is-rest' : ''}`}>
      <div className="block-handle">
        <span>{props.index + 1}</span>
        <button type="button" className="mini-icon" onClick={() => props.onMove(-1)} aria-label="Move up" title="Move up"><ArrowUp size={14} /></button>
        <button type="button" className="mini-icon" onClick={() => props.onMove(1)} aria-label="Move down" title="Move down"><ArrowDown size={14} /></button>
      </div>
      <div className="block-fields">
        <div className="inline-fields">
          <input value={block.title} onChange={(event) => props.onChange({ title: event.target.value } as Partial<WorkoutBlock>)} placeholder={block.type === 'rest' ? 'Recupero' : 'Exercise title'} />
          {block.type === 'work' ? (
            <select value={block.mode} onChange={(event) => props.onChange({ mode: event.target.value as 'timer' | 'reps' } as Partial<WorkoutBlock>)}>
              <option value="timer">Timer</option>
              <option value="reps">Reps</option>
            </select>
          ) : null}
        </div>
        <input value={block.short_description} onChange={(event) => props.onChange({ short_description: event.target.value } as Partial<WorkoutBlock>)} placeholder="Short description" />
        <textarea value={block.long_description} onChange={(event) => props.onChange({ long_description: event.target.value } as Partial<WorkoutBlock>)} placeholder="Full cues and setup" />
        {block.type === 'work' ? (
          <>
            <div className="inline-fields">
              {block.mode === 'timer' ? (
                <NumberField label="Seconds" value={block.seconds || 0} onChange={(seconds) => props.onChange({ seconds } as Partial<WorkoutBlock>)} />
              ) : (
                <>
                  <NumberField label="Reps" value={block.reps || 0} onChange={(reps) => props.onChange({ reps } as Partial<WorkoutBlock>)} />
                  <input value={block.reps_label || ''} onChange={(event) => props.onChange({ reps_label: event.target.value } as Partial<WorkoutBlock>)} placeholder="Label" />
                </>
              )}
            </div>
            <MediaPicker media={block.media} onChange={(media) => props.onChange({ media } as Partial<WorkoutBlock>)} />
          </>
        ) : (
          <div className="inline-fields">
            <NumberField label="Seconds" value={block.seconds} onChange={(seconds) => props.onChange({ seconds } as Partial<WorkoutBlock>)} />
            <label className="toggle-field"><input type="checkbox" checked={block.show_next_exercise} onChange={(event) => props.onChange({ show_next_exercise: event.target.checked } as Partial<WorkoutBlock>)} /> Next</label>
            <label className="toggle-field"><input type="checkbox" checked={block.skip_if_last} onChange={(event) => props.onChange({ skip_if_last: event.target.checked } as Partial<WorkoutBlock>)} /> Skip last</label>
          </div>
        )}
      </div>
      <div className="block-actions">
        <button className="mini-icon" type="button" onClick={props.onDuplicate} aria-label="Duplicate block" title="Duplicate"><Copy size={14} /></button>
        <button className="mini-icon danger" type="button" onClick={props.onDelete} aria-label="Delete block" title="Delete"><Trash2 size={14} /></button>
      </div>
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
}) {
  const filtered = props.exercises.filter((exercise) => {
    const query = props.query.trim().toLowerCase();
    const tagOk = !props.tag || exercise.tags.includes(props.tag);
    const queryOk = !query || [exercise.title, exercise.short_description, exercise.long_description, exercise.tags.join(' ')].join(' ').toLowerCase().includes(query);
    return tagOk && queryOk;
  });
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
        {filtered.map((exercise) => (
          <article key={exercise.id} className="exercise-row">
            <MediaThumb media={exercise.primary_media} />
            <div className="exercise-main">
              <strong>{exercise.title}</strong>
              <span>{exercise.short_description || 'No short description'}</span>
              <small>{exercise.tags.join(' · ') || 'No tags'}</small>
            </div>
            <div className="exercise-actions">
              <button type="button" onClick={() => props.onAddToWorkout(exercise)}>Add</button>
              <button type="button" onClick={() => props.onDraft(exercise)}>Edit</button>
              <button type="button" onClick={() => openStorageForMedia(exercise.primary_media)}>Storage</button>
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
  return (
    <section className="exercise-editor">
      <div className="inline-fields">
        <input value={draft.title || ''} onChange={(event) => update({ title: event.target.value })} placeholder="Exercise title" />
        <button className="icon-button" type="button" onClick={() => props.onDraft(null)} aria-label="Close editor" title="Close"><X size={16} /></button>
      </div>
      <input value={draft.short_description || ''} onChange={(event) => update({ short_description: event.target.value })} placeholder="Short description" />
      <textarea value={draft.long_description || ''} onChange={(event) => update({ long_description: event.target.value })} placeholder="Full description and cues" />
      <input value={(draft.tags || []).join(', ')} onChange={(event) => update({ tags: event.target.value.split(',').map((tag) => tag.trim()).filter(Boolean) })} placeholder="tags, comma separated" />
      <MediaPicker
        media={draft.primary_media || null}
        onChange={(media) => update({ primary_media: media, media: media ? [media] : [] })}
      />
      <div className="editor-actions">
        <button className="secondary-action" type="button" onClick={() => props.onSave(draft)} disabled={props.busy === 'save-exercise'}>
          <Check size={16} aria-hidden="true" />
          <span>Save exercise</span>
        </button>
      </div>
    </section>
  );
}

function MediaPicker({ media, onChange }: { media: ExerciseMediaRef | null; onChange: (media: ExerciseMediaRef | null) => void }) {
  const [files, setFiles] = useState<StorageFile[]>([]);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [manualDrive, setManualDrive] = useState(false);
  const [driveDraft, setDriveDraft] = useState({ stable_storage_file_id: '', connection_id: '', drive_file_id: '', display_path: '', name: '', content_type: 'video/mp4' });

  async function load() {
    setLoading(true);
    setError('');
    try {
      setFiles(await listStorageMedia(query));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Storage catalog unavailable.');
    } finally {
      setLoading(false);
    }
  }

  function useManualDrive() {
    onChange({
      kind: 'drive_file',
      provider: 'google_drive',
      stable_storage_file_id: driveDraft.stable_storage_file_id,
      connection_id: driveDraft.connection_id,
      drive_file_id: driveDraft.drive_file_id,
      display_path: driveDraft.display_path,
      name: driveDraft.name || 'Drive exercise media',
      content_type: driveDraft.content_type,
      preview_kind: driveDraft.content_type.startsWith('image/') ? 'image' : 'video',
      source_version: '',
      etag_or_version: '',
      capabilities: { can_read: true, can_preview: true }
    });
  }

  return (
    <div className="media-picker">
      <div className="media-current">
        <MediaThumb media={media} />
        <div>
          <strong>{media?.name || 'No media selected'}</strong>
          <span>{media?.display_path || 'Use Storage image/video or a Drive Storage ref.'}</span>
        </div>
        <button type="button" onClick={() => openStorageForMedia(media)}>Open Storage</button>
        {media ? <button type="button" onClick={() => onChange(null)}>Clear</button> : null}
      </div>
      <div className="media-catalog-controls">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter Storage media" />
        <button type="button" onClick={load} disabled={loading}>{loading ? 'Loading' : 'Load Storage'}</button>
        <button type="button" onClick={() => setManualDrive((value) => !value)}>Drive ref</button>
      </div>
      {error ? <div className="inline-error">{error}</div> : null}
      {manualDrive ? (
        <div className="drive-ref-grid">
          <input value={driveDraft.stable_storage_file_id} onChange={(event) => setDriveDraft({ ...driveDraft, stable_storage_file_id: event.target.value })} placeholder="stable_storage_file_id" />
          <input value={driveDraft.connection_id} onChange={(event) => setDriveDraft({ ...driveDraft, connection_id: event.target.value })} placeholder="connection_id" />
          <input value={driveDraft.drive_file_id} onChange={(event) => setDriveDraft({ ...driveDraft, drive_file_id: event.target.value })} placeholder="drive_file_id" />
          <input value={driveDraft.display_path} onChange={(event) => setDriveDraft({ ...driveDraft, display_path: event.target.value })} placeholder="display path" />
          <button type="button" onClick={useManualDrive}>Use Drive ref</button>
        </div>
      ) : null}
      {files.length ? (
        <div className="media-results">
          {files.map((file) => {
            const ref = storageFileToMediaRef(file);
            return (
              <button type="button" key={file.file_id || file.id || file.workspace_relative_path} onClick={() => ref && onChange(ref)}>
                <span>{file.name || 'Storage file'}</span>
                <small>{file.preview_kind} · {file.display_path || file.workspace_relative_path}</small>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function WorkPlayer({ workout, onClose, onComplete }: { workout: Workout; onClose: () => void; onComplete: (run: WorkoutRunSummary) => void }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const segments = useMemo(() => runtimeSegmentsForWorkout(workout), [workout]);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [remaining, setRemaining] = useState(segments[0]?.type === 'work' && segments[0].mode === 'reps' ? 0 : segments[0]?.seconds || 0);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [resolution, setResolution] = useState(initialMediaResolution());
  const [summary, setSummary] = useState<WorkoutRunSummary | null>(null);
  const [startedAt] = useState(new Date().toISOString());
  const [skipped, setSkipped] = useState(0);
  const timerTargetRef = useRef(0);
  const beepedRef = useRef<Set<number>>(new Set());
  const pointerStartRef = useRef<{ x: number; y: number } | null>(null);
  const segment = segments[index];

  useEffect(() => {
    rootRef.current?.requestFullscreen?.().catch(() => undefined);
  }, []);

  useEffect(() => {
    setResolution(initialMediaResolution());
    if (!segment) return;
    const media = segment.type === 'work' ? segment.media : nextWorkMedia(segments, index);
    let canceled = false;
    resolveMediaPlayback(media).then((next) => {
      if (!canceled) setResolution(next);
    });
    const nextSegment = segments[index + 1];
    if (nextSegment?.type === 'work') {
      resolveMediaPlayback(nextSegment.media).catch(() => undefined);
    }
    return () => {
      canceled = true;
    };
  }, [index, segment, segments]);

  useEffect(() => {
    if (!segment || paused || segment.type === 'work' && segment.mode === 'reps') return;
    const duration = segment.seconds || 0;
    setRemaining(duration);
    timerTargetRef.current = performance.now() + duration * 1000;
    beepedRef.current = new Set();
    const timer = window.setInterval(() => {
      const next = Math.max(0, Math.ceil((timerTargetRef.current - performance.now()) / 1000));
      setRemaining(next);
      if (next <= 3 && next > 0 && !beepedRef.current.has(next)) {
        beepedRef.current.add(next);
        playTone(520, 0.08);
      }
      if (next === 0) {
        playTone(820, 0.16);
        window.clearInterval(timer);
        advance();
      }
    }, 160);
    return () => window.clearInterval(timer);
  }, [index, paused, segment]);

  useEffect(() => {
    function onVisibility() {
      if (document.hidden) setPaused(true);
    }
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

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

  function handlePointerUp(event: PointerEvent) {
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
            <button type="button" onClick={() => { setSummary(null); setIndex(0); }}>Rifai</button>
            <button type="button" onClick={onClose}>Modifica workout</button>
            <button type="button" onClick={onClose}>Chiudi</button>
          </div>
        </section>
      </main>
    );
  }

  if (!segment) {
    return <main className="work-player"><button onClick={onClose}>Close</button></main>;
  }

  const isReps = segment.type === 'work' && segment.mode === 'reps';
  const counter = segment.type === 'rest' ? `Recupero ${formatClock(remaining)}` : isReps ? segment.repsLabel || 'reps' : formatClock(remaining);
  return (
    <main
      className="work-player"
      ref={rootRef}
      onPointerDown={(event) => { pointerStartRef.current = { x: event.clientX, y: event.clientY }; }}
      onPointerUp={handlePointerUp}
    >
      <div className="player-media" onClick={() => setPaused((value) => !value)}>
        {resolution.status === 'ready' && resolution.mediaKind === 'video' ? (
          <video src={resolution.url} muted autoPlay loop playsInline onError={fallbackBlob} />
        ) : resolution.status === 'ready' && resolution.mediaKind === 'image' ? (
          <img src={resolution.url} alt="" onError={fallbackBlob} />
        ) : (
          <div className="media-placeholder">
            <Dumbbell size={42} />
            <span>{resolution.detail || 'Resolving Storage media'}</span>
          </div>
        )}
      </div>
      <div className="player-scrim" />
      <div className="player-progress" aria-label="Workout progress">
        {segments.map((item, itemIndex) => <span key={`${item.blockId}-${itemIndex}`} className={itemIndex < index ? 'is-done' : itemIndex === index ? 'is-current' : ''} />)}
      </div>
      <div className="player-top">
        <button className="player-icon" type="button" onClick={onClose} aria-label="Close player"><ArrowLeft size={20} /></button>
        <button className="player-icon" type="button" onClick={() => setPaused((value) => !value)} aria-label={paused ? 'Resume' : 'Pause'}>{paused ? <Play size={20} /> : <Pause size={20} />}</button>
        <span className="counter-pill">{counter}</span>
      </div>
      <button className="player-caption" type="button" onClick={() => setSheetOpen(true)}>
        <strong>{segment.title}</strong>
        <span>{segment.short_description}</span>
      </button>
      <div className="player-bottom-actions">
        <button type="button" onClick={previous}>Prev</button>
        <button type="button" onClick={() => advance(true)}>{isReps ? 'Done' : 'Skip'}</button>
      </div>
      {resolution.status === 'error' ? (
        <div className="player-error">
          <span>{resolution.detail}</span>
          {resolution.canRetry ? <button type="button" onClick={() => setIndex((value) => value)}>Retry</button> : null}
        </div>
      ) : null}
      {sheetOpen ? (
        <div className="sheet-backdrop" onClick={() => setSheetOpen(false)}>
          <section className="description-sheet" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <button className="icon-button" type="button" onClick={() => setSheetOpen(false)} aria-label="Close details"><X size={16} /></button>
            <h2>{segment.title}</h2>
            <p>{segment.long_description}</p>
            <small>{counter}</small>
          </section>
        </div>
      ) : null}
    </main>
  );
}

function MediaThumb({ media }: { media: ExerciseMediaRef | null }) {
  return (
    <div className={`media-thumb ${media ? '' : 'is-empty'}`}>
      {media?.preview_kind === 'video' ? <Play size={18} aria-hidden="true" /> : media ? <Library size={18} aria-hidden="true" /> : <MoreHorizontal size={18} aria-hidden="true" />}
    </div>
  );
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="number-field">
      <span>{label}</span>
      <input type="number" min={0} value={value} onChange={(event) => onChange(Math.max(0, Number(event.target.value) || 0))} />
    </label>
  );
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
    title: 'Recupero',
    short_description: 'Preparati al prossimo esercizio.',
    long_description: 'Respira, riposizionati e guarda il prossimo movimento.',
    seconds,
    show_next_exercise: true,
    skip_if_last: true
  };
}

function workBlockFromExercise(exercise: Exercise, workout: Workout): WorkBlock {
  return {
    id: crypto.randomUUID(),
    type: 'work',
    exercise_id: exercise.id,
    exercise_snapshot_updated_at: exercise.updated_at,
    title: exercise.title,
    short_description: exercise.short_description,
    long_description: exercise.long_description,
    tags: exercise.tags,
    mode: 'timer',
    seconds: workout.default_work_seconds,
    reps: workout.default_reps,
    reps_label: null,
    media: exercise.primary_media,
    notes: null
  };
}

function replaceById<T extends { id: string }>(items: T[], next: T) {
  const exists = items.some((item) => item.id === next.id);
  return exists ? items.map((item) => (item.id === next.id ? next : item)) : [next, ...items];
}

function insertAfter<T extends { id: string }>(items: T[], id: string, next: T) {
  const index = items.findIndex((item) => item.id === id);
  if (index < 0) return [...items, next];
  return [...items.slice(0, index + 1), next, ...items.slice(index + 1)];
}

function nextWorkMedia(segments: RuntimeSegment[], index: number): ExerciseMediaRef | null {
  const next = segments.slice(index + 1).find((item) => item.type === 'work');
  return next?.type === 'work' ? next.media : null;
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

function playTone(frequency: number, duration: number) {
  try {
    const audioContext = new AudioContext();
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
