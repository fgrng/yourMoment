// Repo über `git` im Checkout des Hosts.

import { execFileSync } from "node:child_process";
import { MAIN_REF, type Repo, STANDALONE_BRANCH } from "./iteration.mts";

/** Das Repo des Hosts; kein Aufruf ändert dessen Checkout oder Arbeitsverzeichnis. */
export const gitRepo: Repo = {
  async fetch(): Promise<void> {
    git(["fetch", "--quiet", "origin"]);
  },

  async hostBranch(): Promise<string> {
    return git(["rev-parse", "--abbrev-ref", "HEAD"]).trim();
  },

  async contains(branch: string, ref: string): Promise<boolean> {
    // Exit-Code 1 heißt „nicht enthalten“; ein unbekannter Ref zählt ebenso.
    return succeeds(["merge-base", "--is-ancestor", ref, branch]);
  },

  async mentionsIssue(ref: string, issue: number): Promise<boolean> {
    // In der einfachen Regex ist `(` ein Zeichen; `[,)]` trennt #12 von #120.
    const grep = ["--basic-regexp", `--grep=(#${issue}[,)]`];
    return git(["log", "--format=%H", "-1", ...grep, ref]).trim() !== "";
  },

  async branchExists(branch: string): Promise<boolean> {
    return succeeds(["rev-parse", "--verify", "--quiet", `refs/heads/${branch}`]);
  },

  async createBranch(branch: string, base: string): Promise<void> {
    // `git branch` setzt nur die Ref; der Checkout des Hosts bleibt, wo er ist.
    // Ohne Upstream, auch wenn `base` ein Remote-Branch ist.
    git(["branch", "--no-track", branch, base]);
  },

  async branches(prefix: string): Promise<string[]> {
    return git(["for-each-ref", "--format=%(refname:short)", `refs/heads/${prefix}`])
      .split("\n")
      .filter(Boolean);
  },

  async mergeMain(branch: string): Promise<"clean" | "conflict"> {
    if (await gitRepo.contains(branch, MAIN_REF)) return "clean";
    // Ein Branch, der in einem Worktree ausgecheckt ist, würde dort hinter dem
    // Rücken des Checkouts verschoben.
    if (checkedOutBranches().has(branch)) {
      throw new Error(`${branch} is checked out in a worktree`);
    }
    const head = await gitRepo.head(branch);
    let tree: string;
    try {
      // Mergt ohne Worktree und ohne Index; Exit-Code 1 heißt Konflikt.
      tree = git(["merge-tree", "--write-tree", head, MAIN_REF]).split("\n")[0];
    } catch (error) {
      if ((error as { status?: number }).status === 1) return "conflict";
      throw error;
    }
    const commit = git([
      "commit-tree",
      tree,
      "-p",
      head,
      "-p",
      MAIN_REF,
      "-m",
      `Merge branch '${MAIN_REF}' into ${branch}`,
    ]).trim();
    git(["update-ref", `refs/heads/${branch}`, commit, head]);
    return "clean";
  },

  async fastForward(branch: string, to: string): Promise<boolean> {
    if (!(await gitRepo.contains(to, branch))) return false;
    // Den Branch eines Worktrees verschiebt nur, wer dort arbeitet.
    if (checkedOutBranches().has(branch)) return false;
    // Der alte Stand als dritter Wert: Ist `branch` inzwischen weiter, scheitert update-ref.
    git(["update-ref", `refs/heads/${branch}`, await gitRepo.head(to), await gitRepo.head(branch)]);
    return true;
  },

  async head(branch: string): Promise<string> {
    // Lokaler Branch oder Remote-Ref wie origin/main.
    return git(["rev-parse", "--verify", `${branch}^{commit}`]).trim();
  },

  async resetBranch(branch: string, head: string): Promise<void> {
    git(["update-ref", `refs/heads/${branch}`, head]);
  },

  async isPushed(branch: string): Promise<boolean> {
    try {
      const [local, remote] = git([
        "rev-parse",
        `refs/heads/${branch}`,
        `refs/remotes/origin/${branch}`,
      ])
        .trim()
        .split("\n");
      return local === remote;
    } catch {
      return false;
    }
  },

  async push(branch: string): Promise<void> {
    // Nur sandcastle/standalone beginnt nach einem gemergten PR neu von main;
    // sein Push ist dann kein Fast-Forward. Die Lease schützt Commits auf
    // origin, die dieser Checkout noch nicht kennt. Ein Spec-Branch wächst nur.
    const force = branch === STANDALONE_BRANCH ? ["--force-with-lease"] : [];
    git(["push", ...force, "origin", `${branch}:${branch}`]);
  },
};

// Führt git aus und liefert stdout; wirft bei einem Exit-Code ungleich 0.
function git(args: string[]): string {
  return execFileSync("git", args, { encoding: "utf8", stdio: "pipe" });
}

// Ob git mit Exit-Code 0 endet.
function succeeds(args: string[]): boolean {
  try {
    git(args);
    return true;
  } catch {
    return false;
  }
}

// Die Branches, die in irgendeinem Worktree des Repos ausgecheckt sind.
function checkedOutBranches(): Set<string> {
  return new Set(
    git(["worktree", "list", "--porcelain"])
      .split("\n")
      .filter((line) => line.startsWith("branch refs/heads/"))
      .map((line) => line.slice("branch refs/heads/".length)),
  );
}
