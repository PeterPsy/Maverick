import type { RuntimeStepMessage as RuntimeStep } from "../api/client";

export function RuntimeStepMessage({ step }: { step: RuntimeStep }) {
  return (
    <div className="chatapp-agent-step chatapp-agent-step--thought">
      <div className="chatapp-agent-step__body">
        <p>{step.label}</p>
      </div>
    </div>
  );
}
