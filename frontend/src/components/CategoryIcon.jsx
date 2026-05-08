import React from 'react';
import { Thermometer, Pill, Leaf, Apple, HeartPulse, Wind, Shield, Baby, Eye, Sparkles, Droplets, Brain } from 'lucide-react';

const MAP = { Thermometer, Pill, Leaf, Apple, HeartPulse, Wind, Shield, Baby, Eye, Sparkles, Droplets, Brain };

export default function CategoryIcon({ name, className = 'w-6 h-6' }) {
  const Cmp = MAP[name] || Pill;
  return <Cmp className={className} />;
}
