import React from 'react';

// Real photo-rendered tablet image.
// Pass `size` (number) for a fixed pixel size,
// or omit `size` and pass Tailwind sizing classes (e.g. "w-4 h-4 md:w-5 md:h-5") via `className`.
export default function PillIcon({ size, className = '' }) {
  const styleProp = size ? { width: size, height: size, objectFit: 'contain' } : { objectFit: 'contain' };
  const sizeAttrs = size ? { width: size, height: size } : {};
  return (
    <img
      src="/pill-logo.png"
      alt=""
      {...sizeAttrs}
      style={styleProp}
      className={`select-none ${className}`}
      draggable={false}
    />
  );
}
