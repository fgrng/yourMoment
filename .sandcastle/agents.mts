// Agents über Sandcastle: Line-ups je CLI, Docker-Sandbox mit den
// Auth-Mounts des Hosts und die Agent-Läufe der einzelnen Phasen.

import os from "node:os";
import path from "node:path";
import * as sandcastle from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { z } from "zod";
import type {
  AgentRun,
  Agents,
  PlannedIssue,
  PullRequestText,
  SpecReview,
  Ticket,
  TicketSession,
} from "./iteration.mts";
import { ticketBranch } from "./iteration.mts";

// Mounts für die Ordner .codex und .claude mit den Zugangsdaten des Hosts.
// <user>
const hostCodexHome = path.join(os.homedir(), ".codex");
const sandboxCodexMount = "/mnt/host-codex";
const sandboxCodexHome = "/home/agent/.codex";

const hostClaudeHome = path.join(os.homedir(), ".claude");
const sandboxClaudeMount = "/mnt/host-claude";
const sandboxClaudeHome = "/home/agent/.claude";
// </user>

// Höchstzahl der Agent-Aufrufe des Implementers je Ticket. Der
// Implement-Prompt ist als Ralph-Schleife geschrieben („REPEAT until done“,
// Notizen für die nächste Iteration); das trägt nur, wenn der Agent nach
// einem Lauf ohne Abschlusssignal erneut startet. Sandcastles Default von 1
// bräche die Schleife still nach dem ersten Aufruf ab.
const MAX_IMPLEMENT_ITERATIONS = 20;

// ---------------------------------------------------------------------------
// Line-ups: hier werden die Modelle je Phase getauscht
// ---------------------------------------------------------------------------
//
// Ein Line-up je CLI, gewählt beim Start mit `--agent`. Beide CLIs sind im
// Image installiert und werden von den Hooks unten angemeldet, also läuft
// jedes Line-up ohne weitere Einrichtung.

/** Die Agent-CLI und das Modell je Phase. */
export type Lineup = {
  planner: sandcastle.AgentProvider;
  implementer: sandcastle.AgentProvider;
  reviewer: sandcastle.AgentProvider;
  merger: sandcastle.AgentProvider;
};

/** Die wählbaren Line-ups, nach dem Namen für `--agent`. */
export const LINEUPS: Record<string, Lineup> = {
  claude: {
    planner: sandcastle.claudeCode("claude-sonnet-5", { effort: "medium" }),
    implementer: sandcastle.claudeCode("claude-opus-5-5", { effort: "medium" }),
    reviewer: sandcastle.claudeCode("claude-opus-5-5", { effort: "high" }),
    merger: sandcastle.claudeCode("claude-opus-5-5", { effort: "high" }),
  },
  codex: {
    planner: sandcastle.codex("gpt-5.6-terra"),
    implementer: sandcastle.codex("gpt-5.6-sol", { effort: "medium" }),
    reviewer: sandcastle.codex("gpt-5.6-sol", { effort: "high" }),
    merger: sandcastle.codex("gpt-5.6-sol", { effort: "high" }),
  },
};

/** Das Line-up ohne `--agent`. */
export const DEFAULT_LINEUP = "claude";

// Die Form, die der Planner in seinem <plan>-Tag ausgeben muss. Sandcastle
// prüft sie, sodass ein fehlerhafter oder fehlender Plan mit einem
// Schema-Fehler scheitert statt mit einem rohen JSON.parse-Absturz.
const planSchema = z.object({
  issues: z.array(
    z.object({ id: z.string(), title: z.string(), branch: z.string() }),
  ),
});

// Befunde des Spec-Reviews im <spec-review>-Tag, siehe spec-review-prompt.md.
const specReviewSchema = z.object({
  standards: z.array(z.string()),
  correctness: z.array(z.string()),
  spec: z.array(z.string()),
});

// Titel und Text des Spec-PRs im <pull-request>-Tag, siehe pr-prompt.md.
const pullRequestSchema = z.object({
  title: z.string().min(1),
  body: z.string().min(1),
});

// Ein ungültiger Tag kostete sonst die ganze Abschlussphase; der Agent
// bekommt den Fehler zurück und gibt neu aus.
const OUTPUT_RETRIES = 2;

// Die docker()-Sandbox mit den schreibgeschützten Auth-Mounts des Hosts und
// CODEX_HOME. Jede Phase bekommt einen frisch konfigurierten Container.
// Claude Code braucht keine entsprechende Variable: /home/agent/.claude ist
// für den Agent-User in der Sandbox ohnehin der Standardort.
const agentSandbox = () =>
  docker({
    env: { CODEX_HOME: sandboxCodexHome },
    mounts: [
      { hostPath: hostCodexHome, sandboxPath: sandboxCodexMount, readonly: true },
      { hostPath: hostClaudeHome, sandboxPath: sandboxClaudeMount, readonly: true },
    ],
  });

// Die Hooks laufen in der Sandbox, bevor der Agent startet. Der erste Befehl
// bringt die Abhängigkeiten des Projekts auf den Stand des Worktrees: Das
// Image (siehe .sandcastle/Dockerfile) trägt eine fertige virtualenv unter
// /home/agent/venv mit requirements-dev.txt, außerhalb des gemounteten
// Workspace; `uv pip install` prüft sie gegen die Datei im Worktree und
// installiert nur, was dort inzwischen dazukam. Die Testsuite braucht keine
// .env: tests/conftest.py setzt ihre Umgebung selbst. Der zweite und dritte
// Befehl kopieren die Zugangsdaten von Codex und Claude Code aus den
// schreibgeschützten Mounts in deren Konfigurationsordner, damit beide CLIs
// angemeldet sind.
const hooks = {
  sandbox: {
    onSandboxReady: [
      // Normalerweise ein No-op in Sekunden. Das erhöhte Timeout sichert den
      // Fall ab, dass requirements-dev.txt seit dem letzten Image-Build neue
      // Pakete bekam, die erst heruntergeladen werden.
      { command: "uv pip install -r requirements-dev.txt", timeoutMs: 180_000 },
      {
        command: [
          `mkdir -p "${sandboxCodexHome}"`,
          `test -f "${sandboxCodexMount}/auth.json"`,
          `cp "${sandboxCodexMount}/auth.json" "${sandboxCodexHome}/auth.json"`,
          `if [ -f "${sandboxCodexMount}/config.toml" ]; then cp "${sandboxCodexMount}/config.toml" "${sandboxCodexHome}/config.toml"; fi`,
        ].join(" && "),
      },
      {
        command: [
          `mkdir -p "${sandboxClaudeHome}"`,
          `test -f "${sandboxClaudeMount}/.credentials.json"`,
          `cp "${sandboxClaudeMount}/.credentials.json" "${sandboxClaudeHome}/.credentials.json"`,
          // Die settings.json des Hosts enthält drei Schlüssel, die nur auf dem
          // Host gelten und im Container stören oder in die Irre führen; sie
          // werden entfernt statt wörtlich kopiert:
          //   sandbox       — schaltet eine verschachtelte bubblewrap/socat-
          //                   Sandbox ein, die im Image fehlt und mit
          //                   failIfUnavailable den Agent abbricht. Neben der
          //                   Docker-Sandbox wäre sie ohnehin überflüssig.
          //   statusLine    — ruft ein Skript im Home des Hosts auf.
          //   enabledPlugins— verweist auf ~/.claude/plugins, das nicht in die
          //                   Sandbox kopiert wird.
          `if [ -f "${sandboxClaudeMount}/settings.json" ]; then jq 'del(.sandbox, .statusLine, .enabledPlugins)' "${sandboxClaudeMount}/settings.json" > "${sandboxClaudeHome}/settings.json"; fi`,
        ].join(" && "),
      },
    ],
  },
};

// Nichts aus dem Host in den Worktree kopieren: virtualenv und Python liegen
// im Image, nicht im Worktree.
const copyToWorktree: string[] = [];

// Die gemeinsamen Einstellungen jedes Agent-Laufs. Mit `branch` arbeitet der
// Agent in einem eigenen Worktree auf diesem Branch, nie im Checkout des
// Hosts; den Branch, den der Host ausgecheckt hat, lässt iteration.mts aus.
function runSettings(branch?: string) {
  return {
    sandbox: agentSandbox(),
    hooks,
    copyToWorktree,
    ...(branch === undefined ? {} : { branchStrategy: { type: "branch" as const, branch } }),
  };
}

// Die Commits und das Abschlusssignal eines Sandcastle-Laufs.
function agentRun(result: {
  commits: readonly { sha: string }[];
  completionSignal?: string;
}): AgentRun {
  return {
    commits: result.commits.map((c) => c.sha),
    completed: result.completionSignal !== undefined,
  };
}

// Eine Markdown-Aufzählung für ein Prompt-Argument.
function bulletList(items: string[]): string {
  return items.map((item) => `- ${item}`).join("\n");
}

/** Die echten Agents eines Line-ups, jeder Lauf in einer eigenen Docker-Sandbox. */
export function sandcastleAgents(lineup: Lineup): Agents {
  return {
    async plan(tickets: Ticket[]): Promise<PlannedIssue[]> {
      // Ohne zweites Ticket gibt es keine Überschneidung abzuwägen; dafür
      // lohnt kein Container.
      if (tickets.length <= 1) {
        return tickets.map((t) => ({
          id: String(t.number),
          title: t.title,
          branch: ticketBranch(t.number),
        }));
      }
      const plan = await sandcastle.run({
        ...runSettings(),
        name: "Planner",
        // Nur lesen und abwägen, kein Code. Strukturierte Ausgabe verlangt
        // genau eine Iteration; das ist also mehr als ein Default.
        maxIterations: 1,
        agent: lineup.planner,
        promptFile: "./.sandcastle/plan-prompt.md",
        promptArgs: { ISSUES: JSON.stringify(tickets, null, 2) },
        output: sandcastle.Output.object({ tag: "plan", schema: planSchema }),
      });
      return plan.output.issues;
    },

    async onTicketBranch<T>(
      issue: PlannedIssue,
      integrationBranch: string,
      work: (session: TicketSession) => Promise<T>,
    ): Promise<T> {
      await using sandbox = await sandcastle.createSandbox({
        sandbox: agentSandbox(),
        branch: issue.branch,
        // Nur für einen neuen Ticket-Branch; ein bestehender behält seinen Stand.
        baseBranch: integrationBranch,
        hooks,
        copyToWorktree,
      });
      const promptArgs = {
        TASK_ID: issue.id,
        ISSUE_TITLE: issue.title,
        BRANCH: issue.branch,
        // TARGET_BRANCH ist ein eingebautes Prompt-Argument (beim run() als
        // aktiver Branch des Hosts gesetzt) und darf nicht übergeben werden,
        // sonst wirft Sandcastle einen PromptError. Der Branch, in den das
        // Ticket gemergt wird, reist deshalb als eigenes Argument.
        INTEGRATION_BRANCH: integrationBranch,
      };
      return await work({
        implement: async () =>
          agentRun(
            await sandbox.run({
              name: "Implementer #" + issue.id,
              maxIterations: MAX_IMPLEMENT_ITERATIONS,
              agent: lineup.implementer,
              promptFile: "./.sandcastle/implement-prompt.md",
              promptArgs,
            }),
          ),
        review: async () =>
          agentRun(
            await sandbox.run({
              name: "Reviewer #" + issue.id,
              // Ein Durchgang über den fertigen Diff, wie im Prompt.
              maxIterations: 1,
              agent: lineup.reviewer,
              promptFile: "./.sandcastle/review-prompt.md",
              promptArgs,
            }),
          ),
      });
    },

    async merge(into: string, branches: string[]): Promise<AgentRun> {
      return agentRun(
        await sandcastle.run({
          ...runSettings(into),
          name: `Merger ${into}`,
          maxIterations: 10,
          agent: lineup.merger,
          promptFile: "./.sandcastle/merge-prompt.md",
          promptArgs: {
            BRANCHES: bulletList(branches),
            INTEGRATION_BRANCH: into,
          },
        }),
      );
    },

    async reviewSpec(spec: number, branch: string): Promise<SpecReview> {
      const review = await sandcastle.run({
        ...runSettings(branch),
        name: `Spec-Review #${spec}`,
        // Strukturierte Ausgabe verlangt genau eine Iteration.
        maxIterations: 1,
        agent: lineup.reviewer,
        promptFile: "./.sandcastle/spec-review-prompt.md",
        promptArgs: { SPEC: spec, INTEGRATION_BRANCH: branch },
        output: sandcastle.Output.object({
          tag: "spec-review",
          schema: specReviewSchema,
          maxRetries: OUTPUT_RETRIES,
        }),
      });
      return review.output;
    },

    async fixFindings(spec: number, branch: string, findings: string[]): Promise<AgentRun> {
      return agentRun(
        await sandcastle.run({
          ...runSettings(branch),
          name: `Spec-Fix #${spec}`,
          maxIterations: MAX_IMPLEMENT_ITERATIONS,
          agent: lineup.implementer,
          promptFile: "./.sandcastle/spec-fix-prompt.md",
          promptArgs: {
            SPEC: spec,
            INTEGRATION_BRANCH: branch,
            FINDINGS: bulletList(findings),
          },
        }),
      );
    },

    async writePullRequest(spec: number, branch: string): Promise<PullRequestText> {
      const text = await sandcastle.run({
        ...runSettings(branch),
        name: `PR-Text #${spec}`,
        maxIterations: 1,
        agent: lineup.reviewer,
        promptFile: "./.sandcastle/pr-prompt.md",
        promptArgs: { SPEC: spec, INTEGRATION_BRANCH: branch },
        output: sandcastle.Output.object({
          tag: "pull-request",
          schema: pullRequestSchema,
          maxRetries: OUTPUT_RETRIES,
        }),
      });
      return text.output;
    },
  };
}
