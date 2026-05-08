import React from 'react';

// Stylized tablet pill icon (round/oval tablet with a score line)
export default function PillIcon({ size = 28, className = '' }) {
  const w = size * 1.45;
  const h = size;
  return (
    <svg
      width={w}
      height={h}
      viewBox="0 0 32 22"
      className={`-rotate-[18deg] drop-shadow-sm ${className}`}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="tabletFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#ECFDF5" />
        </linearGradient>
      </defs>
      <ellipse cx="16" cy="11" rx="14.5" ry="9" fill="url(#tabletFill)" stroke="#0E9F6E" strokeWidth="1.8" />
      <line x1="2.5" y1="11" x2="29.5" y2="11" stroke="#0E9F6E" strokeWidth="1.6" strokeLinecap="round" />
      {/* subtle highlight */}
      <ellipse cx="11" cy="7.5" rx="5" ry="1.5" fill="#ffffff" opacity="0.7" />
    </svg>
  );
}
