/**
 * Tiny app-wide browser events, for parts of the page that don't share state.
 *
 *   window.dispatchEvent(new Event(ONBOARDING_REFRESH));
 */

/** Something happened that may finish a "Get started" step (e.g. a job was started). */
export const ONBOARDING_REFRESH = "onboarding:refresh";
