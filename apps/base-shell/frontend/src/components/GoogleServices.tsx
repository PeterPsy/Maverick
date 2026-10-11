import type { GoogleService } from "../api";

export const GOOGLE_SERVICES: { id: GoogleService; label: string; detail: string }[] = [
  { id: "calendar", label: "Calendar", detail: "Read and manage events" },
  { id: "gmail", label: "Gmail", detail: "Read, organise and send mail" },
  { id: "drive", label: "Drive", detail: "Read and manage files" },
];

export function GoogleServices({ selected, onChange, disabled = false }: {
  selected: GoogleService[]; onChange: (services: GoogleService[]) => void; disabled?: boolean;
}) {
  return <fieldset className="bs-google-services" disabled={disabled}>
    <legend>Connect Google services</legend>
    {GOOGLE_SERVICES.map(service => <label key={service.id}>
      <input type="checkbox" checked={selected.includes(service.id)} onChange={event => onChange(event.target.checked
        ? [...selected, service.id] : selected.filter(item => item !== service.id))} />
      <span><strong>{service.label}</strong><small>{service.detail}</small></span>
    </label>)}
    <small>Optional. You can add services later. New Maverick apps can reuse the services you approve.</small>
  </fieldset>;
}

export function GoogleMark() {
  return <svg aria-hidden="true" width="20" height="20" viewBox="0 0 48 48">
    <path fill="#4285F4" d="M43.61 24.46c0-1.36-.12-2.66-.35-3.92H24v7.42h11a9.4 9.4 0 0 1-4.08 6.17v5h6.6c3.87-3.56 6.09-8.81 6.09-14.67Z" />
    <path fill="#34A853" d="M24 44c5.5 0 10.1-1.83 13.46-4.94l-6.6-5A12.1 12.1 0 0 1 24 36.03c-5.3 0-9.8-3.57-11.4-8.38H5.77v5.16A20.33 20.33 0 0 0 24 44Z" />
    <path fill="#FBBC05" d="M12.6 27.65A12 12 0 0 1 12 24c0-1.27.22-2.5.6-3.65v-5.16H5.77A20 20 0 0 0 3.6 24c0 3.22.78 6.27 2.17 8.81l6.83-5.16Z" />
    <path fill="#EA4335" d="M24 11.97c3 0 5.7 1.03 7.83 3.06l5.87-5.87C34.1 5.8 29.5 4 24 4A20.33 20.33 0 0 0 5.77 15.19l6.83 5.16C14.2 15.54 18.7 11.97 24 11.97Z" />
  </svg>;
}

export function googleCallbackMessage(code: string | null): string | null {
  if (!code) return null;
  const messages: Record<string, string> = {
    google_workspace_pending: "Your Google account is registered. Ask an administrator to assign you a workspace, then sign in again.",
    google_account_link_required: "Sign in with your Maverick password first, then link Google from Connected accounts.",
    google_account_already_linked: "This Google account is linked to another Maverick user.",
    google_consent_cancelled: "Google sign-in was cancelled. You can try again or sign in with your password.",
    google_offline_consent_required: "Google did not grant background access. Try connecting again and approve the selected services.",
    google_not_configured: "Google sign-in is not configured. Contact your administrator.",
    google_flow_session_changed: "Your Maverick session changed. Start the Google connection again.",
    google_registration_disabled: "This Google account is not authorised to sign in. Contact your administrator.",
  };
  return messages[code] ?? "Google sign-in could not be completed. Please try again.";
}
