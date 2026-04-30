import { FormEvent, useState } from "react";
import { login, SessionPayload } from "../api";
import { BrandMark } from "./BrandMark";
import { Button, Surface } from "../ui";

export function LoginScreen({ onAuthenticated }: { onAuthenticated: (session: Extract<SessionPayload, { authenticated: true }>) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const session = await login(username, password);
      if (!session.authenticated) {
        setError("Accesso non riuscito.");
        return;
      }
      onAuthenticated(session);
    } catch {
      setError("Credenziali non valide.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="bs-login">
      <Surface className="bs-login__panel">
        <BrandMark className="bs-login__brand" />
        <p className="bs-eyebrow">Maverick</p>
        <h1 className="bs-login__title">Accedi alla shell</h1>
        <p className="bs-login__copy">La shell usa sessioni core e monta solo app abilitate nel workspace attivo.</p>
        <form className="bs-login__form" onSubmit={submit}>
          <label className="bs-form-field">
            <span>Username</span>
            <input autoComplete="username" onChange={(event) => setUsername(event.target.value)} required value={username} />
          </label>
          <label className="bs-form-field">
            <span>Password</span>
            <input
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Password admin"
              required
              type="password"
              value={password}
            />
          </label>
          {error ? <p className="bs-form-error">{error}</p> : null}
          <Button fullWidth loading={isSubmitting} type="submit" variant="primary">
            Entra
          </Button>
        </form>
      </Surface>
    </main>
  );
}
