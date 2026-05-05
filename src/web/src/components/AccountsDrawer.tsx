import { useEffect, useMemo, useState } from "react";
import {
  fetchEnvConfig,
  testGlobalTelegram,
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

function booleanConfigKey(key: string): boolean {
  return key === "TELEGRAM_ENABLED" || key === "ENABLE_WS_LISTENERS";
}

function sourceLabel(account: Account, key: string): string {
  return account.config_sources?.[key] === "global" ? "来自统一配置" : "账号覆盖";
}

function isTruthy(value: string | boolean | undefined): boolean {
  if (typeof value === "boolean") return value;
  return String(value ?? "").toLowerCase() === "true";
}

export function AccountsDrawer({ accounts, help, onSaved, onError }: Props) {
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [envConfig, setEnvConfig] = useState<EnvConfig | null>(null);
  const [envDraft, setEnvDraft] = useState<EnvDraft>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [envBusy, setEnvBusy] = useState(false);
  const [envTestBusy, setEnvTestBusy] = useState(false);

  useEffect(() => {
    setDrafts(Object.fromEntries(accounts.map((account) => [account.id, toDraft(account)])));
  }, [accounts]);

  useEffect(() => {
    fetchEnvConfig()
      .then((config) => {
        setEnvConfig(config);
        setEnvDraft(
          Object.fromEntries(
            config.items.map((item) => [item.key, booleanConfigKey(item.key) ? isTruthy(item.value) : item.value])
          )
        );
      })
      .catch(onError);
  }, [onError]);

  const envItemMap = useMemo(() => {
    return new Map((envConfig?.items ?? []).map((item) => [item.key, item]));
  }, [envConfig]);

  const canTestGlobalTelegram = useMemo(() => {
    const enabled = isTruthy(envDraft.TELEGRAM_ENABLED);
    const botTokenConfigured = Boolean(
      String(envDraft.TELEGRAM_BOT_TOKEN ?? "").trim() || envItemMap.get("TELEGRAM_BOT_TOKEN")?.configured
    );
    const chatConfigured = Boolean((String(envDraft.TELEGRAM_CHAT_ID ?? "").trim()) || envItemMap.get("TELEGRAM_CHAT_ID")?.configured);
    return enabled && botTokenConfigured && chatConfigured;
  }, [envDraft, envItemMap]);

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
      setEnvDraft(
        Object.fromEntries(
          updated.items.map((item) => [item.key, booleanConfigKey(item.key) ? isTruthy(item.value) : item.value])
        )
      );
      onSaved(accounts, "统一配置已保存");
    } catch (error) {
      onError(error);
    } finally {
      setEnvBusy(false);
    }
  }

  async function testEnv() {
    setEnvTestBusy(true);
    try {
      const updated = await updateEnvConfig(envDraft);
      setEnvConfig(updated);
      setEnvDraft(
        Object.fromEntries(
          updated.items.map((item) => [item.key, booleanConfigKey(item.key) ? isTruthy(item.value) : item.value])
        )
      );
      await testGlobalTelegram();
      onSaved(accounts, "统一配置已保存，Telegram 测试消息已发送");
    } catch (error) {
      onError(error);
    } finally {
      setEnvTestBusy(false);
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
      onSaved(accounts.map((item) => (item.id === updated.id ? updated : item)), "账号配置已保存");
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
          <strong>统一配置文件</strong>
          <span>这里会同步到 config.json，账号列表仍由下方主账号卡片管理。</span>
        </div>
        <span className="tag ok">{accounts.length} main accounts</span>
      </div>

      {envConfig && (
        <section className="account-config env-config">
          <div className="account-config-head">
            <div>
              <strong>全局设置</strong>
              <span>{envConfig.path}</span>
            </div>
            <span className="tag ok">config.json</span>
          </div>
          {envConfig.items.map((item) => {
            const value = envDraft[item.key] ?? "";
            return (
              <label className="config-field" key={item.key}>
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.help}</small>
                </span>
                {booleanConfigKey(item.key) ? (
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
            <button onClick={testEnv} disabled={envTestBusy || !canTestGlobalTelegram}>
              {envTestBusy ? "发送中..." : "测试推送"}
            </button>
            <button className="primary" onClick={saveEnv} disabled={envBusy}>
              {envBusy ? "保存中..." : "保存统一配置"}
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
                  {telegramReady ? "电报已启用" : account.status.telegramConfigured ? "电报未启用" : "电报未配置"}
                </span>
              </div>
              {FIELDS.map((field) => {
                const value = draft[field.key];
                return (
                  <label className="config-field" key={field.key}>
                    <span>
                      <strong>{field.label}</strong>
                      <small>
                        {help[field.key] || ""}
                        {field.key.startsWith("telegram_") && (
                          <em className="source-pill">{sourceLabel(account, field.key)}</em>
                        )}
                      </small>
                    </span>
                    {field.key === "telegram_enabled" ? (
                      <input
                        type="checkbox"
                        checked={Boolean(value)}
                        onChange={(event) => setValue(account.id, field.key, event.target.checked)}
                      />
                    ) : field.textarea ? (
                      <textarea
                        value={String(value ?? "")}
                        placeholder={field.secret && account.has_dashboard_cookie_value ? "已配置，留空则不修改" : ""}
                        onChange={(event) => setValue(account.id, field.key, event.target.value)}
                      />
                    ) : (
                      <input
                        value={String(value ?? "")}
                        placeholder={field.secret && (account as any)[`has_${field.key}_value`] ? "已配置，留空则不修改" : ""}
                        onChange={(event) => setValue(account.id, field.key, event.target.value)}
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
                  {busyId === account.id ? "保存中..." : "保存"}
                </button>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
