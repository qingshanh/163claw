export type Mailbox = {
  id: string;
  email: string;
  prefix: string;
  display_name: string | null;
  account_id: string | null;
  status: string;
  openclaw_status: string | null;
  install_command: string | null;
  auth_url: string | null;
  comm_level: number | null;
  ext_receive_type: number | null;
  ext_send_type: number | null;
  created_at: string;
  updated_at: string;
};

export type Account = {
  id: number;
  name: string | null;
  user_email: string | null;
  registered_email: string | null;
  workspace_id: string | null;
  workspace_name: string | null;
  parent_mailbox_id: string | null;
  root_prefix: string | null;
  domain: string;
  telegram_enabled: number;
  telegram_bot_token: string | null;
  telegram_chat_id: string | null;
  telegram_api_base: string | null;
  sort_order: number;
  has_api_key_value?: boolean;
  has_dashboard_cookie_value?: boolean;
  has_telegram_bot_token_value?: boolean;
  config_sources?: Record<string, string>;
  is_active: number;
  status: ClawAuthStatus;
};

export type MailSummary = {
  id: number;
  provider_mail_id: string;
  mailbox_email: string;
  source: string | null;
  address: string | null;
  subject: string | null;
  text: string | null;
  html: string | null;
  has_attachments: number;
  received_at: string | null;
  created_at: string;
};

export type MailDetail = MailSummary & {
  parsed: any;
  attachments: Array<{
    id: number;
    mail_id: number;
    provider_part_id: string;
    filename: string | null;
    content_type: string | null;
    size: number | null;
  }>;
};

export type ClawAuthStatus = {
  connected: boolean;
  hasApiKey: boolean;
  hasDashboardCookie: boolean;
  userEmail: string | null;
  workspaceId: string | null;
  workspaceName: string | null;
  parentMailboxId: string | null;
  rootPrefix: string | null;
  domain: string | null;
  apiKeyPrefix: string | null;
  apiKeySuffix: string | null;
  accountId?: number | null;
  accountName?: string | null;
  telegramEnabled?: boolean;
  telegramConfigured?: boolean;
};

export type EnvConfigItem = {
  key: string;
  label: string;
  help: string;
  value: string;
  configured: boolean;
  secret?: boolean;
  textarea?: boolean;
};

export type EnvConfig = {
  path: string;
  items: EnvConfigItem[];
};

export type ListenerSnapshot = {
  email: string;
  status: string;
  startedAt?: string | null;
  lastEventAt?: string | null;
  error?: string | null;
};

let adminPassword = localStorage.getItem("adminPassword") ?? "";

export function getAdminPassword() {
  return adminPassword;
}

export function setAdminPassword(value: string) {
  adminPassword = value;
  if (value) {
    localStorage.setItem("adminPassword", value);
  } else {
    localStorage.removeItem("adminPassword");
  }
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  adminPasswordOverride = adminPassword
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("x-admin-password", adminPasswordOverride);
  if (init.body !== undefined && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  const response = await fetch(path, {
    ...init,
    headers
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(data?.error ?? `HTTP ${response.status}`);
  }
  return data as T;
}

export async function verifyAdminPassword(value: string): Promise<ClawAuthStatus> {
  return requestJson<ClawAuthStatus>("/api/auth/claw/status", {}, value);
}

export async function fetchMailboxes(sync = false): Promise<Mailbox[]> {
  const data = await requestJson<{ items: Mailbox[] }>(`/api/mailboxes${sync ? "?sync=true" : ""}`);
  return data.items;
}

export async function fetchAccounts(): Promise<{ items: Account[]; help: Record<string, string> }> {
  return requestJson<{ items: Account[]; help: Record<string, string> }>("/api/accounts");
}

export async function fetchEnvConfig(): Promise<EnvConfig> {
  return requestJson<EnvConfig>("/api/config");
}

export async function updateEnvConfig(values: Record<string, string | boolean>): Promise<EnvConfig> {
  return requestJson<EnvConfig>("/api/config", {
    method: "PATCH",
    body: JSON.stringify({ values })
  });
}

export async function createAccount(input: {
  name?: string;
  user_email?: string;
  registered_email?: string;
  api_key: string;
  dashboard_cookie?: string;
  workspace_id?: string;
  parent_mailbox_id?: string;
  root_prefix?: string;
  domain?: string;
  telegram_enabled?: boolean;
  telegram_bot_token?: string;
  telegram_chat_id?: string;
  telegram_api_base?: string;
  sort_order?: number;
}): Promise<Account> {
  return requestJson<Account>("/api/accounts", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export async function updateAccount(id: number, input: Partial<{
  name: string;
  user_email: string;
  registered_email: string;
  api_key: string;
  dashboard_cookie: string;
  workspace_id: string;
  parent_mailbox_id: string;
  root_prefix: string;
  domain: string;
  telegram_enabled: boolean;
  telegram_bot_token: string;
  telegram_chat_id: string;
  telegram_api_base: string;
  sort_order: number;
  is_active: boolean;
}>): Promise<Account> {
  return requestJson<Account>(`/api/accounts/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input)
  });
}

export async function deleteAccount(id: number): Promise<void> {
  await requestJson<{ success: boolean }>(`/api/accounts/${id}`, {
    method: "DELETE"
  });
}

export async function testTelegram(accountId: number): Promise<void> {
  await requestJson<{ success: boolean }>(`/api/accounts/${accountId}/telegram-test`, {
    method: "POST"
  });
}

export async function testGlobalTelegram(): Promise<void> {
  await requestJson<{ success: boolean }>("/api/config/telegram-test", {
    method: "POST"
  });
}

export async function createMailbox(suffix: string, accountId?: number | null): Promise<Mailbox> {
  return requestJson<Mailbox>("/api/mailboxes", {
    method: "POST",
    body: JSON.stringify({ suffix, ...(accountId ? { account_id: accountId } : {}) })
  });
}

export async function deleteMailbox(id: string): Promise<void> {
  await requestJson<{ success: boolean }>(`/api/mailboxes/${encodeURIComponent(id)}`, {
    method: "DELETE"
  });
}

export type CommunicationSettingsInput = {
  commLevel: 0 | 1 | 2;
  extReceiveType?: 0 | 1;
  extSendType?: 0 | 1;
};

export async function updateMailboxCommunicationSettings(
  id: string,
  input: CommunicationSettingsInput
): Promise<Mailbox> {
  return requestJson<Mailbox>(`/api/mailboxes/${encodeURIComponent(id)}/comm-settings`, {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export async function fetchMails(
  mailbox?: string,
  limit = 50,
  offset = 0,
  sync = false
): Promise<{ items: MailSummary[]; count: number }> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (mailbox) params.set("mailbox", mailbox);
  if (sync) params.set("sync", "true");
  return requestJson(`/api/mails?${params.toString()}`);
}

export async function fetchMail(id: number): Promise<MailDetail> {
  return requestJson(`/api/mails/${id}`);
}

export async function deleteMail(id: number): Promise<void> {
  await requestJson<{ success: boolean }>(`/api/mails/${id}`, {
    method: "DELETE"
  });
}

export type SendMailInput = {
  from: string;
  to: string[];
  cc?: string[];
  bcc?: string[];
  subject?: string;
  body?: string;
  html?: boolean;
};

export async function sendMail(input: SendMailInput) {
  return requestJson<{ status: "sent" }>("/api/send", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export type ReplyMailInput = {
  mailId: number;
  body?: string;
  html?: boolean;
  toAll?: boolean;
};

export async function replyMail(input: ReplyMailInput) {
  return requestJson<{ status: "sent" }>("/api/reply", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export function createEventSource(): EventSource {
  return new EventSource(`/api/events?token=${encodeURIComponent(adminPassword)}`);
}

export async function fetchClawAuthStatus(): Promise<ClawAuthStatus> {
  return requestJson<ClawAuthStatus>("/api/auth/claw/status");
}

export async function sendClawLoginCode(email: string): Promise<void> {
  await requestJson<{ success: boolean }>("/api/auth/claw/send-code", {
    method: "POST",
    body: JSON.stringify({ email })
  });
}

export async function verifyClawLoginCode(email: string, code: string): Promise<{
  auth: ClawAuthStatus;
  syncedMailboxes: number;
}> {
  return requestJson("/api/auth/claw/verify-code", {
    method: "POST",
    body: JSON.stringify({ email, code })
  });
}

export async function refreshClawConnection(): Promise<{
  auth: ClawAuthStatus;
  syncedMailboxes: number;
}> {
  return requestJson("/api/auth/claw/refresh", {
    method: "POST"
  });
}

export async function disconnectClaw(): Promise<ClawAuthStatus> {
  return requestJson("/api/auth/claw/logout", {
    method: "POST"
  });
}

export async function fetchListeners(): Promise<ListenerSnapshot[]> {
  const data = await requestJson<{ items: ListenerSnapshot[] }>("/api/listeners");
  return data.items;
}
