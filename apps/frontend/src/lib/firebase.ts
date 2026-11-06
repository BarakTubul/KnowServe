import { getApp, getApps, initializeApp, type FirebaseApp } from 'firebase/app';
import {
  browserPopupRedirectResolver,
  browserSessionPersistence,
  connectAuthEmulator,
  initializeAuth,
  type Auth,
} from 'firebase/auth';

let auth: Auth | undefined;

function firebaseApp(): FirebaseApp {
  if (getApps().length > 0) return getApp();
  const env = import.meta.env;
  return initializeApp({
    apiKey: env.VITE_FIREBASE_API_KEY,
    authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
    projectId: env.VITE_FIREBASE_PROJECT_ID,
  });
}

/**
 * The one Firebase Auth instance. Persistence is the tab-scoped session storage (FE-AUTH-06):
 * it survives a reload, so a Demo user can still link a credential, but not a new tab or browser.
 * The popup resolver enables Google sign-in as a popup (the default flow, see docs/frontend/auth.md).
 */
export function getFirebaseAuth(): Auth {
  if (auth) return auth;
  const instance = initializeAuth(firebaseApp(), {
    persistence: browserSessionPersistence,
    popupRedirectResolver: browserPopupRedirectResolver,
  });
  const emulatorUrl = import.meta.env.VITE_FIREBASE_AUTH_EMULATOR_URL;
  if (emulatorUrl) connectAuthEmulator(instance, emulatorUrl, { disableWarnings: true });
  auth = instance;
  return instance;
}
