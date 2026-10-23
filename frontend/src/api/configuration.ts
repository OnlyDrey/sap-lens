import { apiRequest } from './client'

export interface ThemePalette { primary:string;accent:string;background:string;surface:string;text:string }
export interface ThemePreset { name:string;mode:'light'|'dark';colors:ThemePalette }
export interface ThemeColors { dark:ThemePalette;light:ThemePalette;custom_presets:ThemePreset[] }
export interface Organization { name: string; platform: string; custom_platform: string; system_id: string; client: string; description: string; footer: string }
export interface ImportProfile { id: string; name: string; version: number; mapping: Record<string,string>; delimiter: string; encoding: string }
export interface ModuleOverride { display_name?: string | null; icon?: string | null; color?: string | null; enabled: boolean }
export interface Configuration { employee_csv_path?: string; employee_snapshot_id?: string | null; features?: { employee_directory: boolean; user_role_mapping?: boolean }; schema_version: number; revision: number; data_csv_path: string; organization: Organization; theme: 'system' | 'dark' | 'light'; theme_colors:ThemeColors; logo_id: string | null; module_overrides: Record<string,ModuleOverride>; user_csv_path: string; user_import_profiles: ImportProfile[]; active_user_import: string; legacy_classification?: Record<string,unknown> | null; import_profiles: ImportProfile[]; active_import: string }
export interface ConfigurationResponse { data_revision?: string; settings: Configuration; notice: string | null; error: string | null; loading: boolean; analysis: Record<string,unknown> }
export interface RegistryEntry { id: string; abbreviation: string; name: string; category: string; parent: string | null; aliases: string[]; icon: string; color: string; enabled: boolean; display_name: string | null; default_color?: string; default_icon?: string; default_name?: string }
export interface RegistryResponse { modules: RegistryEntry[]; icons: string[]; reference_note: string }
export interface ImportReport { file_name: string; detected_columns: string[]; parsed_rows: number; unique_roles: number; unique_transactions: number; transaction_assignments: number; duplicate_rows: number; warnings: string[]; errors: string[]; samples: Record<string,string>[]; analysis: Record<string,unknown> }
export const fetchConfiguration = () => apiRequest<ConfigurationResponse>('/api/configuration')
export const saveConfiguration = (settings: Configuration) => apiRequest<ConfigurationResponse>('/api/configuration','POST',settings)
export const fetchRegistry = () => apiRequest<RegistryResponse>('/api/registry/modules')
export const previewImport = (path: string, profile: ImportProfile) => apiRequest<ImportReport>('/api/import/preview','POST',{data_csv_path:path,profile})
export const detectHeaders = (path: string, profile: ImportProfile) => apiRequest<{detected_columns:string[];proposed_mapping:Record<string,string>;issues:string[]}>('/api/import/headers','POST',{data_csv_path:path,profile})
