// Static visual styles per category slug. The list of categories themselves
// (and their counts) comes from the backend `/api/categories` endpoint —
// this map only provides icon name + brand colors for the UI cards.
export const CATEGORY_STYLES = {
  'ot-prostudy':       { icon: 'Thermometer', color: '#FEE2E2', accent: '#DC2626' },
  'obezbolivayuschie': { icon: 'Pill',        color: '#FEF3C7', accent: '#D97706' },
  'vitaminy-bady':     { icon: 'Leaf',        color: '#DCFCE7', accent: '#16A34A' },
  'zhkt':              { icon: 'Apple',       color: '#FFE4E6', accent: '#E11D48' },
  'serdce':            { icon: 'HeartPulse',  color: '#E0E7FF', accent: '#4F46E5' },
  'allergiya':         { icon: 'Wind',        color: '#CFFAFE', accent: '#0891B2' },
  'antibiotiki':       { icon: 'Shield',      color: '#F3E8FF', accent: '#7E22CE' },
  'mat-i-ditya':       { icon: 'Baby',        color: '#FCE7F3', accent: '#DB2777' },
  'glaza':             { icon: 'Eye',         color: '#DBEAFE', accent: '#1D4ED8' },
  'kozha':             { icon: 'Sparkles',    color: '#FEF9C3', accent: '#CA8A04' },
  'gigiena':           { icon: 'Droplets',    color: '#E0F2FE', accent: '#0369A1' },
  'nervnaya':          { icon: 'Brain',       color: '#EDE9FE', accent: '#6D28D9' },
};

const FALLBACK = { icon: 'Pill', color: '#F1F5F9', accent: '#475569' };

export function getCategoryStyle(slug) {
  return CATEGORY_STYLES[slug] || FALLBACK;
}
