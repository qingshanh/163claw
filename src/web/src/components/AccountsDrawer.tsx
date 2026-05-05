import { useEffect, useState } from "react";
import {
  fetchEnvConfig,
  testTelegram,
  updateAccount,
  updateEnvConfig,
  type Account,
  type EnvConfig
} from "../api";

type Props = {
  accounts: Account[];
  help: Record<string, string>;
  onSaved: (items: Account[], msg: string) => void;
  onError: (error: unknown) => void;
};

const FIELDS: Array<{ key: string; label: string; secret?: boolean; textarea?: boolean }> = [
  { key: "name", label: "显示名" },
  { key: "user_email", label: "Claw 主邮箱" },
  { key: "registered_email", label: "注册邮箱" },
  { key: "workspace_id", label: "Workspace ID" },
  { key: "parent_mailbox_id", label: "主邮箱 ID" },
  { key: "root_prefix", label: "主邮箱前缀" },
  { key: "domain", label: "域名" },
  { key: "api_key", label: "API Key", secret: true },
  { key: "dashboard_cookie", label: "Dashboard Cookie", secret: true, textarea: true },
  { key: "telegram_enabled", label: "电报通知" },
  { key: "telegram_bot_token", label: "Bot Token", secret: true },
  { key: "telegram_chat_id", label: "Chat ID" },
  { key: "telegram_api_base", label: "Telegram API" }
];

type Draft = Record<string, string | boolean>;
type EnvDraft = Record<string, string | boolean>;

function toDraft(account: Account): Draft {
  return {
    name: account.name ?? "",
    user_email: account.user_email ?? "",
    registered_email: account.registered_email ?? "",
    workspace_id: account.workspace_id ?? "",
    parent_mailbox_id: account.parent_mailbox_id ?? "",
    root_prefix: account.root_prefix ?? "",
    domain: account.domain ?? "claw.163.com",
    api_key: "",
    dashboard_cookie: "",
    telegram_enabled: Boolean(account.status.telegramEnabled),
    telegram_bot_token: "",
    telegram_chat_id: account.telegram_chat_id ?? "",
    telegram_api_base: account.telegram_api_base ?? "https://api.telegram.org"
  };
}

function sourceLabel(account: Account, key: string): string {
  const source = account.config_sources?.[key];
  return source === "env" ? "来自 .env" : "账号配置";
}

function booleanEnvKey(key: string): boolean {
  return key === "TELEGRAM_ENABLED" || key === "ENABLE_WS_LISTENERS";
}

export function AccountsDrawer({ accounts, help, onSaved, onError }: Props) {
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [envConfig, setEnvConfig] = useState<EnvConfig | null>(null);
  const [envDraft, setEnvDraft] = useState<EnvDraft>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [envBusy, setEnvBusy] = useState(false);

  useEffect(() => {
    setDrafts(Object.fromEntries(accounts.map((account) => [account.id, toDraft(account)])));
  }, [accounts]);

  useEffect(() => {
    fetchEnvConfig()
      .then((config) => {
        setEnvConfig(config);
        setEnvDraft(Object.fromEntries(config.items.map((item) => [item.key, booleanEnvKey(item.key) ? item.value.toLowerCase() === "true" : item.value])));
      })
      .catch(onError);
  }, []);

  function setValue(id: number, key: string, value: string | boolean) {
    setDrafts((current) => ({ ...current, [id]: { ...current[id], [key]: value } }));
  }

  function setEnvValue(key: string, value: string | boolean) {
    setEnvDraft((current) => ({ ...current, [key]: value }));
  }

  async function saveEnv() {
    setEnvBusy(true);
    try {
      const updated = await updateEnvConfig(envDraft);
      setEnvConfig(updated);
      setEnvDraft(Object.fromEntries(updated.items.map((item) => [item.key, booleanEnvKey(item.key) ? item.value.toLowerCase() === "true" : item.value])));
      onSaved(accounts, "环境变量已保存；端口、静态目录等启动项需要重启服务生效");
    } catch (error) {
      onError(error);
    } finally {
      setEnvBusy(false);
    }
  }

  async function save(account: Account) {
    const draft = drafts[account.id];
    setBusyId(account.id);
    try {
      const payload: any = { ...draft };
      if (!payload.api_key) delete payload.api_key;
      if (!payload.dashboard_cookie) delete payload.dashboard_cookie;
      if (!payload.telegram_bot_token) delete payload.telegram_bot_token;
      const updated = await updateAccount(account.id, payload);
      onSaved(accounts.map((item) => item.id === updated.id ? updated : item), "配置已保存");
    } catch (error) {
      onError(error);
    } finally {
      setBusyId(null);
    }
  }

  async function handleTestTelegram(account: Account) {
    setBusyId(account.id);
    try {
      await testTelegram(account.id);
      onSaved(accounts, "电报测试消息已发送");
    } catch (error) {
      onError(error);
    } finally {
      setBusyId(null);
    }
  }

  return (
      <div className="accounts-page accounts-drawer">
        <div className="settings-summary">
          <div>
            <strong>主账号配置</strong>
            <span>JSON 配置会自动同步到这里；在页面保存后会更新本地配置数据库。</span>
          </div>
          <span className="tag ok">{accounts.length} main accounts</span>
        </div>
        {envConfig && (
          <section className="account-config env-config">
            <div className="account-config-head">
              <div>
                <strong>全局环境变量</strong>
                <span>{envConfig.path}</span>
              </div>
              <span className="tag ok">.env</span>
            </div>
            {envConfig.items.map((item) => {
              const value = envDraft[item.key] ?? "";
              return (
                <label className="config-field" key={item.key}>
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.help}</small>
                  </span>
                  {booleanEnvKey(item.key) ? (
                    <input
                      type="checkbox"
                      checked={Boolean(value)}
                      onChange={(event) => setEnvValue(item.key, event.target.checked)}
                    />
                  ) : item.textarea ? (
                    <textarea
                      value={String(value)}
                      placeholder={item.secret && item.configured ? "已配置，留空则不修改" : ""}
                      onChange={(event) => setEnvValue(item.key, event.target.value)}
                    />
                  ) : (
                    <input
                      value={String(value)}
                      placeholder={item.secret && item.configured ? "已配置，留空则不修改" : ""}
                      onChange={(event) => setEnvValue(item.key, event.target.value)}
                    />
                  )}
                </label>
              );
            })}
            <div className="account-config-actions">
              <button className="primary" onClick={saveEnv} disabled={envBusy}>
                {envBusy ? "保存中" : "保存环境变量"}
              </button>
            </div>
          </section>
        )}
        <div className="accounts-body">
          {accounts.map((account) => {
            const draft = drafts[account.id] ?? toDraft(account);
            const root = account.root_prefix && account.domain ? `${account.root_prefix}@${account.domain}` : account.user_email;
            const telegramReady = Boolean(account.status.telegramEnabled && account.status.telegramConfigured);
            return (
              <section className="account-config" key={account.id}>
                <div className="account-config-head">
                  <div>
                    <strong>{root}</strong>
                    <span>{account.registered_email ? `注册邮箱 ${account.registered_email}` : account.name}</span>
                  </div>
                  <span className={`tag ${telegramReady ? "ok" : "muted"}`}>
                    {telegramReady ? "电报已开启" : account.status.telegramConfigured ? "电报未开启" : "电报未配置"}
                  </span>
                </div>
                {FIELDS.map((field) => {
                  const value = draft[field.key as string];
                  return (
                    <label className="config-field" key={field.key as string}>
                      <span>
                        <strong>{field.label}</strong>
                        <small>
                          {help[field.key as string]}
                          {field.key.startsWith("telegram_") && (
                            <em className="source-pill">{sourceLabel(account, field.key as string)}</em>
                          )}
                        </small>
                      </span>
                      {field.key === "telegram_enabled" ? (
                        <input
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(event) => setValue(account.id, field.key as string, event.target.checked)}
                        />
                      ) : field.textarea ? (
                        <textarea
                          value={String(value ?? "")}
                          placeholder={field.secret && account.has_dashboard_cookie_value ? "已配置，留空则不修改" : ""}
                          onChange={(event) => setValue(account.id, field.key as string, event.target.value)}
                        />
                      ) : (
                        <input
                          value={String(value ?? "")}
                          placeholder={field.secret && (account as any)[`has_${field.key}_value`] ? "已配置，留空则不修改" : ""}
                          onChange={(event) => setValue(account.id, field.key as string, event.target.value)}
                        />
                      )}
                    </label>
                  );
                })}
                <div className="account-config-actions">
                  <button onClick={() => handleTestTelegram(account)} disabled={busyId === account.id || !account.status.telegramConfigured}>
                    测试电报
                  </button>
                  <button className="primary" onClick={() => save(account)} disabled={busyId === account.id}>
                    {busyId === account.id ? "处理中" : "保存"}
                  </button>
                </div>
              </section>
            );
          })}
        </div>
      </div>
  );
}
