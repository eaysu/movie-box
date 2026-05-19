---
name: Lumina Cinematic
colors:
  surface: '#101417'
  surface-dim: '#101417'
  surface-bright: '#363a3d'
  surface-container-lowest: '#0b0f11'
  surface-container-low: '#191c1f'
  surface-container: '#1d2023'
  surface-container-high: '#272a2d'
  surface-container-highest: '#323538'
  on-surface: '#e0e2e6'
  on-surface-variant: '#bacbb6'
  inverse-surface: '#e0e2e6'
  inverse-on-surface: '#2d3134'
  outline: '#859582'
  outline-variant: '#3c4b3a'
  surface-tint: '#15e558'
  primary: '#43fe6d'
  on-primary: '#00390f'
  primary-container: '#00e054'
  on-primary-container: '#005d1e'
  inverse-primary: '#006e25'
  secondary: '#ffb787'
  on-secondary: '#502400'
  secondary-container: '#ff8000'
  on-secondary-container: '#5e2b00'
  tertiary: '#b9e4ff'
  on-tertiary: '#003549'
  tertiary-container: '#6ccdff'
  on-tertiary-container: '#005675'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#6cff80'
  primary-fixed-dim: '#15e558'
  on-primary-fixed: '#002106'
  on-primary-fixed-variant: '#00531a'
  secondary-fixed: '#ffdcc7'
  secondary-fixed-dim: '#ffb787'
  on-secondary-fixed: '#311300'
  on-secondary-fixed-variant: '#723600'
  tertiary-fixed: '#c3e8ff'
  tertiary-fixed-dim: '#7ad0ff'
  on-tertiary-fixed: '#001e2c'
  on-tertiary-fixed-variant: '#004c69'
  background: '#101417'
  on-background: '#e0e2e6'
  surface-variant: '#323538'
typography:
  display-lg:
    fontFamily: Geist
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: -0.04em
  headline-lg:
    fontFamily: Geist
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.03em
  headline-lg-mobile:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: '600'
    lineHeight: '1.4'
    letterSpacing: -0.02em
  body-lg:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: -0.01em
  body-md:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
    letterSpacing: '0'
  label-md:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Geist
    fontSize: 10px
    fontWeight: '600'
    lineHeight: '1'
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 48px
  stack-sm: 8px
  stack-md: 16px
  stack-lg: 32px
---

## Brand & Style

The design system is engineered for a high-performance film discovery experience, blending the technical precision of modern developer tools with the immersive atmosphere of a high-end screening room. The aesthetic is rooted in **Corporate / Modern** minimalism with a heavy emphasis on **Glassmorphism** and depth.

The target audience consists of cinephiles who value efficiency and high-fidelity visuals. The UI should evoke a sense of "digital craftsmanship"—feeling fast, responsive, and premium. Every interaction should feel intentional, utilizing subtle transitions and crisp borders to define the space rather than heavy shadows or decorative elements.

## Colors

The palette is optimized for low-light environments, reducing eye strain while highlighting cinematic imagery.

- **Foundations:** The primary background uses a deep navy base. A subtle radial gradient of burgundy originates from the top-right corner (opacity ~15%) to add atmospheric depth without sacrificing legibility.
- **Surfaces:** Containers use a tiered navy approach. Borders are strictly 1px, using a semi-transparent white (approx. 10-15% opacity) to create "light-leaks" on the edges of components.
- **Accents:** The Letterboxd-inspired palette (Green, Orange, Blue) is used for functional precision. Green signifies "Go," "Watched," or "Primary Action." Orange and Blue are reserved for secondary metadata, such as ratings or streaming status indicators.

## Typography

This design system utilizes **Geist** for its mechanical precision and readability. 

- **Headlines:** Use Bold or SemiBold weights with tight letter-spacing to create a "compact" tech aesthetic. 
- **Body:** Regular weight with standard tracking for maximum legibility in synopses and reviews.
- **Labels:** Use Medium or SemiBold weights with slight tracking and uppercase transforms for utility text (e.g., Genres, Release Dates, or Durations).

## Layout & Spacing

The layout follows a **Fixed Grid** on desktop (12-column, 1200px max-width) and a **Fluid Grid** on mobile.

- **Rhythm:** A 4px baseline grid ensures consistent vertical rhythm.
- **Gutters:** 24px gutters provide ample breathing room between movie posters and metadata cards.
- **Adaptation:** On mobile, margins shrink to 16px. Vertical stacks increase in frequency, and horizontal scrolling "shelves" are used for movie categories to preserve vertical space.

## Elevation & Depth

Hierarchy is established through **Tonal Layering** and **Backdrop Blurs** rather than traditional drop shadows.

- **Base Layer:** The Deep Navy (#0B0E1A) background.
- **Level 1 (Cards/Lists):** Surface Navy (#13172A) with a 1px border (`rgba(242, 244, 248, 0.1)`).
- **Level 2 (Modals/Popovers):** Surface Navy with `backdrop-filter: blur(12px)`. This creates the "Glassmorphism" effect, allowing colors from movie posters or the background glow to bleed through subtly.
- **Shadows:** Use a single, very soft ambient shadow for floating elements: `0px 8px 32px rgba(0, 0, 0, 0.4)`.

## Shapes

The shape language is modern and approachable but maintains a "pro" feel.

- **Default (0.5rem):** Used for standard buttons, input fields, and small cards.
- **Large (1rem):** Used for movie poster containers and primary content blocks.
- **Extra Large (1.5rem):** Reserved for major modal containers or onboarding cards.
- **Interactive States:** On hover, borders should slightly brighten to `rgba(242, 244, 248, 0.2)` to provide tactile feedback.

## Components

- **Buttons:** Primary buttons use the Accent Green (#00E054) with black text for high contrast. Secondary buttons use a ghost style (1px border, white text).
- **Cards:** Movie cards should feature the poster as the primary element. On hover, a subtle 1px border highlight and a slight scale-up (1.02x) effect should be applied.
- **Input Fields:** Darker than the surface background with a 1px border. Focus state uses the Blue accent (#40BCF4) for the border.
- **Chips/Tags:** Small, pill-shaped with a background that is slightly lighter than the card surface. Used for genres (e.g., "Sci-Fi", "Noir").
- **Status Dots:** Use the 3-color accent system (Green/Orange/Blue) to indicate "Watchlisted," "Favorites," or "Streaming Now" without using heavy icons.
- **Progress Bars/Ratings:** Use the Orange accent (#FF8000) for star ratings or completion bars to distinguish them from primary action buttons.