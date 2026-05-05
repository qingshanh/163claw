import type { Account, Mailbox } from "./api";

function lower(value: string | null | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

export function rootMailboxEmail(account: Pick<Account, "root_prefix" | "domain" | "user_email"> | null | undefined): string | null {
  if (!account) return null;
  const rootPrefix = lower(account.root_prefix);
  const domain = lower(account.domain || "claw.163.com");
  if (rootPrefix && domain) {
    return `${rootPrefix}@${domain}`;
  }
  const userEmail = lower(account.user_email);
  return userEmail && domain && userEmail.endsWith(`@${domain}`) ? userEmail : null;
}

export function mailboxMatchesAccount(mailbox: Mailbox, account: Account | null | undefined): boolean {
  if (!account) return false;

  if (account.id && Number(mailbox.account_id) === account.id) {
    return true;
  }

  const email = lower(mailbox.email);
  if (!email) return false;

  const userEmail = lower(account.user_email);
  if (userEmail && email === userEmail) {
    return true;
  }

  const rootEmail = rootMailboxEmail(account);
  if (rootEmail && email === rootEmail) {
    return true;
  }

  const rootPrefix = lower(account.root_prefix);
  const domain = lower(account.domain || "claw.163.com");
  const mailboxPrefix = lower(mailbox.prefix || email.split("@", 1)[0]);
  if (rootPrefix && mailboxPrefix) {
    if (mailboxPrefix === rootPrefix) {
      return true;
    }
    if (domain && email.endsWith(`@${domain}`) && mailboxPrefix.startsWith(`${rootPrefix}.`)) {
      return true;
    }
  }

  return false;
}

export function isRootMailboxForAccount(mailbox: Mailbox, account: Account | null | undefined): boolean {
  if (!account) return false;

  const email = lower(mailbox.email);
  const rootEmail = rootMailboxEmail(account);
  if (rootEmail && email === rootEmail) {
    return true;
  }

  const userEmail = lower(account.user_email);
  if (userEmail && email === userEmail && email.endsWith("@claw.163.com")) {
    return true;
  }

  return false;
}

export function groupMailboxesByAccount(accounts: Account[], mailboxes: Mailbox[]): Array<{
  account: Account | null;
  rootMailbox: Mailbox | null;
  childMailboxes: Mailbox[];
}> {
  if (accounts.length === 0) {
    return [{ account: null, rootMailbox: null, childMailboxes: mailboxes.slice() }];
  }

  return accounts.map((account) => {
    const matched = mailboxes.filter((mailbox) => mailboxMatchesAccount(mailbox, account));
    const rootMailbox = matched.find((mailbox) => isRootMailboxForAccount(mailbox, account)) ?? null;
    const childMailboxes = matched.filter((mailbox) => !isRootMailboxForAccount(mailbox, account));
    return { account, rootMailbox, childMailboxes };
  });
}
