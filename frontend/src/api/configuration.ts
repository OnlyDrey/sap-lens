import { apiRequest } from './client'

export interface ThemePalette { primary:string;accent:string;background:string;surface:string;text:string }
export interface ThemePreset { name:string;mode:'light'|'dark';colors:ThemePalette }
export interface ThemeColors { dark:ThemePalette;light:ThemePalette;custom_presets:ThemePreset[] }
export interface Organization { name: string; platform: string; custom_platform: string; system_id: string; client: string; description: string; footer: string }
export interface ImportProfile { id: string; name: string; version: number; mapping: Record<string,string>; delimiter: string; encoding: string }
export interface ModuleOverride { display_name?: string | null; icon?: string | null; color?: string | null; enabled: boolean }
export interface RefreshSchedule { enabled: boolean; mode: 'daily' | 'cron'; time: string; cron: string; timezone: string }
export interface ScheduleState { last_attempt: string | null; last_success: string | null; last_failure: string | null; last_status: 'succeeded' | 'partial' | 'failed' | 'skipped' | null; last_message: string | null; consecutive_failures: number | null }
export interface ScheduleStatus { schedule: RefreshSchedule; state: ScheduleState; runtime: { deployment_mode: 'desktop' | 'server'; requires_running_application: boolean }; expression: string | null; description: string | null; next_runs: string[]; next_run: string | null; error: string | null }
export interface SchedulePreview { valid: boolean; expression: string | null; description: string | null; next_runs: string[]; error: string | null }
export const DEFAULT_SCHEDULE: RefreshSchedule = { enabled: false, mode: 'daily', time: '06:00', cron: '0 6 * * *', timezone: 'local' }
export interface Configuration { refresh_schedule?: RefreshSchedule; desktop?:{close_to_tray:boolean;run_at_signin:boolean;start_minimized:boolean}; source_modes?: {roles:'static'|'dynamic';users:'static'|'dynamic';employees:'static'|'dynamic';sod?:'static'|'dynamic'}; data_lifecycle?: Record<string,unknown>; unlicensed_user_groups?: string[]; employee_csv_path?: string; sod_csv_path?: string; employee_snapshot_id?: string | null; features?: { employee_directory: boolean; user_role_mapping?: boolean; sod?: boolean }; schema_version: number; revision: number; data_csv_path: string; organization: Organization; theme: 'system' | 'dark' | 'light'; theme_colors:ThemeColors; logo_id: string | null; module_overrides: Record<string,ModuleOverride>; user_csv_path: string; user_import_profiles: ImportProfile[]; active_user_import: string; legacy_classification?: Record<string,unknown> | null; import_profiles: ImportProfile[]; active_import: string }
export interface ConfigurationResponse { progress?:{stage:string;source:string|null}|null; data_revision?: string; settings: Configuration; notice: string | null; error: string | null; loading: boolean; analysis: Record<string,unknown> }
export interface RegistryEntry { id: string; abbreviation: string; name: string; category: string; parent: string | null; aliases: string[]; icon: string; color: string; enabled: boolean; display_name: string | null; default_color?: string; default_icon?: string; default_name?: string }
export interface RegistryResponse { modules: RegistryEntry[]; icons: string[]; reference_note: string }
export interface ImportReport { file_name: string; detected_columns: string[]; parsed_rows: number; unique_roles: number; unique_transactions: number; transaction_assignments: number; duplicate_rows: number; warnings: string[]; errors: string[]; samples: Record<string,string>[]; analysis: Record<string,unknown> }
export const fetchConfiguration = () => apiRequest<ConfigurationResponse>('/api/configuration')
export const saveConfiguration = (settings: Configuration) => apiRequest<ConfigurationResponse>('/api/configuration','POST',settings)
export const fetchRegistry = () => apiRequest<RegistryResponse>('/api/registry/modules')
export const previewImport = (path: string, profile: ImportProfile) => apiRequest<ImportReport>('/api/import/preview','POST',{data_csv_path:path,profile})
export const detectHeaders = (path: string, profile: ImportProfile) => apiRequest<{detected_columns:string[];proposed_mapping:Record<string,string>;issues:string[]}>('/api/import/headers','POST',{data_csv_path:path,profile})
