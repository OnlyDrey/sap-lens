/// <reference types="vite/client" />

interface Window {
  pywebview?: {
    api: {
      save_user_access_csv?: (token: string, filename: string, content: string) => Promise<boolean>
      open_logs?: (token: string) => Promise<boolean>
      export_diagnostics?: (token: string) => Promise<boolean>
      choose_logo?: (session: string) => Promise<string | null>
      export_configuration?: (session: string, includePrivate: boolean) => Promise<boolean>
      open_configuration_folder?: (session: string) => Promise<boolean>
      choose_csv: (session: string) => Promise<string | null>
    }
  }
}
