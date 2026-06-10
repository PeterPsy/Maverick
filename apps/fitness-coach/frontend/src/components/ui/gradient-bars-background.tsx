import type { CSSProperties, ReactNode } from 'react';

interface GradientBarsProps {
  numBars?: number;
  gradientFrom?: string;
  gradientTo?: string;
  animationDuration?: number;
}

interface GradientBarsBackgroundProps extends GradientBarsProps {
  backgroundColor?: string;
  className?: string;
  children?: ReactNode;
  ariaLabel?: string;
}

function calculateHeight(index: number, total: number) {
  if (total <= 1) return 100;
  const position = index / (total - 1);
  const distanceFromCenter = Math.abs(position - 0.5);
  const heightPercentage = Math.pow(distanceFromCenter * 2, 1.2);
  return 30 + (100 - 30) * heightPercentage;
}

function GradientBars({
  numBars = 7,
  gradientFrom = 'rgb(215, 219, 220)',
  gradientTo = 'rgba(5, 6, 5, 0)',
  animationDuration = 2
}: GradientBarsProps) {
  return (
    <div
      aria-hidden="true"
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 0,
        overflow: 'hidden'
      }}
    >
      <div
        style={{
          display: 'flex',
          width: '100%',
          height: '100%',
          transform: 'translateZ(0)',
          backfaceVisibility: 'hidden',
          WebkitFontSmoothing: 'antialiased'
        }}
      >
        {Array.from({ length: numBars }).map((_, index) => {
          const height = calculateHeight(index, numBars);
          const barStyle: CSSProperties & { '--initial-scale': number } = {
            '--initial-scale': height / 100,
            flex: `1 0 calc(100% / ${numBars})`,
            maxWidth: `calc(100% / ${numBars})`,
            height: '100%',
            background: `linear-gradient(to top, ${gradientFrom}, ${gradientTo})`,
            transform: `scaleY(${height / 100})`,
            transformOrigin: 'bottom',
            transition: 'transform 0.5s ease-in-out',
            animation: `fitnessGradientBarPulse ${animationDuration}s ease-in-out infinite alternate`,
            animationDelay: `${index * 0.1}s`,
            outline: '1px solid rgba(0, 0, 0, 0)',
            boxSizing: 'border-box'
          };

          return <div className="fitness-gradient-bars__bar" key={index} style={barStyle} />;
        })}
      </div>
    </div>
  );
}

export function GradientBarsBackground({
  numBars = 9,
  gradientFrom = 'rgb(215, 219, 220)',
  gradientTo = 'rgba(5, 6, 5, 0)',
  animationDuration = 2,
  backgroundColor = '#050605',
  className = '',
  children,
  ariaLabel
}: GradientBarsBackgroundProps) {
  return (
    <section
      className={`gradient-bars-background ${className}`.trim()}
      aria-label={ariaLabel}
      role={ariaLabel ? 'status' : undefined}
      style={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '100%',
        height: '100%',
        minHeight: '100%',
        overflow: 'hidden',
        backgroundColor
      }}
    >
      <GradientBars numBars={numBars} gradientFrom={gradientFrom} gradientTo={gradientTo} animationDuration={animationDuration} />
      {children ? (
        <div
          style={{
            position: 'relative',
            zIndex: 1,
            display: 'flex',
            width: '100%',
            height: '100%',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '1rem'
          }}
        >
          {children}
        </div>
      ) : null}
    </section>
  );
}

export { GradientBarsBackground as Component };
