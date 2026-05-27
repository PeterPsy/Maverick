export function SecureSecretInput({ label, placeholder = 'Value', required = true }: { label: string; placeholder?: string; required?: boolean }) {
  return (
    <label className="vault-secure-input">
      <span>{label}</span>
      <input
        name="raw_value"
        placeholder={placeholder}
        type="password"
        required={required}
        autoComplete="new-password"
        spellCheck={false}
      />
    </label>
  );
}
