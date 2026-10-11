import { FormEvent, lazy, Suspense, useEffect, useRef, useState } from "react";
import { login, getSession, googleStatus, startGoogle, type GoogleStatus, type SessionPayload } from "../api";
import { GoogleMark, GOOGLE_SERVICES, googleCallbackMessage } from "./GoogleServices";
import { GoogleAuthError } from "../lib/googleAuth";
import { BrandMark } from "./BrandMark";
import { ServerProfilesLauncher } from "./ServerProfilesPanel";

const LoginPaperBackground = lazy(() =>
  import("./LoginPaperBackground").then(module => ({ default: module.LoginPaperBackground })),
);

export function LoginScreen({ onAuthenticated, callbackError = null }: {
  onAuthenticated: (session: Extract<SessionPayload, { authenticated: true }>) => void;
  callbackError?: string | null;
}) {
  const [credential, setCredential] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [step, setStep] = useState<"email" | "password">("email");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(() => googleCallbackMessage(callbackError ?? new URL(window.location.href).searchParams.get("google_error")));
  const [google, setGoogle] = useState<GoogleStatus | null>(null);
  const [googlePending, setGooglePending] = useState(false);
  const googleController = useRef<AbortController | null>(null);
  const alive = useRef(true);
  const passwordInput = useRef<HTMLInputElement>(null);
  const canContinue = credential.trim().length > 0;
  const canSubmit = canContinue && password.length > 0;
  const errorId = error ? "maverick-login-error" : undefined;
  const requestedServices = GOOGLE_SERVICES.filter(service => google?.login_services.includes(service.id));

  function cancelGoogle() {
    const controller = googleController.current;
    googleController.current = null;
    controller?.abort();
    setGooglePending(false); setIsSubmitting(false);
  }

  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    googleStatus(controller.signal).then(result => { if (!controller.signal.aborted) setGoogle(result); }).catch(() => {});
    const url = new URL(window.location.href);
    if (url.searchParams.has("google_error")) {
      url.searchParams.delete("google_error"); window.history.replaceState(null, "", url);
    }
    const restore = (event: PageTransitionEvent) => {
      if (event.persisted && !googleController.current) { setIsSubmitting(false); setGooglePending(false); }
    };
    window.addEventListener("pageshow", restore);
    return () => {
      alive.current = false; controller.abort(); googleController.current?.abort(); googleController.current = null;
      window.removeEventListener("pageshow", restore);
    };
  }, []);

  useEffect(() => { if (step === "password") passwordInput.current?.focus(); }, [step]);

  async function signInGoogle() {
    if (isSubmitting || !google?.configured) return;
    const controller = new AbortController(); googleController.current = controller;
    const current = () => alive.current && googleController.current === controller && !controller.signal.aborted;
    setIsSubmitting(true); setGooglePending(true); setError(null);
    try {
      const result = await startGoogle("login", google.login_services, controller.signal);
      if (result === "completed" && current()) {
        const session = await getSession(controller.signal);
        if (!current()) return;
        if (!session.authenticated) throw new GoogleAuthError("google_flow_invalid");
        setGooglePending(false); setIsSubmitting(false); onAuthenticated(session);
      }
    } catch (reason) {
      if (current()) {
        setError(reason instanceof GoogleAuthError ? googleCallbackMessage(reason.code) : "Unable to complete Google sign-in. Please try again.");
        setIsSubmitting(false); setGooglePending(false);
      }
    } finally { if (googleController.current === controller) googleController.current = null; }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (isSubmitting) return;
    if (step === "email") {
      if (canContinue) { setError(null); setStep("password"); }
      return;
    }
    if (!canSubmit) return;
    setIsSubmitting(true); setError(null);
    try {
      const session = await login(credential.trim(), password);
      if (!alive.current) return;
      if (!session.authenticated) { setError("Sign-in failed. Please try again."); return; }
      onAuthenticated(session);
    } catch { if (alive.current) setError("Invalid credentials. Check your username and password."); }
    finally { if (alive.current) setIsSubmitting(false); }
  }

  return <main className="bs-login">
    <Suspense fallback={<div className="bs-login-paper-bg is-static" aria-hidden="true" />}><LoginPaperBackground /></Suspense>
    <div className="bs-login__brand-strip"><BrandMark className="bs-login__brand-mark" variant="mark" /></div>
    <ServerProfilesLauncher beforeSwitch={cancelGoogle} />
    <section className="bs-login__stage" aria-label="Maverick sign-in">
      <div className="bs-login__content">
        <div className="bs-login__welcome">
          <BrandMark className="bs-login__headline-logotype" variant="logotype" />
          <h1>Welcome back.</h1><p>Your apps. Your workspace. One connection.</p>
        </div>
        <form className="bs-login__form" onSubmit={submit} aria-busy={isSubmitting}>
          {step === "email" ? <div className="bs-login__google">
            <button className="bs-google-button" type="button" disabled={isSubmitting || !google?.configured} onClick={() => void signInGoogle()}>
              <GoogleMark /><span>{googlePending ? "Connecting…" : "Continue with Google"}</span>
            </button>
            {google?.configured && <div className="bs-login__services">
              {requestedServices.length > 0 && <><p>Connect the services your apps use</p>
                <ul aria-label="Google services requested at sign-in">{requestedServices.map(service => <li key={service.id}>
                  <span className="material-symbols-rounded" aria-hidden="true">{service.id === "calendar" ? "calendar_month" : service.id === "gmail" ? "mail" : "folder"}</span>{service.label}
                </li>)}</ul>
                <small>Approve access once with Google. Manage accounts and app permissions in your profile anytime.</small>
              </>}
            </div>}
            {google && !google.configured && <small>Google sign-in is not configured on this installation.</small>}
          </div> : <div className="bs-login__password-heading"><h2>Sign in with your password</h2><p>{credential.trim()}</p></div>}
          {step === "email" && <div className="bs-login__divider"><span>or use your Maverick account</span></div>}
          <div className="bs-login__fields">
            <label htmlFor={step === "email" ? "maverick-login-credential" : "maverick-login-password"}>{step === "email" ? "Email or username" : "Password"}</label>
            <div className="bs-login__input-wrap">
              <span className="material-symbols-rounded" aria-hidden="true">{step === "email" ? "person" : "lock"}</span>
              {step === "email" ? <input id="maverick-login-credential" autoComplete="username" type="text" value={credential}
                aria-describedby={errorId} aria-invalid={!!error} disabled={isSubmitting} placeholder="you@example.com" spellCheck={false}
                onChange={event => { setCredential(event.target.value); setError(null); }} />
                : <><input id="maverick-login-password" autoComplete="current-password" type={showPassword ? "text" : "password"}
                  value={password} ref={passwordInput} aria-describedby={errorId} aria-invalid={!!error} disabled={isSubmitting} placeholder="Enter your password"
                  onChange={event => { setPassword(event.target.value); setError(null); }} />
                <button type="button" className="bs-login__visibility" aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword(value => !value)}><span className="material-symbols-rounded" aria-hidden="true">{showPassword ? "visibility_off" : "visibility"}</span></button></>}
            </div>
            <button className="bs-login__submit" type="submit" disabled={isSubmitting || (step === "email" ? !canContinue : !canSubmit)}>
              <span>{step === "email" ? "Continue" : isSubmitting ? "Signing in…" : "Sign in"}</span>
              <span className="material-symbols-rounded" aria-hidden="true">arrow_forward</span>
            </button>
          </div>
          {step === "password" && <button className="bs-login__back" type="button" disabled={isSubmitting} onClick={() => {
            setStep("email"); setPassword(""); setShowPassword(false); setError(null);
          }}><span className="material-symbols-rounded" aria-hidden="true">arrow_back</span>Back to sign-in options</button>}
          {googlePending && <div className="bs-login__pending"><span className="bs-login__spinner" aria-hidden="true" /><p role="status">Continue in your browser. Maverick will update automatically.</p>
            <button type="button" onClick={cancelGoogle}>Cancel Google sign-in</button></div>}
          {error && <p className="bs-form-error" id="maverick-login-error" role="alert">{error}</p>}
        </form>
        <p className="bs-login__server"><span className="material-symbols-rounded" aria-hidden="true">dns</span>{window.location.host}</p>
      </div>
    </section>
  </main>;
}
