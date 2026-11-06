/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  /** Public Firebase web config (not secrets). */
  readonly VITE_FIREBASE_API_KEY?: string;
  readonly VITE_FIREBASE_AUTH_DOMAIN?: string;
  readonly VITE_FIREBASE_PROJECT_ID?: string;
  /** When set (local and CI only), the Firebase Auth Emulator is used instead of Firebase. */
  readonly VITE_FIREBASE_AUTH_EMULATOR_URL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
