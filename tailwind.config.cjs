// Colours resolve through CSS custom properties (see static/css/source.css):
// :root holds the dark palette (unchanged values), and `.theme-light` — applied
// to #view-profile — overrides the tokens for the opt-in light profile view.
const c = (name) => `rgb(var(--color-${name}) / <alpha-value>)`;
const TOKENS = [
  'outline', 'inverse-surface', 'primary', 'on-secondary-fixed-variant',
  'secondary-fixed', 'on-secondary-container', 'secondary-container',
  'surface-container-high', 'surface-tint', 'inverse-primary', 'on-primary-container',
  'tertiary-container', 'on-surface-variant', 'primary-fixed-dim', 'on-tertiary-container',
  'on-primary', 'tertiary-fixed', 'surface', 'surface-dim', 'on-surface',
  'error-container', 'secondary-fixed-dim', 'surface-container', 'secondary',
  'primary-container', 'on-primary-fixed-variant', 'inverse-on-surface',
  'tertiary-fixed-dim', 'on-tertiary-fixed-variant', 'outline-variant', 'surface-bright',
  'surface-container-low', 'on-secondary-fixed', 'on-primary-fixed', 'on-secondary',
  'on-error', 'on-tertiary-fixed', 'error', 'on-error-container',
  'surface-container-lowest', 'on-tertiary', 'surface-variant', 'tertiary',
  'background', 'on-background', 'primary-fixed', 'surface-container-highest',
];

module.exports = {
  darkMode: 'class',
  content: ['./static/index.html', './static/js/**/*.js'],
  theme: {
    extend: {
      colors: Object.fromEntries(TOKENS.map((name) => [name, c(name)])),
      borderRadius: { DEFAULT: '0.25rem', lg: '0.5rem', xl: '0.75rem', full: '9999px' },
      spacing: {
        'stack-sm': '8px', 'stack-lg': '32px', gutter: '24px',
        'margin-desktop': '48px', 'margin-mobile': '16px', unit: '4px', 'stack-md': '16px',
      },
      fontFamily: {
        'headline-lg': ['Space Grotesk', 'Geist'],
        'headline-lg-mobile': ['Space Grotesk', 'Geist'],
        'label-md': ['Space Grotesk', 'Geist'],
        'headline-md': ['Space Grotesk', 'Geist'],
        'body-md': ['Geist'],
        'label-sm': ['Space Grotesk', 'Geist'],
        'display-lg': ['Space Grotesk', 'Geist'],
        'body-lg': ['Geist'],
      },
      fontSize: {
        'headline-lg': ['36px', { lineHeight: '1.15', letterSpacing: '-0.03em', fontWeight: '700' }],
        'headline-lg-mobile': ['26px', { lineHeight: '1.15', letterSpacing: '-0.02em', fontWeight: '700' }],
        'label-md': ['12px', { lineHeight: '1', letterSpacing: '0.04em', fontWeight: '600' }],
        'headline-md': ['22px', { lineHeight: '1.35', letterSpacing: '-0.02em', fontWeight: '700' }],
        'body-md': ['14px', { lineHeight: '1.5', letterSpacing: '0', fontWeight: '400' }],
        'label-sm': ['10px', { lineHeight: '1', letterSpacing: '0.06em', fontWeight: '700' }],
        'display-lg': ['64px', { lineHeight: '1.05', letterSpacing: '-0.04em', fontWeight: '700' }],
        'body-lg': ['16px', { lineHeight: '1.6', letterSpacing: '-0.01em', fontWeight: '400' }],
      },
    },
  },
};
