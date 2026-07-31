import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface JoystickProps {
  disabled?: boolean;
  /** Called at most every `intervalMs` while the stick is held. */
  onCommand: (linear: number, angular: number) => void;
  onRelease: () => void;
  maxLinear?: number;
  maxAngular?: number;
  intervalMs?: number;
  className?: string;
}

/**
 * Analog teleop pad. Commands are emitted on a fixed timer (not per pointer
 * event) so dragging never floods the backend with requests.
 */
export function Joystick({
  disabled,
  onCommand,
  onRelease,
  maxLinear = 0.6,
  maxAngular = 1.2,
  intervalMs = 200,
  className,
}: JoystickProps) {
  const padRef = useRef<HTMLDivElement>(null);
  const vectorRef = useRef({ x: 0, y: 0 });
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [knob, setKnob] = useState({ x: 0, y: 0 });
  const [active, setActive] = useState(false);

  const stop = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    vectorRef.current = { x: 0, y: 0 };
    setKnob({ x: 0, y: 0 });
    setActive(false);
    onRelease();
  }, [onRelease]);

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current);
  }, []);

  const updateFromPointer = useCallback((clientX: number, clientY: number) => {
    const pad = padRef.current;
    if (!pad) return;
    const rect = pad.getBoundingClientRect();
    const radius = rect.width / 2;
    let dx = clientX - (rect.left + radius);
    let dy = clientY - (rect.top + radius);
    const distance = Math.hypot(dx, dy);
    if (distance > radius) {
      dx = (dx / distance) * radius;
      dy = (dy / distance) * radius;
    }
    setKnob({ x: dx, y: dy });
    vectorRef.current = { x: dx / radius, y: dy / radius };
  }, []);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setActive(true);
    updateFromPointer(event.clientX, event.clientY);
    if (!timerRef.current) {
      const tick = () => {
        const { x, y } = vectorRef.current;
        onCommand(Number((-y * maxLinear).toFixed(3)), Number((-x * maxAngular).toFixed(3)));
      };
      tick();
      timerRef.current = setInterval(tick, intervalMs);
    }
  };

  return (
    <div className={cn("flex flex-col items-center gap-3", className)}>
      <div
        ref={padRef}
        role="application"
        aria-label="Teleoperation joystick"
        aria-disabled={disabled}
        onPointerDown={handlePointerDown}
        onPointerMove={(event) => {
          if (!active || disabled) return;
          updateFromPointer(event.clientX, event.clientY);
        }}
        onPointerUp={stop}
        onPointerCancel={stop}
        className={cn(
          "relative flex size-44 touch-none items-center justify-center rounded-full border-2 border-primary/40 bg-card transition-opacity",
          disabled ? "cursor-not-allowed opacity-40" : "cursor-grab active:cursor-grabbing",
        )}
      >
        <div className="absolute inset-6 rounded-full border border-border" />
        <div
          className="size-14 rounded-full bg-primary shadow-lg transition-transform"
          style={{ transform: `translate(${knob.x}px, ${knob.y}px)` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        {disabled ? "Connect a robot to enable teleop" : "Hold and drag to drive"}
      </p>
    </div>
  );
}
