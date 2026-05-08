import React from 'react';

// Real photo-rendered tablet image
export default function PillIcon({ size = 28, className = '' }) {
  return (
    <img
      src="/pill-logo.png"
      alt=""
      width={size}
      height={size}
      style={{ width: size, height: size, objectFit: 'contain' }}
      className={`select-none ${className}`}
      draggable={false}
    />
  );
}
