"use client";

import {
  AnimatePresence,
  LayoutGroup,
  motion,
  type Transition,
} from "motion/react";
import { useState, type DragEvent } from "react";
import {
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
import { formatBytes, kindLabels, roleLabels } from "@/storageMeta";
import { cn } from "@/lib/utils";
import type { StorageFile, PreviewKind } from "@/types";

export type CollectionViewMode = "list" | "card";

type AnimatedFileCollectionProps = {
  files: StorageFile[];
  onDelete: (file: StorageFile) => void;
  onDownload: (file: StorageFile) => void;
  onDragEnd: () => void;
  onDragStart: (event: DragEvent<HTMLDivElement>, file: StorageFile) => void;
  onOpen: (file: StorageFile) => void;
  onShowDetails: (file: StorageFile) => void;
  selectedFileId?: string;
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
  onDelete,
  onDownload,
  onDragEnd,
  onDragStart,
  onOpen,
  onShowDetails,
  selectedFileId,
  view,
}: AnimatedFileCollectionProps) {
  const [draggingFileId, setDraggingFileId] = useState<string | null>(null);

  function handleDragStart(event: DragEvent<HTMLDivElement>, file: StorageFile) {
    setDraggingFileId(file.id);
    attachCompactFileDragImage(event);
    onDragStart(event, file);
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
          <motion.div
            key={file.id}
            layout
            transition={snappySpring}
            className={cn(
              "animated-file-item",
              view === "list" && "is-list",
              view === "card" && "is-card",
              selectedFileId === file.id && "selected",
              draggingFileId === file.id && "is-dragging",
            )}
            style={{ zIndex: 1 }}
            animate={{ rotate: 0, x: 0, y: 0 }}
            draggable
            onDragEnd={handleDragEnd}
            onDragStartCapture={(event) => handleDragStart(event, file)}
          >
            <motion.button
              layout
              transition={snappySpring}
              className={cn(
                "animated-file-preview-button",
                file.preview_kind === "image" && "is-image-preview",
              )}
              aria-label={`Open ${file.name}`}
              onClick={() => onOpen(file)}
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
                  onClick={() => onOpen(file)}
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
                      onClick={() => onDownload(file)}
                      type="button"
                    >
                      <HugeiconsIcon icon={Download04Icon} size={16} />
                    </button>
                    <button
                      className="animated-file-action danger"
                      aria-label={`Delete ${file.name}`}
                      onClick={() => onDelete(file)}
                      type="button"
                    >
                      <HugeiconsIcon icon={Delete02Icon} size={16} />
                    </button>
                  </div>
                  <span className={cn("animated-file-role-badge", file.role)}>
                    {roleLabels[file.role]}
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
        ))}
      </motion.div>
    </LayoutGroup>
  );
}

function attachCompactFileDragImage(event: DragEvent<HTMLDivElement>) {
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
  document.body.appendChild(dragImage);
  event.dataTransfer.setDragImage(
    dragImage,
    Math.round(FILE_DRAG_IMAGE_SIZE / 2),
    Math.round(FILE_DRAG_IMAGE_SIZE / 2),
  );
  window.setTimeout(() => dragImage.remove(), 0);
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
