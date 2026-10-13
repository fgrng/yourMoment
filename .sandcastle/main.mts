// Paralleler Planner: Plan → Implement → Review → Merge
//
// Der Treiber verdrahtet die echten Schnittstellen Tracker (gh), Repo (git)
// und Agents (Sandcastle) mit dem Ablauf in iteration.mts und führt die
// äußere Schleife:
//   Update:    Einmal zu Laufbeginn holt `git fetch origin` den Stand von
//              GitHub. Gemessen wird danach immer gegen origin/main, nie gegen
//              das lokale main. origin/main wird in jeden aktiven
//              Integrations-Branch gemergt (`spec/<n>` einer offenen Spec und
//              `sandcastle/standalone`, falls vorhanden), ohne den Checkout
//              des Hosts zu berühren. Nur ein Konflikt startet einen Merger;
//              scheitert er, bleibt der Branch, wie er war, und der Lauf
//              meldet ihn.
//   Host:      Einen Integrations-Branch, den der Checkout des Hosts gerade
//              ausgecheckt hat, lässt der Lauf aus: kein Update, keine Tickets,
//              keine Abschlussphase. Das Log meldet ihn.
//   Plan:      Der Tracker liefert die unblockierten Tickets (`ready-for-agent`,
//              nicht `Spec`, nicht `is:blocked`). Der Treiber verwirft Tickets,
//              deren Blocker aus einer anderen Spec stammt, die noch offen
//              oder nicht nach origin/main gemergt ist, oder deren Blocker ohne
//              Spec noch nicht auf origin/main liegt, und mit `--spec <n>`
//              jedes Ticket außerhalb von Spec <n>, ebenso Tickets, die die
//              Suche noch führt, obwohl sie schon geschlossen sind. Der Planner
//              bekommt diese Liste, stellt Tickets zurück, die einander wohl in
//              die Quere kommen, und benennt jeden Branch; bei höchstens einem
//              Ticket entfällt er.
//   Implement: Ein Implementer je Ticket, mehrere zugleich. Ein Ticket mit
//              Eltern-Spec <n> zweigt von seinem Integrations-Branch `spec/<n>`
//              ab (fehlt er, entsteht er von origin/main); ein Ticket ohne
//              Spec zweigt von `sandcastle/standalone` ab.
//   Review:    Nur für Branches, deren Implementer das Abschlusssignal gab.
//   Merge:     Ein Merger je Integrations-Branch mergt dessen reviewte
//              Ticket-Branches, immer in einem eigenen Worktree. Ein einzelner
//              Branch, der per Fast-Forward passt, landet ohne Merger; der
//              Treiber setzt den Integrations-Branch nur vor. Endet er ohne
//              Abschlusssignal, steht der Integrations-Branch wieder auf dem
//              Stand davor. Sonst schließt der Treiber jedes Ticket, dessen
//              Branch gelandet ist. Eine Spec bleibt offen; ihr PR schließt sie.
//   Publish:   Am Ende jeder Iteration pusht der Treiber `sandcastle/standalone`,
//              wenn es Commits trägt, die origin/main fehlen, und legt dessen
//              PR an oder ergänzt ihn. Ist der PR gemergt, beginnt der Branch
//              im nächsten Lauf vor dem Update neu von origin/main.
//   Finish:    Am Ende jeder Iteration bekommt jede Spec, deren Sub-Issues alle
//              geschlossen sind und deren `spec/<n>` keinen offenen PR hat,
//              ihre Abschlussphase, höchstens einmal je Lauf: ein
//              `code-review` der ganzen Spec gegen origin/main, ein
//              Fix-Implementer für die Standards- und Korrektheitsbefunde, ein
//              PR-Text mit dem Skill `pr`, dann pusht der Treiber und legt den
//              PR an. Spec-Befunde landen als „Offene Punkte“ im PR-Text, der
//              mit `Closes #<n>` endet.
//
// Die äußere Schleife läuft höchstens MAX_ITERATIONS-mal und endet früher,
// sobald der Backlog leer ist (ein Plan ohne Tickets).
//
// Aufruf:
//   npm run sandcastle                  — Line-up Claude Code (Default)
//   npm run sandcastle -- --agent codex — Line-up Codex
//   npm run sandcastle:codex            — dasselbe, ohne `--`
//   npm run sandcastle -- --spec 321    — nur Spec #321: ihre Sub-Issues, nur spec/321

import { parseArgs } from "node:util";
import { DEFAULT_LINEUP, LINEUPS, sandcastleAgents } from "./agents.mts";
import { type IterationDeps, runIteration, updateIntegrationBranches } from "./iteration.mts";
import { gitRepo } from "./repo.mts";
import { githubTracker } from "./tracker.mts";

// Höchstzahl der Iterationen aus Plan, Ausführung und Merge je Lauf.
const MAX_ITERATIONS = 10;

const { values: cliArgs } = parseArgs({
  options: {
    agent: { type: "string", short: "a", default: DEFAULT_LINEUP },
    spec: { type: "string" },
  },
});

const lineupName = cliArgs.agent ?? DEFAULT_LINEUP;
const lineup = LINEUPS[lineupName];

if (!lineup) {
  console.error(
    `Unknown --agent "${lineupName}". Available: ${Object.keys(LINEUPS).join(", ")}`,
  );
  process.exit(1);
}

const spec = cliArgs.spec === undefined ? undefined : Number(cliArgs.spec);
if (spec !== undefined && !Number.isInteger(spec)) {
  console.error(`--spec expects an issue number, got "${cliArgs.spec}".`);
  process.exit(1);
}

console.log(`Agent line-up: ${lineupName}`);
if (spec !== undefined) console.log(`Limited to the sub-issues of spec #${spec}.`);

const deps: IterationDeps = {
  tracker: githubTracker,
  repo: gitRepo,
  agents: sandcastleAgents(lineup),
  spec,
  finishAttempted: new Set(),
};

console.log(`\n=== Fetching origin, updating integration branches ===\n`);
const { failed } = await updateIntegrationBranches(deps);
if (failed.length > 0) {
  console.log(`origin/main could not be merged into: ${failed.join(", ")}`);
}

for (let iteration = 1; iteration <= MAX_ITERATIONS; iteration++) {
  console.log(`\n=== Iteration ${iteration}/${MAX_ITERATIONS} ===\n`);
  const { planned } = await runIteration(deps);
  if (planned === 0) break;
}

console.log("\nAll done.");
