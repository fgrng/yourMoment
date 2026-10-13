// Tracker über die GitHub-CLI `gh`.

import { execFileSync } from "node:child_process";
import type {
  IssueSummary,
  PullRequest,
  PullRequestText,
  Ticket,
  Tracker,
} from "./iteration.mts";

// Führt gh aus und liefert stdout; wirft bei einem Exit-Code ungleich 0.
function gh(args: string[]): string {
  return execFileSync("gh", args, { encoding: "utf8", stdio: "pipe" });
}

// Die Felder eines Issues aus der REST-API, die der Tracker braucht.
type ApiIssue = {
  number: number;
  state: string;
  labels: { name: string }[];
  sub_issues_summary: { total: number; completed: number };
};

// Übersetzt ein Issue der REST-API in eine IssueSummary.
function summary(issue: ApiIssue): IssueSummary {
  return {
    number: issue.number,
    open: issue.state === "open",
    labels: issue.labels.map((l) => l.name),
    subIssues: {
      total: issue.sub_issues_summary.total,
      completed: issue.sub_issues_summary.completed,
    },
  };
}

/** Der Tracker des Repos auf GitHub, über die Anmeldung von `gh`. */
export const githubTracker: Tracker = {
  async readyTickets(): Promise<Ticket[]> {
    const issues: {
      number: number;
      title: string;
      body: string;
      labels: { name: string }[];
      comments: { body: string }[];
      blockedBy: { nodes: { number: number }[] };
    }[] = JSON.parse(
      gh([
        "issue",
        "list",
        "--state",
        "open",
        "--label",
        "ready-for-agent",
        "--search",
        "-label:Spec -is:blocked",
        "--limit",
        "100",
        "--json",
        "number,title,body,labels,comments,blockedBy",
      ]),
    );
    return issues.map((i) => ({
      number: i.number,
      title: i.title,
      body: i.body,
      labels: i.labels.map((l) => l.name),
      comments: i.comments.map((c) => c.body),
      blockedBy: i.blockedBy.nodes.map((b) => b.number),
    }));
  },

  async parentOf(issue: number): Promise<IssueSummary | undefined> {
    try {
      return summary(JSON.parse(gh(["api", `repos/{owner}/{repo}/issues/${issue}/parent`])));
    } catch (error) {
      // GitHub antwortet mit 404, wenn das Issue kein Eltern-Issue hat.
      const stderr = String((error as { stderr?: unknown }).stderr ?? "");
      if (stderr.includes("HTTP 404")) return undefined;
      throw error;
    }
  },

  async issue(issue: number): Promise<IssueSummary> {
    return summary(JSON.parse(gh(["api", `repos/{owner}/{repo}/issues/${issue}`])));
  },

  async close(issue: number, comment: string): Promise<void> {
    gh(["issue", "close", String(issue), "--comment", comment]);
  },

  async comment(issue: number, comment: string): Promise<void> {
    gh(["issue", "comment", String(issue), "--body", comment]);
  },

  async swapLabel(issue: number, remove: string, add: string): Promise<void> {
    gh(["issue", "edit", String(issue), "--remove-label", remove, "--add-label", add]);
  },

  async pullRequest(head: string): Promise<PullRequest | undefined> {
    // gh listet die neuesten PRs zuerst.
    const prs: {
      number: number;
      headRefName: string;
      baseRefName: string;
      title: string;
      body: string;
      state: "OPEN" | "MERGED" | "CLOSED";
    }[] = JSON.parse(
      gh([
        "pr",
        "list",
        "--head",
        head,
        "--state",
        "all",
        "--limit",
        "20",
        "--json",
        "number,headRefName,baseRefName,title,body,state",
      ]),
    );
    const pr = prs.find((p) => p.state === "OPEN") ?? prs[0];
    if (!pr) return undefined;
    return {
      number: pr.number,
      head: pr.headRefName,
      base: pr.baseRefName,
      title: pr.title,
      body: pr.body,
      state: pr.state === "OPEN" ? "open" : pr.state === "MERGED" ? "merged" : "closed",
    };
  },

  async createPullRequest(pr: PullRequestText & { head: string; base: string }): Promise<void> {
    gh(["pr", "create", "--head", pr.head, "--base", pr.base, "--title", pr.title, "--body", pr.body]);
  },

  async updatePullRequest(number: number, text: PullRequestText): Promise<void> {
    gh(["pr", "edit", String(number), "--title", text.title, "--body", text.body]);
  },
};
