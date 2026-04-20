import { useEffect, useState } from "react";
import { Button, Dialog } from "../ui";

type TutorialStep = {
  description: string;
  eyebrow: string;
  linkLabel: string;
  linkHref: string;
  mediaLabel: string;
  mediaVariant?: "default" | "animated-background";
  title: string;
};

const TUTORIAL_STEPS: TutorialStep[] = [
  {
    eyebrow: "Workspaces",
    title: "Switch contexts without losing momentum.",
    description: "Move between workspaces, chats, and installed apps from one place.",
    linkLabel: "Learn how workspaces are organized",
    linkHref: "#",
    mediaLabel: "Workspace switching",
  },
  {
    eyebrow: "Chats",
    title: "Every chat is a persistent agent session.",
    description: "Create, rename, move, and revisit chats as durable working threads.",
    linkLabel: "See how chat instances work",
    linkHref: "#",
    mediaLabel: "Persistent chats",
  },
  {
    eyebrow: "Apps",
    title: "Open focused tools inside Maverick.",
    description: "Installed apps add dedicated panels for operations, media, documents, and more.",
    linkLabel: "Explore the apps layer",
    linkHref: "#",
    mediaLabel: "Integrated apps",
  },
  {
    eyebrow: "Agents",
    title: "Choose the right agent for the job.",
    description: "Agent types define behavior, runtime access, and how new chats get started.",
    linkLabel: "Understand agent types",
    linkHref: "#",
    mediaLabel: "Agent setup",
  },
  {
    eyebrow: "Automation",
    title: "Schedule recurring work in a few clicks.",
    description: "Turn a chat into a periodic agent for reports, monitoring, and recurring tasks.",
    linkLabel: "View automation basics",
    linkHref: "#",
    mediaLabel: "Scheduled workflows",
  },
];

export function TutorialDialog({ onClose, open }: { onClose: () => void; open: boolean }) {
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    if (!open) {
      setStepIndex(0);
    }
  }, [open]);

  const step = TUTORIAL_STEPS[stepIndex];
  const isFirstStep = stepIndex === 0;
  const isLastStep = stepIndex === TUTORIAL_STEPS.length - 1;

  return (
    <Dialog
      description="A quick walkthrough of Maverick's core workflow."
      hideHeader
      onClose={onClose}
      open={open}
      panelClassName="bs-tutorial-dialog"
      title="Tutorial"
    >
      <div className="bs-tutorial">
        <div className="bs-tutorial__hero">
          <button aria-label="Close tutorial" className="bs-tutorial__close" onClick={onClose} type="button">
            <span aria-hidden="true" className="material-symbols-rounded">close</span>
          </button>
          <div className="bs-tutorial__hero-background" aria-hidden="true">
            <div className="bs-tutorial__hero-background-grid" />
          </div>
          <div className="bs-tutorial__hero-card" aria-label={step.mediaLabel}>
            <div className="bs-tutorial__hero-media">
              <div className="bs-tutorial__hero-window">
                <div className="bs-tutorial__hero-window-bar">
                  <span />
                  <span />
                  <span />
                </div>
                <div className={`bs-tutorial__hero-window-screen${step.mediaVariant === "animated-background" ? " is-animated-background" : ""}`}>
                  {step.mediaVariant === "animated-background" ? (
                    <>
                      <div className="bs-tutorial__hero-orb bs-tutorial__hero-orb--one" />
                      <div className="bs-tutorial__hero-orb bs-tutorial__hero-orb--two" />
                      <div className="bs-tutorial__hero-orb bs-tutorial__hero-orb--three" />
                      <div className="bs-tutorial__hero-grid" />
                      <div className="bs-tutorial__hero-content">
                        <span className="bs-tutorial__hero-pill">Transform + opacity</span>
                        <span className="bs-tutorial__hero-line bs-tutorial__hero-line--strong" />
                        <span className="bs-tutorial__hero-line" />
                        <span className="bs-tutorial__hero-line bs-tutorial__hero-line--short" />
                      </div>
                    </>
                  ) : null}
                </div>
              </div>
            </div>
            <div className="bs-tutorial__hero-card-copy">
              <p className="bs-tutorial__hero-card-eyebrow">{step.eyebrow}</p>
              <h4 className="bs-tutorial__hero-card-title">{step.title}</h4>
            </div>
          </div>
        </div>

        <div className="bs-tutorial__panel">
          <div className="bs-tutorial__dots" aria-label={`Step ${stepIndex + 1} of ${TUTORIAL_STEPS.length}`}>
            {TUTORIAL_STEPS.map((item, index) => (
              <button
                aria-current={index === stepIndex ? "step" : undefined}
                className={`bs-tutorial__dot ${index === stepIndex ? "is-active" : ""}`}
                key={item.title}
                onClick={() => setStepIndex(index)}
                type="button"
              />
            ))}
          </div>
          <div className="bs-tutorial__copy">
            <h4 className="bs-tutorial__title">{step.title}</h4>
            <p className="bs-tutorial__description">{step.description}</p>
            <a className="bs-tutorial__link" href={step.linkHref}>
              {step.linkLabel}
            </a>
          </div>
          <div className="bs-tutorial__actions">
            {!isFirstStep ? (
              <Button variant="ghost" onClick={() => setStepIndex((current) => Math.max(0, current - 1))}>
                Back
              </Button>
            ) : (
              <span />
            )}
            <Button
              variant="primary"
              onClick={isLastStep ? onClose : () => setStepIndex((current) => Math.min(TUTORIAL_STEPS.length - 1, current + 1))}
            >
              {isLastStep ? "Start" : "Next"}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
