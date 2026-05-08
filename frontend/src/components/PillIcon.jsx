import React from 'react';

// 3D-styled pharmaceutical tablet with realistic lighting, score line and shadow
export default function PillIcon({ size = 28, className = '' }) {
  const w = size * 1.5;
  const h = size;
  return (
    <svg
      width={w}
      height={h}
      viewBox="0 0 60 40"
      className={`-rotate-[15deg] ${className}`}
      aria-hidden="true"
    >
      <defs>
        {/* main pill body — radial light from top */}
        <radialGradient id="pillBody" cx="38%" cy="28%" r="80%">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="55%" stopColor="#ECFDF5" />
          <stop offset="90%" stopColor="#A7F3D0" />
          <stop offset="100%" stopColor="#34D399" />
        </radialGradient>

        {/* subtle outer ring shadow */}
        <linearGradient id="pillRim" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#10B981" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#047857" stopOpacity="0.85" />
        </linearGradient>

        {/* top highlight */}
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
          <feGaussianBlur in="SourceAlpha" stdDeviation="1.6" />
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

      <g filter="url(#pillDrop)">
        {/* tablet outer */}
        <ellipse cx="30" cy="20" rx="27" ry="16" fill="url(#pillBody)" stroke="url(#pillRim)" strokeWidth="1.2" />

        {/* score line — recessed effect: dark line + thin highlight */}
        <line x1="5" y1="20.4" x2="55" y2="20.4" stroke="url(#scoreShadow)" strokeWidth="2.4" strokeLinecap="round" />
        <line x1="6" y1="19.4" x2="54" y2="19.4" stroke="#ffffff" strokeWidth="0.8" strokeLinecap="round" opacity="0.7" />

        {/* top gloss highlight */}
        <ellipse cx="24" cy="11" rx="14" ry="3.2" fill="url(#pillGloss)" />

        {/* small specular dot */}
        <ellipse cx="18" cy="9" rx="3" ry="1" fill="#ffffff" opacity="0.95" />
      </g>
    </svg>
  );
}
