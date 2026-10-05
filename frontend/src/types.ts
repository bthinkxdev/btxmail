export type Role = "SUPER_ADMIN" | "OPS_ADMIN" | "BUSINESS_ADMIN";

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  business: number | null;
  business_name: string | null;
  is_active: boolean;
  totp_enabled: boolean;
  must_change_password: boolean;
  date_joined: string;
  last_login: string | null;
}

export interface Me extends User {
  setup_required: null | "password_change_required" | "two_factor_setup_required";
  is_platform_staff: boolean;
  is_super_admin: boolean;
  business_status: string | null;
}

export interface Plan {
  id: number;
  code: string;
  name: string;
  description: string;
  max_domains: number;
  max_mailboxes: number;
  max_aliases: number;
  default_mailbox_quota_mb: number;
  max_mailbox_quota_mb: number;
  total_storage_mb: number;
  outbound_per_hour: number;
  outbound_per_day: number;
  is_active: boolean;
}

export interface Business {
  id: number;
  name: string;
  legal_name: string;
  status: "ACTIVE" | "SUSPENDED" | "CLOSED";
  contact_person: string;
  contact_email: string;
  contact_phone: string;
  plan: number;
  plan_detail: Plan;
  notes: string;
  suspended_reason: string;
  usage: {
    domains: number;
    mailboxes: number;
    aliases: number;
    allocated_storage_mb: number;
    used_storage_bytes: number;
  };
  created_at: string;
}

export type CheckStatus = "PASS" | "FAIL" | "WARN" | "UNKNOWN";

export interface DnsRecord {
  purpose: "VERIFICATION" | "MX" | "SPF" | "DKIM" | "DMARC" | "AUTODISCOVER" | "AUTOCONFIG";
  type: string;
  name: string;
  value: string;
  priority?: number;
  required: boolean;
}

export interface DnsCheckDetail {
  status: CheckStatus;
  message: string;
  found: string[];
}

export interface DnsStatus {
  mx_status: CheckStatus;
  spf_status: CheckStatus;
  dkim_status: CheckStatus;
  dmarc_status: CheckStatus;
  ptr_status: CheckStatus;
  details: Partial<Record<"mx" | "spf" | "dkim" | "dmarc" | "ptr", DnsCheckDetail>>;
  last_checked: string | null;
  is_ready: boolean;
}

export type DomainStatus =
  | "PENDING_VERIFICATION"
  | "PROVISIONING"
  | "DNS_PENDING"
  | "ACTIVE"
  | "PROVISIONING_FAILED"
  | "SUSPENDED"
  | "DELETING";

export interface Domain {
  id: number;
  business: number;
  business_name: string;
  name: string;
  status: DomainStatus;
  verification_method: "DNS_TXT" | "MANUAL";
  verification: {
    record_type: string;
    record_name: string;
    record_value: string;
    started_at: string;
    last_attempt_at: string | null;
  };
  verified_at: string | null;
  mailcow_provisioned: boolean;
  dkim_selector: string;
  dns_records: DnsRecord[];
  dns_status: DnsStatus | null;
  mailbox_count: number;
  alias_count: number;
  last_error: string;
  created_at: string;
}

export type MailboxStatus = "PENDING" | "ACTIVE" | "SUSPENDED" | "DISABLED" | "FAILED" | "DELETING";

export interface Mailbox {
  id: number;
  business: number;
  business_name: string;
  domain: number;
  domain_name: string;
  local_part: string;
  email: string;
  display_name: string;
  status: MailboxStatus;
  quota_mb: number;
  used_bytes: number;
  message_count: number;
  usage_percent: number;
  outbound_suspended: boolean;
  outbound_suspended_reason: string;
  outbound_suspended_at: string | null;
  outbound_limit_per_hour: number | null;
  outbound_limit_per_day: number | null;
  effective_limit_per_hour: number;
  effective_limit_per_day: number;
  last_login_at: string | null;
  last_synced_at: string | null;
  last_error: string;
  webmail_url: string;
  created_at: string;
  temporary_password?: string;
}

export interface Alias {
  id: number;
  business: number;
  business_name: string;
  domain: number;
  domain_name: string;
  source_address: string;
  destinations: string[];
  status: "ACTIVE" | "DISABLED";
  created_at: string;
}

export interface SecurityEvent {
  id: number;
  business: number | null;
  business_name: string | null;
  mailbox: number | null;
  mailbox_email: string | null;
  subject: string;
  event_type: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  source_ip: string | null;
  message_count: number;
  description: string;
  details: Record<string, unknown>;
  action_taken: string;
  detected_at: string;
  resolved_at: string | null;
  resolved_by_email: string | null;
  resolution_note: string;
  is_open: boolean;
}

export interface AuditEntry {
  id: number;
  timestamp: string;
  actor_email: string;
  actor_role: string;
  business: number | null;
  business_name: string | null;
  action: string;
  object_type: string;
  object_id: string;
  object_repr: string;
  ip_address: string | null;
  user_agent: string;
  request_id: string;
  metadata: Record<string, unknown>;
}

export interface Dashboard {
  domains: { total: number; active: number; pending: number };
  mailboxes: { total: number; active: number; suspended: number; outbound_suspended: number };
  storage: { allocated_mb: number; used_bytes: number };
  open_security_events: number;
  recent_security_events: Pick<
    SecurityEvent,
    "id" | "event_type" | "severity" | "subject" | "description" | "detected_at" | "action_taken"
  >[];
  businesses?: { total: number; active: number; suspended: number };
  business?: {
    id: number;
    name: string;
    status: string;
    plan: Plan;
    limits: { domains: number; mailboxes: number; storage_mb: number; aliases: number };
    aliases: number;
  };
}

export interface Alert {
  id: number;
  key: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  title: string;
  message: string;
  business: number | null;
  delivered: boolean;
  delivery_error: string;
  created_at: string;
  acknowledged_at: string | null;
}

export interface Reputation {
  mail_ip: string;
  mail_hostname: string;
  status: "HEALTHY" | "LISTED";
  blacklists: { zone: string; listed: boolean; response: string; error: string; checked_at: string }[];
  components: Record<string, { status: string; message: string; checked_at: string; details: Record<string, unknown> }>;
}
