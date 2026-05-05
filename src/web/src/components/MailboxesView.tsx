import type { Account, ClawAuthStatus, Mailbox } from "../api";
import { usePrefs } from "../i18n";
import { parseServerTime } from "../time";

type Props = {
  mailboxes: Mailbox[];
  accounts: Account[];
  clawAuth: ClawAuthStatus | null;
  suffix: string;
  setSuffix: (value: string) => void;
  selectedAccountId: number | null;
  setSelectedAccountId: (value: number | null) => void;
  onCreate: () => void;
  onDeleteAccount: (account: Account) => void;
  onMoveAccount: (account: Account, direction: -1 | 1) => void;
  onDelete: (mailbox: Mailbox) => void;
  onOpen: (mailbox: Mailbox) => void;
  onConfigureRules: (mailbox: Mailbox) => void;
};

function relTime(value: string, t: (key: string, vars?: Record<string, string | number>) => string): string {
  if (!value) return "—";
  const date = parseServerTime(value);
  if (Number.isNaN(date.getTime())) return value;
  const diff = Date.now() - date.getTime();
  const min = Math.round(diff / 60000);
  if (min < 1) return t("time.justNow");
  if (min < 60) return t("time.mAgo", { n: min });
  const h = Math.round(min / 60);
  if (h < 24) return t("time.hAgo", { n: h });
  const d = Math.round(h / 24);
  return t("time.dAgo", { n: d });
}

function ruleLabel(mailbox: Mailbox, t: (key: string) => string): string {
  if (mailbox.comm_level === 0) return t("mb.rules.personal");
  if (mailbox.comm_level === 1) return t("mb.rules.internal");
  if (mailbox.comm_level === 2 && mailbox.ext_receive_type === 1) {
    return t("mb.rules.receiveAll");
  }
  if (mailbox.comm_level === 2) return t("mb.rules.external");
  return t("mb.rules.unknown");
}

function clawEmail(account: Account | null): string | null {
  if (!account) return null;
  if (account.root_prefix && account.domain) return `${account.root_prefix}@${account.domain}`;
  if (account.user_email?.endsWith("@claw.163.com")) return account.user_email;
  return null;
}

export function MailboxesView({
  mailboxes,
  accounts,
  clawAuth,
  suffix,
  setSuffix,
  selectedAccountId,
  setSelectedAccountId,
  onCreate,
  onDeleteAccount,
  onMoveAccount,
  onDelete,
  onOpen,
  onConfigureRules
}: Props) {
  const { t } = usePrefs();
  const selectedAccount = accounts.find((account) => account.id === selectedAccountId) ?? accounts[0] ?? null;
  const rootPrefix = selectedAccount?.root_prefix ?? (clawAuth?.rootPrefix || null);
  const domain = selectedAccount?.domain ?? (clawAuth?.domain || null);
  const canCreate = Boolean(rootPrefix && domain);

  const isPrimary = (m: Mailbox): boolean => {
    const account = accounts.find((item) => item.id === Number(m.account_id));
    const rootEmail = account?.root_prefix && account?.domain
      ? `${account.root_prefix}@${account.domain}`
      : clawAuth?.rootPrefix && clawAuth?.domain
        ? `${clawAuth.rootPrefix}@${clawAuth.domain}`
        : null;
    return Boolean(rootEmail && m.email.toLowerCase() === rootEmail.toLowerCase());
  };

  const grouped = accounts.length > 0
    ? accounts.map((account) => ({
        account,
        items: mailboxes.filter((mailbox) => Number(mailbox.account_id) === account.id && mailbox.email !== clawEmail(account))
      }))
    : [{ account: null, items: mailboxes }];

  return (
    <div className="stagger">
      <div className="create-bar">
        <span className="label">{t("mb.forge")}</span>
        <select
          className="account-select"
          value={selectedAccountId ?? selectedAccount?.id ?? ""}
          onChange={(event) => setSelectedAccountId(event.target.value ? Number(event.target.value) : null)}
        >
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>
              {account.name || account.user_email || `${account.root_prefix}@${account.domain}`}
            </option>
          ))}
        </select>
        <div className="composer">
          {canCreate ? (
            <>
              <span>{rootPrefix}.</span>
              <input
                value={suffix}
                onChange={(event) => setSuffix(event.target.value.toLowerCase().replace(/[^a-z0-9]/g, ""))}
                placeholder={t("mb.placeholder.suffix")}
              />
              <span>@{domain}</span>
            </>
          ) : (
            <span>{t("mb.root.pending")}</span>
          )}
        </div>
        <span className="hint">{selectedAccount?.status?.hasDashboardCookie ? t("mb.hint") : "API key mode"}</span>
        <button
          className="primary"
          onClick={onCreate}
          disabled={!suffix || !canCreate}
        >
          {t("mb.create")}
        </button>
      </div>

      {accounts.length === 0 && mailboxes.length === 0 ? (
        <div className="empty-state">
          <span className="big">{t("mb.empty.head")}</span>
          {t("mb.empty.body")}
        </div>
      ) : (
        <div className="account-stack">
          {grouped.map(({ account, items }) => (
            <section className="account-group" key={account?.id ?? "default"}>
              <div className="account-head">
                <div>
                  <strong>{clawEmail(account) || t("mb.row.primary")}</strong>
                  <span>{account?.registered_email ? `注册邮箱 ${account.registered_email}` : account?.user_email && !account.user_email.endsWith("@claw.163.com") ? `注册邮箱 ${account.user_email}` : account?.name || "default"}</span>
                </div>
                <div className="account-head-actions">
                  <span className={`tag ${account?.status?.hasApiKey ? "ok" : "muted"}`}>
                    <span className={`dot ${account?.status?.hasApiKey ? "live" : ""}`} />
                    {items.length} boxes
                  </span>
                  {account && (
                    <>
                      <button onClick={() => onMoveAccount(account, -1)}>上移</button>
                      <button onClick={() => onMoveAccount(account, 1)}>下移</button>
                      <button className="danger" onClick={() => onDeleteAccount(account)}>删除主账号</button>
                    </>
                  )}
                </div>
              </div>
              <div className="mb-table">
                <div className="mb-row head">
                  <span>{t("mb.head.mailbox")}</span>
                  <span>{t("mb.head.status")}</span>
                  <span>{t("mb.head.rules")}</span>
                  <span>{t("mb.head.created")}</span>
                  <span style={{ textAlign: "right" }}>{t("mb.head.ops")}</span>
                </div>
                {items.map((mailbox) => (
                  <div className="mb-row" key={mailbox.id}>
                    <div className="email-cell">
                      <span className="e">{mailbox.email}</span>
                      <span className="pref">
                        {isPrimary(mailbox)
                          ? t("mb.row.primary")
                          : t("mb.row.prefix", { p: mailbox.prefix })}
                      </span>
                    </div>
                    <div>
                      <span className={`tag ${mailbox.status === "active" ? "ok" : "muted"}`}>
                        <span className={`dot ${mailbox.status === "active" ? "live" : ""}`} />
                        {mailbox.status}
                      </span>
                    </div>
                    <div>
                      <span className={`tag ${mailbox.comm_level === 2 && mailbox.ext_receive_type === 1 ? "ok" : "muted"}`}>
                        <span className={`dot ${mailbox.comm_level === 2 && mailbox.ext_receive_type === 1 ? "live" : ""}`} />
                        {ruleLabel(mailbox, t)}
                      </span>
                    </div>
                    <div className="time-cell">{relTime(mailbox.created_at, t)}</div>
                    <div className="ops">
                      <button onClick={() => onOpen(mailbox)}>{t("mb.row.open")}</button>
                      <button
                        onClick={() => onConfigureRules(mailbox)}
                        disabled={!account?.status?.hasDashboardCookie}
                      >
                        {t("mb.row.rules")}
                      </button>
                      <button
                        className="danger"
                        onClick={() => onDelete(mailbox)}
                        disabled={isPrimary(mailbox)}
                      >
                        {t("mb.row.delete")}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
