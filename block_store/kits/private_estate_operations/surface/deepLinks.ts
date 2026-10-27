// Factory-generated deep links for Steward SPA
export const DEEP_LINKS = {
  home: '/',
  registry: '/registry',
  houseManual: '/house-manual',
  maintenance: '/maintenance',
  vendors: '/vendors',
  staff: '/staff',
  principal: '/principal',
  onboarding: '/onboarding',
  rag: '/rag',
  resident: '/resident',
} as const;

/** Cold-start retry hint for Render free-tier spin-up. */
export const COLD_START = {
  retries: 3,
  backoffMs: [1000, 3000, 8000],
  message: 'Service waking up — retrying…',
};
