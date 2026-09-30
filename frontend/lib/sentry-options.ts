/**
 * Sentry options shared by the server and the browser (see instrumentation*.ts).
 *
 * PRIVACY: Sentry SDK v11 collects cookies, headers, request bodies and user info by DEFAULT.
 * We switch every category off, because the privacy policy promises that error reports contain
 * no personal data. Do not loosen this without changing the privacy policy first
 * (config/legal.ts, docs/LEGAL_TEMPLATES.md).
 */
export const sentryPrivacyOptions = {
  dataCollection: {
    userInfo: false,
    cookies: false,
    httpHeaders: false,
    httpBodies: [] as never[],
    urlQueryParams: false,
    databaseQueryData: false,
    queues: false,
    stackFrameVariables: false,
    genAI: { inputs: false, outputs: false },
    graphQL: { document: false, variables: false },
  },
  tracesSampleRate: 0,
} as const;
