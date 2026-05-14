export type FileDropDataTransfer = {
  files?: ArrayLike<File> | null;
  types?: ArrayLike<string> | null;
};

export function hasFileDropData(dataTransfer: FileDropDataTransfer): boolean {
  return Array.from(dataTransfer.types ?? []).some((type) => type.toLowerCase() === "files");
}

export function filesFromDataTransfer(dataTransfer: FileDropDataTransfer): File[] {
  return Array.from(dataTransfer.files ?? []).filter((file): file is File => file instanceof File);
}
