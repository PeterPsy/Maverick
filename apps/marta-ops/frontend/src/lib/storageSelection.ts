type StoragePickerFile = {
  workspace_relative_path?: unknown;
};

type StoragePickerResult = {
  file?: StoragePickerFile;
};

export type StorageSelection = {
  workId: string;
  workspaceRelativePath: string;
  requestKey: string;
};

export function storageSelectionFromParams(
  params: Record<string, unknown>,
): StorageSelection | null {
  if (params.picker_mode !== "workspace-file") return null;
  const workId = scalar(params.picker_context).slice(0, 80);
  const encoded = scalar(params.storage_picker_result);
  if (!workId || !encoded) return null;
  let result: StoragePickerResult;
  try {
    result = JSON.parse(encoded) as StoragePickerResult;
  } catch {
    return null;
  }
  const workspaceRelativePath = scalar(
    result?.file?.workspace_relative_path,
  ).slice(0, 1000);
  if (
    !workspaceRelativePath.startsWith("storage/uploaded/") &&
    !workspaceRelativePath.startsWith("storage/generated/")
  )
    return null;
  return {
    workId,
    workspaceRelativePath,
    requestKey: `storage:${workId}:${workspaceRelativePath}`,
  };
}

function scalar(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}
