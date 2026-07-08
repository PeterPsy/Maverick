import { FormEvent, lazy, Suspense, useEffect, useRef, useState } from "react";
import { login, SessionPayload } from "../api";
import { BrandMark } from "./BrandMark";

type LoginStep = "email" | "password";

const LoginPaperBackground = lazy(() =>
  import("./LoginPaperBackground").then((module) => ({ default: module.LoginPaperBackground })),
);

export function LoginScreen({ onAuthenticated }: { onAuthenticated: (session: Extract<SessionPayload, { authenticated: true }>) => void }) {
  const [credential, setCredential] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [step, setStep] = useState<LoginStep>("email");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const passwordInputRef = useRef<HTMLInputElement>(null);
  const canContinue = credential.trim().length > 0;
  const canSubmit = credential.trim().length > 0 && password.length > 0;
  const errorId = error ? "maverick-login-error" : undefined;

  useEffect(() => {
    if (step === "password") {
      const focusTimer = window.setTimeout(() => passwordInputRef.current?.focus(), 280);
      return () => window.clearTimeout(focusTimer);
    }
    return undefined;
  }, [step]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (step === "email") {
      if (canContinue) {
        setError(null);
        setStep("password");
      }
      return;
    }
    if (!canSubmit || isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const session = await login(credential.trim(), password);
      if (!session.authenticated) {
        setError("Sign-in failed.");
        return;
      }
      onAuthenticated(session);
    } catch {
      setError("Invalid credentials.");
    } finally {
      setIsSubmitting(false);
    }
  }

  function goBackToEmail() {
    if (isSubmitting) return;
    setError(null);
    setPassword("");
    setShowPassword(false);
    setStep("email");
  }

  return (
    <main className="bs-login">
      <Suspense fallback={<div className="bs-login-paper-bg is-static" aria-hidden="true" />}>
        <LoginPaperBackground />
      </Suspense>
      <div className="bs-login__brand-strip">
        <BrandMark className="bs-login__brand-mark" variant="mark" />
      </div>
      <section className="bs-login__stage" aria-label="Maverick sign-in">
        <div className="bs-login__content">
          <form className="bs-login__form" onSubmit={submit}>
            <div className="bs-login__step" key={step}>
              <div className="bs-login__headline" aria-live="polite">
                {step === "email" ? (
                  <p>
                    <BrandMark className="bs-login__headline-logotype" variant="logotype" />
                    <span>was waiting for you.</span>
                  </p>
                ) : (
                  <p>Enter your password</p>
                )}
                {step === "password" ? <span className="bs-login__credential">{credential.trim()}</span> : null}
              </div>

              <div className="bs-login__fields">
                {step === "email" ? (
                  <div className="bs-glass-field">
                    <label className="bs-glass-field__floating" htmlFor="maverick-login-credential">Email or username</label>
                    <span className="bs-glass-field__control">
                      <span className={`bs-glass-field__icon ${credential.length > 20 ? "is-compressed" : ""}`}>
                        <span className="material-symbols-rounded" aria-hidden="true">mail</span>
                      </span>
                      <input
                        aria-describedby={errorId}
                        aria-invalid={!!error}
                        autoComplete="username"
                        id="maverick-login-credential"
                        onChange={(event) => {
                          setCredential(event.target.value);
                          setError(null);
                        }}
                        placeholder="Email or username"
                        spellCheck={false}
                        type="text"
                        value={credential}
                      />
                      <button
                        aria-label="Continue"
                        className={`bs-glass-field__action ${canContinue ? "is-visible" : ""}`}
                        disabled={!canContinue}
                        type="submit"
                      >
                        <span className="material-symbols-rounded" aria-hidden="true">arrow_forward</span>
                        <span>Continue</span>
                      </button>
                    </span>
                  </div>
                ) : (
                  <div className="bs-glass-field">
                    <label className={`bs-glass-field__floating ${password ? "is-visible" : ""}`} htmlFor="maverick-login-password">Password</label>
                    <span className="bs-glass-field__control">
                      <button
                        aria-label={showPassword ? "Hide password" : "Show password"}
                        className="bs-glass-field__icon bs-glass-field__toggle"
                        onClick={() => setShowPassword((value) => !value)}
                        type="button"
                      >
                        <span className="material-symbols-rounded" aria-hidden="true">
                          {showPassword ? "visibility_off" : "visibility"}
                        </span>
                      </button>
                      <input
                        aria-describedby={errorId}
                        aria-invalid={!!error}
                        autoComplete="current-password"
                        id="maverick-login-password"
                        onChange={(event) => {
                          setPassword(event.target.value);
                          setError(null);
                        }}
                        placeholder="Password"
                        ref={passwordInputRef}
                        type={showPassword ? "text" : "password"}
                        value={password}
                      />
                      <button
                        aria-label="Sign in"
                        className={`bs-glass-field__action ${canSubmit ? "is-visible" : ""}`}
                        disabled={!canSubmit || isSubmitting}
                        type="submit"
                      >
                        {isSubmitting ? (
                          <>
                            <span className="bs-login__spinner" />
                            <span>Signing in...</span>
                          </>
                        ) : (
                          <>
                            <span className="material-symbols-rounded" aria-hidden="true">arrow_forward</span>
                            <span>Sign in</span>
                          </>
                        )}
                      </button>
                    </span>
                    <button className="bs-login__back" onClick={goBackToEmail} type="button">
                      <span className="material-symbols-rounded" aria-hidden="true">arrow_back</span>
                      Back
                    </button>
                  </div>
                )}
              </div>
            </div>

            {error ? <p className="bs-form-error" id="maverick-login-error" role="alert">{error}</p> : null}
          </form>
        </div>
      </section>
    </main>
  );
}
