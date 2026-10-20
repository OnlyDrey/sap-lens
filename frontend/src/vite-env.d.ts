/// <reference types="vite/client" />

interface Window {
  pywebview?: {
    api: {
      choose_csv: (session: string) => Promise<string | null>
    }
  }
}
