import React from 'react';

// Photo-realistic 3D white pharmaceutical tablet (oval with diagonal score line)
export default function PillIcon({ size = 28, className = '' }) {
  const w = size * 1.55;
  const h = size;
  return (
    <svg
      width={w}
      height={h}
      viewBox="0 0 100 64"
      className={className}
      aria-hidden="true"
    >
      <defs>
        {/* Main body: top-left lit, bottom-right shaded */}
        <radialGradient id="bodyMain" cx="38%" cy="30%" r="78%">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="55%" stopColor="#F1F3F6" />
          <stop offset="85%" stopColor="#D6DBE2" />
          <stop offset="100%" stopColor="#B7BEC8" />
        </radialGradient>

        {/* Soft rim shadow */}
        <linearGradient id="rim" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.6" />
          <stop offset="100%" stopColor="#9CA3AF" stopOpacity="0.7" />
        </linearGradient>

        {/* Top gloss reflection */}
        <linearGradient id="gloss" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>

        {/* Ambient shadow under pill */}
        <radialGradient id="ground" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#1f2937" stopOpacity="0.35" />
          <stop offset="70%" stopColor="#1f2937" stopOpacity="0.05" />
          <stop offset="100%" stopColor="#1f2937" stopOpacity="0" />
        </radialGradient>

        {/* Score line shadow (diagonal indentation) */}
        <linearGradient id="scoreDark" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#6B7280" stopOpacity="0.65" />
          <stop offset="100%" stopColor="#6B7280" stopOpacity="0" />
        </linearGradient>

        {/* clip path so score stays inside pill */}
        <clipPath id="pillClip">
          <ellipse cx="50" cy="32" rx="44" ry="22" />
        </clipPath>
      </defs>

      {/* group rotated for tilted look */}
      <g transform="rotate(-14 50 32)">
        {/* ambient shadow on the ground */}
        <ellipse cx="52" cy="56" rx="40" ry="4" fill="url(#ground)" />

        {/* tablet body */}
        <ellipse cx="50" cy="32" rx="44" ry="22" fill="url(#bodyMain)" />

        {/* score line — recessed diagonal across pill */}
        <g clipPath="url(#pillClip)">
          {/* main shadow band */}
          <rect x="-10" y="30" width="120" height="3.5" fill="url(#scoreDark)" />
          {/* highlight on the upper edge of the line */}
          <line x1="0" y1="29.5" x2="100" y2="29.5" stroke="#ffffff" strokeWidth="1" opacity="0.9" />
          {/* deep dark line (centre of indent) */}
          <line x1="0" y1="32" x2="100" y2="32" stroke="#9CA3AF" strokeWidth="0.7" opacity="0.85" />
        </g>

        {/* outer rim */}
        <ellipse cx="50" cy="32" rx="44" ry="22" fill="none" stroke="url(#rim)" strokeWidth="0.8" />

        {/* upper glossy highlight */}
        <ellipse cx="40" cy="16" rx="22" ry="4.5" fill="url(#gloss)" />

        {/* small specular highlight */}
        <ellipse cx="32" cy="13" rx="6" ry="1.4" fill="#ffffff" opacity="0.95" />
      </g>
    </svg>
  );
}
