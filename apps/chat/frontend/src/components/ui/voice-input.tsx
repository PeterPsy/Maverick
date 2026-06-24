"use client";

import React from "react";
import { Mic } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

import { cn } from "../../lib/utils";

interface VoiceInputProps {
  active?: boolean;
  ariaLabel?: string;
  busy?: boolean;
  disabled?: boolean;
  onStart?: () => void;
  onStop?: () => void;
  title?: string;
}

export function VoiceInput({
  active,
  ariaLabel,
  busy = false,
  className,
  disabled = false,
  onStart,
  onStop,
  title,
  ...props
}: React.ComponentProps<"div"> & VoiceInputProps) {
  const [_listening, _setListening] = React.useState<boolean>(false);
  const [_time, _setTime] = React.useState<number>(0);
  const isControlled = typeof active === "boolean";
  const listening = isControlled ? active : _listening;
  const showStopIndicator = listening || busy;

  React.useEffect(() => {
    if (!listening) {
      _setTime(0);
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      _setTime((t) => t + 1);
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [listening]);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const onClickHandler = () => {
    if (disabled || busy) {
      return;
    }

    if (listening) {
      if (!isControlled) {
        _setListening(false);
      }
      onStop?.();
      return;
    }

    if (!isControlled) {
      _setListening(true);
    }
    onStart?.();
  };

  return (
    <div className={cn("chatapp-voice-input", className)} {...props}>
      <motion.button
        aria-busy={busy || undefined}
        aria-label={ariaLabel || (listening ? "Stop voice input" : "Start voice input")}
        aria-pressed={listening}
        className="chatapp-voice-input__control"
        disabled={disabled || busy}
        layout
        onClick={onClickHandler}
        title={title}
        transition={{
          layout: {
            duration: 0.4,
          },
        }}
        type="button"
      >
        <div className="chatapp-voice-input__icon">
          {showStopIndicator ? (
            <motion.div
              className="chatapp-voice-input__stop-shape"
              animate={{
                rotate: [0, 180, 360],
              }}
              transition={{
                duration: 2,
                repeat: Number.POSITIVE_INFINITY,
                ease: "easeInOut",
              }}
            />
          ) : (
            <Mic />
          )}
        </div>
        {busy ? null : (
          <AnimatePresence mode="wait">
            {listening && (
              <motion.div
                initial={{ opacity: 0, width: 0, marginLeft: 0 }}
                animate={{ opacity: 1, width: "auto", marginLeft: 8 }}
                exit={{ opacity: 0, width: 0, marginLeft: 0 }}
                transition={{
                  duration: 0.4,
                }}
                className="chatapp-voice-input__meter"
              >
                <div className="chatapp-voice-input__frequency" aria-hidden="true">
                  {[...Array(12)].map((_, i) => (
                    <motion.div
                      key={i}
                      className="chatapp-voice-input__bar"
                      initial={{ height: 2 }}
                      animate={{
                        height: listening ? [2, 3 + Math.random() * 10, 3 + Math.random() * 5, 2] : 2,
                      }}
                      transition={{
                        duration: listening ? 1 : 0.3,
                        repeat: listening ? Infinity : 0,
                        delay: listening ? i * 0.05 : 0,
                        ease: "easeInOut",
                      }}
                    />
                  ))}
                </div>
                <div className="chatapp-voice-input__timer">{formatTime(_time)}</div>
              </motion.div>
            )}
          </AnimatePresence>
        )}
      </motion.button>
    </div>
  );
}
