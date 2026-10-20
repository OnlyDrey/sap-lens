import { apiRequest } from './client'

export interface Organization { name: string; platform: string; custom_platform: string; system_id: string; client: string; description: string; footer: string }
export interface Domain { id: string; label: string; module_id: string | null }
export interface Rule { id: string; kind: 'prefix' | 'exact' | 'contains' | 'regex'; pattern: string; domain_id: string; priority: number; case_sensitive: boolean }
export interface ClassificationProfile { id: string; name: string; version: number; mode: 'legacy' | 'generic' | 'custom'; domains: Domain[]; rules: Rule[]; overrides: Record<string,string>; fallback_domain: string | null }
export interface ImportProfile { id: string; name: string; version: number; mapping: Record<string,string>; delimiter: string; encoding: string }
export interface ModuleOverride { display_name?: string | null; icon?: string | null; color?: string | null; enabled: boolean }
export interface Configuration { schema_version: number; revision: number; data_csv_path: string; organization: Organization; theme: 'system' | 'dark' | 'light'; logo_id: string | null; module_overrides: Record<string,ModuleOverride>; classification_profiles: ClassificationProfile[]; active_classification: string; import_profiles: ImportProfile[]; active_import: string }
export interface ConfigurationResponse { settings: Configuration; notice: string | null; error: string | null; loading: boolean; analysis: Record<string,unknown> }
export interface RegistryEntry { id: string; abbreviation: string; name: string; category: string; parent: string | null; aliases: string[]; icon: string; color: string; enabled: boolean; display_name: string | null }
export interface RegistryResponse { modules: RegistryEntry[]; icons: string[]; reference_note: string }
export interface ImportReport { file_name: string; detected_columns: string[]; parsed_rows: number; unique_roles: number; unique_transactions: number; transaction_assignments: number; duplicate_rows: number; warnings: string[]; errors: string[]; samples: Record<string,string>[]; analysis: Record<string,unknown> }
export interface ClassificationReport { total_roles: number; counts: Record<string,number>; unclassified_roles: number; ambiguous_matches: number; conflicting_rules: {rule_ids: string[]; reason: string}[]; changed_roles: number; samples: {agr_name: string; module_id: string; domain_id: string | null; ambiguous: boolean; changed: boolean}[]; test_result: Record<string,unknown> | null; profile_fingerprint: string }
export const fetchConfiguration = () => apiRequest<ConfigurationResponse>('/api/configuration')
export const saveConfiguration = (settings: Configuration) => apiRequest<ConfigurationResponse>('/api/configuration','POST',settings)
export const fetchRegistry = () => apiRequest<RegistryResponse>('/api/registry/modules')
export const previewImport = (path: string, profile: ImportProfile) => apiRequest<ImportReport>('/api/import/preview','POST',{data_csv_path:path,profile})
export const detectHeaders = (path: string, profile: ImportProfile) => apiRequest<{detected_columns:string[]}>('/api/import/headers','POST',{data_csv_path:path,profile})
export const previewClassification = (profile: ClassificationProfile, test_role?: string) => apiRequest<ClassificationReport>('/api/classification/preview','POST',{profile,test_role:test_role || null})
