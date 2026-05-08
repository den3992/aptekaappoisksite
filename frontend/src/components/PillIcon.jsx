import React from 'react';

// 3D-styled round pharmaceutical tablet with realistic lighting, score line and shadow
export default function PillIcon({ size = 28, className = '' }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      className={`${className}`}
      aria-hidden="true"
    >
      <defs>
        {/* main pill body — radial light from top-left */}
        <radialGradient id="pillBody" cx="35%" cy="28%" r="78%">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="55%" stopColor="#ECFDF5" />
          <stop offset="90%" stopColor="#A7F3D0" />
          <stop offset="100%" stopColor="#34D399" />
        </radialGradient>

        {/* outer ring shadow */}
        <linearGradient id="pillRim" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#10B981" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#047857" stopOpacity="0.85" />
        </linearGradient>

        {/* top gloss highlight */}
        <linearGradient id="pillGloss" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>

        {/* score line shading */}
        <linearGradient id="scoreShadow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#047857" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#10B981" stopOpacity="0" />
        </linearGradient>

        {/* drop shadow filter */}
        <filter id="pillDrop" x="-30%" y="-20%" width="160%" height="160%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="1.4" />
          <feOffset dx="0" dy="2" result="offsetblur" />
          <feComponentTransfer>
            <feFuncA type="linear" slope="0.35" />
          </feComponentTransfer>
          <feMerge>
            <feMergeNode />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <g filter="url(#pillDrop)" transform="rotate(-12 20 20)">
        {/* tablet body */}
        <circle cx="20" cy="20" r="17" fill="url(#pillBody)" stroke="url(#pillRim)" strokeWidth="1.2" />

        {/* score line — recessed effect: dark line + thin highlight */}
        <line x1="4" y1="20.4" x2="36" y2="20.4" stroke="url(#scoreShadow)" strokeWidth="2.4" strokeLinecap="round" />
        <line x1="5" y1="19.4" x2="35" y2="19.4" stroke="#ffffff" strokeWidth="0.8" strokeLinecap="round" opacity="0.7" />

        {/* top gloss highlight */}
        <ellipse cx="15" cy="10.5" rx="9" ry="2.6" fill="url(#pillGloss)" />

        {/* small specular dot */}
        <ellipse cx="11" cy="9" rx="2.2" ry="0.9" fill="#ffffff" opacity="0.95" />
      </g>
    </svg>
  );
}
