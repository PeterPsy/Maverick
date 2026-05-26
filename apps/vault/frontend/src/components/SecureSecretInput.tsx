export function SecureSecretInput({ label }: { label: string }) {
  return (
    <label className="vault-secure-input">
      <span>{label}</span>
      <input
        name="raw_value"
        placeholder="Value"
        type="password"
        required
        autoComplete="new-password"
        spellCheck={false}
      />
    </label>
  );
}
