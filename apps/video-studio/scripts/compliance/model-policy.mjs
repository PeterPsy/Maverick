export function inspectModelInventory(modelInventory, policy) {
  if (
    modelInventory?.schema_version !== 1 ||
    !Array.isArray(modelInventory.models) ||
    policy?.unreviewed_models_allowed !== false ||
    policy?.required_digest !== "sha256" ||
    !Array.isArray(policy?.forbidden_revisions)
  ) {
    return ["model inventory or fail-closed model policy is missing or malformed"];
  }

  const errors = [];
  const seen = new Set();
  for (const model of modelInventory.models) {
    if (!model.id || seen.has(model.id)) {
      errors.push(`model id is missing or duplicated: ${model.id ?? "<missing>"}`);
    }
    seen.add(model.id);
    if (typeof model.source_url !== "string" || !model.source_url.startsWith("https://")) {
      errors.push(`${model.id} requires an HTTPS source URL`);
    }
    if (typeof model.model_card_url !== "string" || !model.model_card_url.startsWith("https://")) {
      errors.push(`${model.id} requires an HTTPS model card URL`);
    }
    if (
      typeof model.revision !== "string" ||
      !model.revision ||
      policy.forbidden_revisions.includes(model.revision.toLowerCase())
    ) {
      errors.push(`${model.id} requires an immutable exact revision`);
    }
    for (const field of ["code_license", "weights_license", "tokenizer_version"]) {
      if (typeof model[field] !== "string" || !model[field]) {
        errors.push(`${model.id} requires ${field}`);
      }
    }
    if (!Array.isArray(model.files) || model.files.length === 0) {
      errors.push(`${model.id} requires content-addressed model files`);
    }
    for (const file of model.files ?? []) {
      if (
        typeof file.path !== "string" ||
        !file.path ||
        !/^[a-f0-9]{64}$/.test(file.sha256 ?? "")
      ) {
        errors.push(`${model.id} has a model file without valid path and sha256`);
      }
    }
  }
  return errors;
}
