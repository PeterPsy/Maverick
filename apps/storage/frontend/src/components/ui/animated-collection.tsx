"use client";

import {
  AnimatePresence,
  LayoutGroup,
  motion,
  type Transition,
} from "motion/react";
import { useState, type DragEvent } from "react";
import {
  CheckmarkCircle02Icon,
  Delete02Icon,
  Doc01Icon,
  Download04Icon,
  File01Icon,
  FileAudioIcon,
  FileCodeIcon,
  FileImageIcon,
  FileSpreadsheetIcon,
  FileVideoIcon,
  GridViewIcon,
  InformationCircleIcon,
  Note01Icon,
  Pdf01Icon,
  Playlist01Icon,
  Presentation01Icon,
  TextIcon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { FileCardPreview } from "@/filePreview";
import { useLongPressSelection } from "@/hooks/useLongPressSelection";
import { formatBytes, formatStorageTimestamp, kindLabels, roleLabels } from "@/storageMeta";
import { cn } from "@/lib/utils";
import type { StorageFile, PreviewKind } from "@/types";

export type CollectionViewMode = "list" | "card";

type AnimatedFileCollectionProps = {
  files: StorageFile[];
  draggingFileIds: Set<string>;
  onDelete: (file: StorageFile) => void;
  onDownload: (file: StorageFile) => void;
  onDragEnd: () => void;
  onDragStart: (event: DragEvent<HTMLDivElement>, file: StorageFile) => number | void;
  onLongPress: (file: StorageFile) => void;
  onOpen: (file: StorageFile) => void;
  onShowDetails: (file: StorageFile) => void;
  onToggleSelection: (file: StorageFile) => void;
  selectedFileId?: string;
  selectedFileIds: Set<string>;
  selectionMode: boolean;
  view: CollectionViewMode;
};

type CollectionViewToggleProps = {
  onChange: (view: CollectionViewMode) => void;
  view: CollectionViewMode;
};

type HugeIconDefinition = typeof Playlist01Icon;

const kindIcons: Record<PreviewKind, HugeIconDefinition> = {
  audio: FileAudioIcon,
  document: Doc01Icon,
  file: File01Icon,
  image: FileImageIcon,
  markdown: Note01Icon,
  pdf: Pdf01Icon,
  presentation: Presentation01Icon,
  spreadsheet: FileSpreadsheetIcon,
  text: TextIcon,
  video: FileVideoIcon,
};

const snappySpring: Transition = {
  type: "spring",
  stiffness: 350,
  damping: 30,
  mass: 1,
};

const fastFade: Transition = {
  duration: 0.1,
  ease: "linear",
};

const FILE_DRAG_IMAGE_SIZE = 58;

export function CollectionViewToggle({ onChange, view }: CollectionViewToggleProps) {
  return (
    <div className="collection-view-toggle" aria-label="View mode">
      <Tab
        active={view === "list"}
        onClick={() => onChange("list")}
        icon={Playlist01Icon}
        label="List view"
      />
      <Tab
        active={view === "card"}
        onClick={() => onChange("card")}
        icon={GridViewIcon}
        label="Card view"
      />
    </div>
  );
}

export function AnimatedFileCollection({
  files,
  draggingFileIds,
  onDelete,
  onDownload,
  onDragEnd,
  onDragStart,
  onLongPress,
  onOpen,
  onShowDetails,
  onToggleSelection,
  selectedFileId,
  selectedFileIds,
  selectionMode,
  view,
}: AnimatedFileCollectionProps) {
  const [draggingFileId, setDraggingFileId] = useState<string | null>(null);

  function handleDragStart(event: DragEvent<HTMLDivElement>, file: StorageFile) {
    setDraggingFileId(file.id);
    const movingCount = onDragStart(event, file) || 1;
    attachCompactFileDragImage(event, movingCount);
  }

  function handleDragEnd() {
    setDraggingFileId(null);
    onDragEnd();
  }

  return (
    <LayoutGroup>
      <motion.div
        layout
        transition={snappySpring}
        className={cn(
          "animated-file-collection",
          view === "list" && "is-list",
          view === "card" && "is-card",
        )}
      >
        {files.map((file) => (
          <AnimatedFileItem
            file={file}
            key={file.id}
            onDelete={onDelete}
            onDownload={onDownload}
            onDragEnd={handleDragEnd}
            onDragStart={handleDragStart}
            onLongPress={onLongPress}
            onOpen={onOpen}
            onShowDetails={onShowDetails}
            onToggleSelection={onToggleSelection}
            dragging={draggingFileId === file.id || draggingFileIds.has(file.id)}
            selected={selectedFileIds.has(file.id)}
            selectedFileId={selectedFileId}
            selectionMode={selectionMode}
            view={view}
          />
        ))}
      </motion.div>
    </LayoutGroup>
  );
}

function AnimatedFileItem({
  dragging,
  file,
  onDelete,
  onDownload,
  onDragEnd,
  onDragStart,
  onLongPress,
  onOpen,
  onShowDetails,
  onToggleSelection,
  selected,
  selectedFileId,
  selectionMode,
  view,
}: {
  dragging: boolean;
  file: StorageFile;
  onDelete: (file: StorageFile) => void;
  onDownload: (file: StorageFile) => void;
  onDragEnd: () => void;
  onDragStart: (event: DragEvent<HTMLDivElement>, file: StorageFile) => number | void;
  onLongPress: (file: StorageFile) => void;
  onOpen: (file: StorageFile) => void;
  onShowDetails: (file: StorageFile) => void;
  onToggleSelection: (file: StorageFile) => void;
  selected: boolean;
  selectedFileId?: string;
  selectionMode: boolean;
  view: CollectionViewMode;
}) {
  const canRead = file.capabilities ? Boolean(file.capabilities.can_read) : true;
  const canDelete = file.capabilities ? Boolean(file.capabilities.can_delete) : true;
  const canMove = file.provider === "google_drive" ? false : file.capabilities ? Boolean(file.capabilities.can_move) : true;
  const timestamp = file.created_at || file.modified_at;
  const timestampLabel = formatStorageTimestamp(timestamp, {
    fallback: file.provider === "google_drive" ? "Drive" : roleLabels[file.role as keyof typeof roleLabels],
  });
  const { cancelLongPress, longPressHandlers } = useLongPressSelection({
    disabled: !canMove,
    item: file,
    onLongPress,
    shouldIgnoreTarget: isFileLongPressIgnored,
  });

  function handleOpen() {
    if (selectionMode) {
      onToggleSelection(file);
      return;
    }
    onOpen(file);
  }

  function handleDragStart(event: DragEvent<HTMLDivElement>) {
    cancelLongPress();
    if (!canMove) {
      event.preventDefault();
      return;
    }
    onDragStart(event, file);
  }

  return (
    <motion.div
      key={file.id}
      layout
      transition={snappySpring}
      className={cn(
        "animated-file-item",
        view === "list" && "is-list",
        view === "card" && "is-card",
        selectedFileId === file.id && "selected",
        selectionMode && "selection-mode",
        selected && "selection-selected",
        dragging && "is-dragging",
      )}
      style={{ zIndex: 1 }}
      animate={{ rotate: 0, x: 0, y: 0 }}
      draggable={canMove}
      onDragEnd={onDragEnd}
      onDragStartCapture={handleDragStart}
      {...longPressHandlers}
    >
      {selectionMode ? (
        <button
          aria-label={`${selected ? "Deselect" : "Select"} ${file.name}`}
          aria-pressed={selected}
          className={cn("storage-selection-toggle", selected && "selected")}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onToggleSelection(file);
          }}
          type="button"
        >
          <span className="storage-selection-toggle-box">
            {selected ? <HugeiconsIcon icon={CheckmarkCircle02Icon} size={15} /> : null}
          </span>
        </button>
      ) : null}

      <motion.button
        layout
        transition={snappySpring}
        className={cn(
          "animated-file-preview-button",
          file.preview_kind === "image" && "is-image-preview",
        )}
        aria-label={selectionMode ? `${selected ? "Deselect" : "Select"} ${file.name}` : `Open ${file.name}`}
        onClick={handleOpen}
        type="button"
      >
        <span className="animated-file-preview">
          <FileCardPreview file={file} />
        </span>
      </motion.button>

      <AnimatePresence mode="popLayout" initial={false}>
        <motion.div
          key={`${file.id}-info`}
          layout
          initial={{
            opacity: 0,
            scale: 0.9,
            filter: "blur(4px)",
          }}
          animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
          exit={{ opacity: 0, scale: 0.9, filter: "blur(4px)" }}
          transition={fastFade}
          className={cn(
            "animated-file-info",
            view === "card" ? "is-card" : "is-list",
          )}
        >
          <button
            className="animated-file-copy"
            onClick={handleOpen}
            type="button"
          >
            <motion.h3 layout>{file.name}</motion.h3>
            <motion.div layout className="animated-file-subtitle">
              <HugeiconsIcon
                icon={kindIcons[file.preview_kind] || FileCodeIcon}
                size={12}
                className="animated-file-kind-icon"
              />
              <span>
                {kindLabels[file.preview_kind]} · {formatBytes(file.size_bytes)}
              </span>
            </motion.div>
          </button>

          <motion.div layout className="animated-file-trailing">
            <div className="animated-file-actions" aria-label={`Actions for ${file.name}`}>
              <button
                className="animated-file-action"
                aria-label={`Show details for ${file.name}`}
                onClick={() => onShowDetails(file)}
                type="button"
              >
                <HugeiconsIcon icon={InformationCircleIcon} size={16} />
              </button>
              <button
                className="animated-file-action"
                aria-label={`Download ${file.name}`}
                disabled={!canRead}
                onClick={() => onDownload(file)}
                type="button"
              >
                <HugeiconsIcon icon={Download04Icon} size={16} />
              </button>
              <button
                className="animated-file-action danger"
                aria-label={`Delete ${file.name}`}
                disabled={!canDelete}
                onClick={() => onDelete(file)}
                type="button"
              >
                <HugeiconsIcon icon={Delete02Icon} size={16} />
              </button>
            </div>
            <span className={cn("animated-file-role-badge", file.role || file.provider)} title={timestampLabel}>
              {timestampLabel}
            </span>
          </motion.div>
        </motion.div>
      </AnimatePresence>

      {view === "list" && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="animated-file-divider"
        />
      )}
    </motion.div>
  );
}

function isFileLongPressIgnored(target: EventTarget | null) {
  const element = target instanceof Element ? target : null;
  return Boolean(element?.closest(".animated-file-actions, .storage-selection-toggle"));
}

function attachCompactFileDragImage(event: DragEvent<HTMLDivElement>, movingCount = 1) {
  const preview = event.currentTarget.querySelector<HTMLElement>(".animated-file-preview");
  if (!preview || !event.dataTransfer.setDragImage) {
    return;
  }
  const dragImage = document.createElement("div");
  dragImage.className = "storage-file-drag-image";
  dragImage.style.width = `${FILE_DRAG_IMAGE_SIZE}px`;
  dragImage.style.height = `${FILE_DRAG_IMAGE_SIZE}px`;

  const previewClone = preview.cloneNode(true) as HTMLElement;
  dragImage.appendChild(previewClone);
  appendDragCountBadge(dragImage, movingCount);
  document.body.appendChild(dragImage);
  event.dataTransfer.setDragImage(
    dragImage,
    Math.round(FILE_DRAG_IMAGE_SIZE / 2),
    Math.round(FILE_DRAG_IMAGE_SIZE / 2),
  );
  window.setTimeout(() => dragImage.remove(), 0);
}

function appendDragCountBadge(dragImage: HTMLElement, movingCount: number) {
  if (movingCount <= 1) {
    return;
  }
  const badge = document.createElement("span");
  badge.className = "storage-drag-count-badge";
  badge.textContent = `+${movingCount}`;
  dragImage.appendChild(badge);
}

function Tab({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: HugeIconDefinition;
  label: string;
}) {
  return (
    <button
      aria-label={label}
      onClick={onClick}
      className={cn(
        "collection-view-tab",
        active ? "selected" : "unselected",
      )}
      title={label}
      type="button"
    >
      {active && (
        <motion.div
          layoutId="active-tab"
          className="collection-view-tab-active"
          transition={snappySpring}
        />
      )}
      <span className="collection-view-tab-content">
        <HugeiconsIcon
          icon={icon}
          size={16}
          className={cn("collection-view-tab-icon", active && "selected")}
        />
        <span className="collection-view-tab-label">{label}</span>
      </span>
    </button>
  );
}

export default AnimatedFileCollection;
