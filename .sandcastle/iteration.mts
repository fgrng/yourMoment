// Ablauf einer Sandcastle-Iteration. Die Außenwelt kommt über drei schmale
// Schnittstellen herein (Tracker, Repo, Agents), damit sich der Ablauf gegen
// Fakes testen lässt. Die echten Implementierungen liegen in tracker.mts,
// repo.mts und agents.mts, verdrahtet in main.mts.

/** Ein bereites Ticket, wie es der Planner zu sehen bekommt. */
export type Ticket = {
  number: number;
  title: string;
  body: string;
  labels: string[];
  comments: string[];
  /** Die Issues, die dieses Ticket blockieren (Blocked-by-Kanten). */
  blockedBy: number[];
};

/** Ein Issue mit dem Stand seiner Sub-Issues, etwa eine Spec. */
export type IssueSummary = {
  number: number;
  open: boolean;
  labels: string[];
  subIssues: { total: number; completed: number };
};

/** Ein Ticket, das der Planner für diese Iteration freigibt, mit seinem Ticket-Branch. */
export type PlannedIssue = { id: string; title: string; branch: string };

/** Ergebnis eines Agent-Laufs: neue Commits (SHAs) und ob das Abschlusssignal kam. */
export type AgentRun = { commits: string[]; completed: boolean };

/** Titel und Text eines Pull Requests. */
export type PullRequestText = { title: string; body: string };

/** Ein Pull Request; `head` ist der Branch, der gemergt werden soll. */
export type PullRequest = PullRequestText & {
  number: number;
  head: string;
  base: string;
  state: "open" | "merged" | "closed";
};

/** Issues und Pull Requests auf GitHub. */
export interface Tracker {
  /** Offene Tickets mit `ready-for-agent`, ohne `Spec`, ohne offenen Blocker. */
  readyTickets(): Promise<Ticket[]>;
  /** Das Eltern-Issue, oder undefined, wenn es keines gibt. */
  parentOf(issue: number): Promise<IssueSummary | undefined>;
  /** Das Issue mit dem Stand seiner Sub-Issues. */
  issue(issue: number): Promise<IssueSummary>;
  /** Schließt das Issue mit einem Kommentar. */
  close(issue: number, comment: string): Promise<void>;
  /** Kommentiert das Issue, ohne es zu schließen. */
  comment(issue: number, comment: string): Promise<void>;
  /** Ersetzt das Label `remove` durch `add`. */
  swapLabel(issue: number, remove: string, add: string): Promise<void>;
  /** Der offene PR von `head`, sonst der zuletzt angelegte, sonst undefined. */
  pullRequest(head: string): Promise<PullRequest | undefined>;
  /** Legt einen PR von `head` nach `base` an. */
  createPullRequest(pr: PullRequestText & { head: string; base: string }): Promise<void>;
  /** Ersetzt Titel und Text eines bestehenden PRs. */
  updatePullRequest(number: number, text: PullRequestText): Promise<void>;
}

/** Das git-Repo des Hosts; kein Aufruf ändert dessen Checkout. */
export interface Repo {
  /** Holt den Stand von origin, ohne den Checkout des Hosts zu berühren. */
  fetch(): Promise<void>;
  /** Der Branch, den der Checkout des Hosts gerade ausgecheckt hat. */
  hostBranch(): Promise<string>;
  /** Ob `ref` vollständig in `branch` enthalten ist (`merge-base --is-ancestor`). */
  contains(branch: string, ref: string): Promise<boolean>;
  /** Ob eine Commit-Nachricht in `ref` auf das Issue verweist, etwa `(#12)` oder `(#12,`. */
  mentionsIssue(ref: string, issue: number): Promise<boolean>;
  /** Ob es den lokalen Branch gibt. */
  branchExists(branch: string): Promise<boolean>;
  /** Legt `branch` auf dem Stand von `base` an, ohne den Checkout des Hosts zu berühren. */
  createBranch(branch: string, base: string): Promise<void>;
  /** Die lokalen Branches, deren Name mit `prefix` beginnt. */
  branches(prefix: string): Promise<string[]>;
  /**
   * Mergt MAIN_REF in `branch`, ohne den Checkout des Hosts zu berühren. Bei
   * einem Konflikt bleibt `branch` unverändert.
   */
  mergeMain(branch: string): Promise<"clean" | "conflict">;
  /**
   * Setzt `branch` auf `to`, wenn das ein Fast-Forward ist und kein Worktree
   * `branch` ausgecheckt hat; sonst bleibt er, wie er war.
   */
  fastForward(branch: string, to: string): Promise<boolean>;
  /** Der Commit, auf dem `branch` steht; auch für Remote-Refs wie MAIN_REF. */
  head(branch: string): Promise<string>;
  /** Setzt `branch` auf `head` zurück, ohne den Checkout des Hosts zu berühren. */
  resetBranch(branch: string, head: string): Promise<void>;
  /** Ob `branch` genau auf seinem Stand in origin steht. */
  isPushed(branch: string): Promise<boolean>;
  /** Pusht `branch` nach origin; nur sandcastle/standalone darf dabei Historie ersetzen. */
  push(branch: string): Promise<void>;
}

/** Implementer und Review eines Tickets teilen sich eine Sandbox. */
export interface TicketSession {
  /** Der Implementer arbeitet das Ticket auf seinem Ticket-Branch ab. */
  implement(): Promise<AgentRun>;
  /** Das Review je Ticket über den Diff gegen den Integrations-Branch. */
  review(): Promise<AgentRun>;
}

/** Die Agent-Läufe der einzelnen Phasen. */
export interface Agents {
  /** Der Planner stellt Tickets mit überlappenden Dateien zurück. */
  plan(tickets: Ticket[]): Promise<PlannedIssue[]>;
  /**
   * Öffnet eine Sandbox auf dem Ticket-Branch und gibt sie nach `work` wieder
   * frei. Fehlt der Ticket-Branch, zweigt er von `integrationBranch` ab.
   */
  onTicketBranch<T>(
    issue: PlannedIssue,
    integrationBranch: string,
    work: (session: TicketSession) => Promise<T>,
  ): Promise<T>;
  /** Der Merger mergt die Branches in `into`, in einem eigenen Worktree. */
  merge(into: string, branches: string[]): Promise<AgentRun>;
  /** Reviewt `branch` gegen MAIN_REF mit `code-review`, Maßstab ist die Spec. */
  reviewSpec(spec: number, branch: string): Promise<SpecReview>;
  /** Ein Implementer behebt die Befunde auf `branch`. */
  fixFindings(spec: number, branch: string, findings: string[]): Promise<AgentRun>;
  /** Titel und Text des PRs von `branch`, geschrieben mit dem Skill `pr`. */
  writePullRequest(spec: number, branch: string): Promise<PullRequestText>;
}

/**
 * Befunde des Spec-Reviews: Standards und Korrektheit werden behoben,
 * Spec-Befunde gehen als offene Punkte in den PR-Text.
 */
export type SpecReview = { standards: string[]; correctness: string[]; spec: string[] };

/** Ziel jedes PRs. */
export const MAIN_BRANCH = "main";

/**
 * Der Stand von main auf GitHub, wie ihn der Fetch zu Laufbeginn geholt hat.
 * Gegen ihn misst der Lauf, und von ihm zweigen neue Integrations-Branches
 * ab; das lokale main des Hosts bleibt dabei außen vor.
 */
export const MAIN_REF = `origin/${MAIN_BRANCH}`;

/** Der fortlaufende Integrations-Branch der Tickets ohne Eltern-Spec. */
export const STANDALONE_BRANCH = "sandcastle/standalone";

const SPEC_PREFIX = "spec/";

const DEFAULT_MAX_PARALLEL = 4;

type Log = (message: string) => void;

/** Die Schnittstellen und Einstellungen, mit denen eine Iteration läuft. */
export type IterationDeps = {
  tracker: Tracker;
  repo: Repo;
  agents: Agents;
  /** Ziel der Fortschrittsmeldungen, Default `console.log`. */
  log?: Log;
  /** Höchstzahl der Tickets, die gleichzeitig implementiert und reviewt werden (Default 4). */
  maxParallel?: number;
  /** Beschränkt den Lauf auf die Sub-Issues dieser Spec (`--spec <n>`). */
  spec?: number;
  /**
   * Die Specs, deren Abschlussphase dieser Lauf schon versucht hat. Eine
   * gescheiterte Abschlussphase beginnt erst der nächste Lauf von vorn; ein
   * Lauf legt die Menge einmal an und reicht sie jeder Iteration weiter.
   */
  finishAttempted: Set<number>;
};

/** Was der Laufbeginn braucht: die Schnittstellen, das Log und `--spec`. */
export type UpdateDeps = Pick<IterationDeps, "tracker" | "repo" | "agents" | "log" | "spec">;

/** Die Integrations-Branches, in die main zu Laufbeginn nicht gemergt werden konnte. */
export type UpdateResult = { failed: string[] };

/** `planned == 0` heißt: der Backlog ist leer, die äußere Schleife kann enden. */
export type IterationResult = { planned: number };

// Die Abhängigkeiten mit gesetztem Log, wie sie die Helfer bekommen.
type WithLog<T extends { log?: Log }> = T & { log: Log };

function withLog<T extends { log?: Log }>(deps: T): WithLog<T> {
  return { ...deps, log: deps.log ?? console.log };
}

/** Ein geplantes Ticket mit dem Branch, in den es gemergt wird. */
type Assignment = PlannedIssue & { integrationBranch: string };

/**
 * Laufbeginn: holt den Stand von origin und mergt MAIN_REF in jeden aktiven
 * Integrations-Branch, damit Tickets von einem aktuellen Stand abzweigen. Nur
 * bei einem Konflikt startet der Merger. Scheitert er, bleibt der Branch
 * unverändert und steht in `failed`. Ohne Fetch bricht der Lauf ab. Mit
 * `--spec <n>` ist nur `spec/<n>` aktiv; sandcastle/standalone bleibt liegen.
 */
export async function updateIntegrationBranches(options: UpdateDeps): Promise<UpdateResult> {
  const deps = withLog(options);
  const { repo, log } = deps;
  const failed: string[] = [];
  // Nur hier, nicht je Iteration: Was der Lauf gegen MAIN_REF misst, soll zu
  // dem Stand passen, der in den Integrations-Branches steckt.
  await repo.fetch();
  const host = await repo.hostBranch();
  // Vor dem Merge von main, sonst wäre der Branch nicht mehr auf seinem
  // gepushten Stand und bliebe stehen.
  try {
    if (deps.spec === undefined) {
      if (host === STANDALONE_BRANCH) log(`  ! ${checkedOutByHost(host)}`);
      else await restartStandaloneAfterMerge(deps);
    }
  } catch (error) {
    log(`  ! ${STANDALONE_BRANCH}: restart failed: ${error}`);
  }
  for (const branch of await activeIntegrationBranches(deps)) {
    if (branch === host) {
      log(`  ! ${checkedOutByHost(host)}`);
      continue;
    }
    let updated = false;
    try {
      updated = await mergeMainInto(deps, branch);
    } catch (error) {
      log(`  ! ${branch}: ${error}`);
    }
    if (!updated) {
      failed.push(branch);
      log(`  ! ${branch}: could not merge ${MAIN_REF}, branch left unchanged.`);
    }
  }
  return { failed };
}

/**
 * Eine Iteration: planen, je Ticket implementieren und reviewen, je
 * Integrations-Branch mergen und gemergte Tickets schließen. Am Ende werden
 * sandcastle/standalone veröffentlicht (nicht mit `--spec`) und fertige Specs
 * abgeschlossen.
 */
export async function runIteration(options: IterationDeps): Promise<IterationResult> {
  const deps = withLog(options);
  const { planned, landed } = await planImplementAndMerge(deps);
  if (deps.spec === undefined) await publishStandalone(deps, landed);
  await finishCompletedSpecs(deps);
  return { planned };
}

// Den Branch, den der Host ausgecheckt hat, fasst der Lauf nicht an: kein
// Update, keine Tickets, keine Abschlussphase. Ein Worktree dafür ginge
// nicht, und ein Agent im Checkout des Hosts störte dessen Arbeit.
function checkedOutByHost(branch: string): string {
  return `${branch} is checked out in the host checkout - skipped in this run.`;
}

// Mergt MAIN_REF in `branch`, bei Konflikt über den Merger. Liefert, ob
// MAIN_REF danach enthalten ist; sonst steht `branch` wieder auf seinem alten Stand.
async function mergeMainInto(deps: WithLog<UpdateDeps>, branch: string): Promise<boolean> {
  const { repo, log } = deps;
  if ((await repo.mergeMain(branch)) === "clean") return true;

  log(`  ${branch}: conflict with ${MAIN_REF}, starting the merger.`);
  return mergeOrReset(deps, branch, [MAIN_REF], () => repo.contains(branch, MAIN_REF));
}

// Lässt den Merger `branches` in `into` mergen. Liefert, ob er mit
// Abschlusssignal endete und `verified` zutrifft; sonst steht `into` wieder
// auf dem Stand davor, damit kein Ticket eine halbe Auflösung erbt.
async function mergeOrReset(
  deps: WithLog<UpdateDeps>,
  into: string,
  branches: string[],
  verified: () => Promise<boolean> = async () => true,
): Promise<boolean> {
  const { repo, agents, log } = deps;
  const before = await repo.head(into);
  let merged = false;
  try {
    merged = (await agents.merge(into, branches)).completed && (await verified());
  } catch (error) {
    log(`  ! Merger on ${into} failed: ${error}`);
  }
  if (!merged) await repo.resetBranch(into, before);
  return merged;
}

// Aktiv ist jeder bestehende `spec/<n>`, dessen Spec noch offen ist, und
// `sandcastle/standalone`, falls es ihn gibt. Den Branch einer geschlossenen
// Spec hat ihr PR schon nach main gebracht. Mit `--spec <n>` zählt nur `spec/<n>`.
async function activeIntegrationBranches(deps: WithLog<UpdateDeps>): Promise<string[]> {
  const { tracker, repo, log } = deps;
  const active: string[] = [];
  if (deps.spec === undefined && (await repo.branchExists(STANDALONE_BRANCH))) {
    active.push(STANDALONE_BRANCH);
  }
  for (const branch of await repo.branches(SPEC_PREFIX)) {
    const spec = specOfBranch(branch);
    if (spec === undefined) continue;
    if (deps.spec !== undefined && spec !== deps.spec) continue;
    try {
      if ((await tracker.issue(spec)).open) active.push(branch);
    } catch (error) {
      log(`  ! ${branch}: could not read spec #${spec}, skipping: ${error}`);
    }
  }
  return active;
}

// Liefert die Zahl der geplanten Tickets und die Tickets, die in ihrem
// Integrations-Branch gelandet sind.
async function planImplementAndMerge(
  deps: WithLog<IterationDeps>,
): Promise<{ planned: number; landed: Assignment[] }> {
  const { agents, repo, log } = deps;
  const issues = await agents.plan(await frontier(deps));
  if (issues.length === 0) {
    log("No issues to work on.");
    return { planned: 0, landed: [] };
  }

  log(`Planning complete. ${issues.length} issue(s) to work in parallel:`);
  for (const issue of issues) log(`  #${issue.id}: ${issue.title} -> ${issue.branch}`);

  const assignments = await assignIntegrationBranches(deps, issues);
  const readyIssues = await implementAndReview(deps, assignments);

  log(`\nExecution complete. ${readyIssues.length} branch(es) to merge:`);
  for (const issue of readyIssues) log(`  ${issue.branch} -> ${issue.integrationBranch}`);
  if (readyIssues.length === 0) {
    log("No completed branches. Nothing to merge.");
    return { planned: issues.length, landed: [] };
  }

  const landed: Assignment[] = [];
  const byIntegrationBranch = Map.groupBy(readyIssues, (i) => i.integrationBranch);
  for (const [into, group] of byIntegrationBranch) {
    // Ein Merger je Integrations-Branch: Scheitert einer, bleiben die anderen unberührt.
    // Ein einzelner Branch, der per Fast-Forward passt, braucht keinen: Sein
    // Stand ist genau der, den das Review getestet hat.
    const branches = group.map((i) => i.branch);
    if (branches.length === 1 && (await repo.fastForward(into, branches[0]!))) {
      log(`  ${into}: fast-forwarded to ${branches[0]}, no merger.`);
    } else if (!(await mergeOrReset(deps, into, branches))) {
      log(`  ! ${into}: merger did not finish, branch reset - no ticket closed.`);
      continue;
    }
    log(`\nBranches merged into ${into}.`);
    landed.push(...(await closeMergedIssues(deps, group)));
  }
  return { planned: issues.length, landed };
}

// Die Tickets, die der Planner zu sehen bekommt: die bereiten Tickets des
// Trackers, die laut ihrem eigenen Status noch offen sind, mit `--spec` nur
// die Sub-Issues dieser Spec. Offene Blocker hat der Tracker schon
// ausgefiltert; ein geschlossener Blocker aus einem anderen
// Integrations-Branch zählt erst, wenn er auf main liegt. Hat die Spec schon
// einen offenen PR, geht das Ticket an einen Menschen. Ein Ticket, dessen
// Eltern-Issues sich nicht lesen lassen oder dessen Integrations-Branch der
// Host ausgecheckt hat, fällt heraus.
async function frontier(deps: WithLog<IterationDeps>): Promise<Ticket[]> {
  const { tracker, repo, log } = deps;
  const host = await repo.hostBranch();
  const tickets: Ticket[] = [];
  for (const ticket of await tracker.readyTickets()) {
    try {
      // Der Suchindex hinkt nach dem Schließen hinterher; maßgeblich ist der
      // Status des Issues selbst.
      if (!(await tracker.issue(ticket.number)).open) {
        log(`  #${ticket.number}: already closed, search index is stale - skipping.`);
        continue;
      }
      const spec = specOf(await tracker.parentOf(ticket.number));
      if (deps.spec !== undefined && spec !== deps.spec) continue;
      if (integrationBranchOf(spec) === host) {
        log(`  #${ticket.number}: ${checkedOutByHost(host)}`);
        continue;
      }
      if (spec !== undefined && (await hasOpenPullRequest(tracker, spec))) {
        await handOverLateTicket(tracker, ticket.number, spec);
        log(`  #${ticket.number}: spec #${spec} already has an open PR, handed over to a human.`);
        continue;
      }
      const pending = await blockersNotOnMain(deps, ticket, spec);
      if (pending.length > 0) {
        log(`  #${ticket.number}: waiting for ${pending.map((b) => `#${b}`).join(", ")} on ${MAIN_REF}.`);
        continue;
      }
    } catch (error) {
      log(`  ! #${ticket.number}: parent unreadable, skipping: ${error}`);
      continue;
    }
    tickets.push(ticket);
  }
  return tickets;
}

// Ob die Spec schon einen offenen PR hat; dann ist sie im Review beim Menschen.
async function hasOpenPullRequest(tracker: Tracker, spec: number): Promise<boolean> {
  return (await tracker.pullRequest(specBranch(spec)))?.state === "open";
}

// Ein Nachzügler würde still den PR im Review vergrößern. Der Label-Wechsel
// nimmt ihn aus der Frontier, damit der Kommentar nur einmal entsteht.
async function handOverLateTicket(tracker: Tracker, issue: number, spec: number): Promise<void> {
  await tracker.comment(
    issue,
    `Sandcastle plant dieses Ticket nicht ein: Spec #${spec} hat schon einen offenen PR. ` +
      "Nachzügler gehören in eine neue Spec. Das Label steht deshalb jetzt auf `ready-for-human`.",
  );
  await tracker.swapLabel(issue, "ready-for-agent", "ready-for-human");
}

// Die Blocker des Tickets aus einem anderen Integrations-Branch, die noch
// nicht auf main liegen. Ein Blocker derselben Spec zählt schon mit dem Merge
// in deren Branch (dann ist er geschlossen). Ein Blocker aus einer anderen
// Spec zählt erst, wenn diese Spec geschlossen und nach main gemergt ist. Ein
// Blocker ohne Spec zählt, wenn sein Ticket-Branch auf main liegt oder ein
// Commit dort auf ihn verweist (`(#<n>`).
async function blockersNotOnMain(
  deps: IterationDeps,
  ticket: Ticket,
  spec: number | undefined,
): Promise<number[]> {
  const { tracker, repo } = deps;
  const pending: number[] = [];
  for (const blocker of ticket.blockedBy) {
    const parent = await tracker.parentOf(blocker);
    const blockerSpec = specOf(parent);
    if (blockerSpec === spec) continue;
    if (parent && blockerSpec !== undefined) {
      if (!parent.open && (await specOnMain(deps, blockerSpec))) continue;
    } else {
      if (await repo.contains(MAIN_REF, ticketBranch(blocker))) continue;
      if (await repo.mentionsIssue(MAIN_REF, blocker)) continue;
    }
    pending.push(blocker);
  }
  return pending;
}

// Ob eine Spec nach main gemergt ist: über ihren PR oder, bei einem Merge von
// Hand, weil ihr Integrations-Branch in main liegt.
async function specOnMain(deps: IterationDeps, spec: number): Promise<boolean> {
  if ((await deps.tracker.pullRequest(specBranch(spec)))?.state === "merged") return true;
  return deps.repo.contains(MAIN_REF, specBranch(spec));
}

// Leitet jedes Ticket in seinen Integrations-Branch. Fehlt der Branch,
// entsteht er von MAIN_REF. Ein Ticket, dessen Eltern-Issue sich nicht lesen
// lässt, wird ausgelassen statt falsch geleitet.
async function assignIntegrationBranches(
  deps: WithLog<IterationDeps>,
  issues: PlannedIssue[],
): Promise<Assignment[]> {
  const { tracker, repo, log } = deps;
  const assignments: Assignment[] = [];
  for (const issue of issues) {
    let integrationBranch: string;
    try {
      integrationBranch = integrationBranchOf(specOf(await tracker.parentOf(Number(issue.id))));
      if (!(await repo.branchExists(integrationBranch))) {
        await repo.createBranch(integrationBranch, MAIN_REF);
        log(`  ${integrationBranch}: created from ${MAIN_REF}.`);
      }
    } catch (error) {
      log(`  ! #${issue.id}: no integration branch, skipping: ${error}`);
      continue;
    }
    assignments.push({ ...issue, integrationBranch });
  }
  return assignments;
}

// Implementiert und reviewt die Tickets mit einem Pool von maxParallel
// Workern und liefert die Tickets, deren Branch bereit zum Merge ist.
async function implementAndReview(
  deps: WithLog<IterationDeps>,
  issues: Assignment[],
): Promise<Assignment[]> {
  const { agents, repo, log } = deps;
  const queue = [...issues];
  const ready: Assignment[] = [];

  const worker = async (): Promise<void> => {
    for (let issue = queue.shift(); issue; issue = queue.shift()) {
      const current = issue;
      const into = current.integrationBranch;
      try {
        const readyToMerge = await agents.onTicketBranch(current, into, async (session) => {
          const implement = await session.implement();
          const producedCommits = implement.commits.length > 0;
          // Ein Branch kann fertige Arbeit aus einer früheren Iteration tragen,
          // auch wenn der Implementer diesmal nichts committet hat.
          const hasUnmergedWork =
            producedCommits || !(await repo.contains(into, current.branch));

          // Ohne Abschlusssignal ist der Branch halbfertig: Er behält seine
          // Commits für eine spätere Iteration, wird aber weder reviewt noch gemergt.
          if (hasUnmergedWork && !implement.completed) {
            log(
              `  #${current.id}: no completion signal - ${current.branch} keeps its progress, skipping review and merge.`,
            );
          }
          if (!(implement.completed && hasUnmergedWork)) return false;

          if (!producedCommits) {
            log(
              `  #${current.id}: no new commits, but ${current.branch} is ahead of ${into} - reviewing anyway.`,
            );
          }
          await session.review();
          return true;
        });
        if (readyToMerge) ready.push(current);
      } catch (error) {
        // Ein kaputtes Ticket soll die übrigen in der Warteschlange nicht aufhalten.
        log(`  ! #${current.id} (${current.branch}) failed: ${error}`);
      }
    }
  };

  const workers = Math.min(deps.maxParallel ?? DEFAULT_MAX_PARALLEL, queue.length);
  await Promise.all(Array.from({ length: workers }, worker));
  return ready;
}

// Schließt jedes Ticket, dessen Branch nachweislich in seinem
// Integrations-Branch liegt, und liefert diese Tickets. Die Spec bleibt
// offen; sie schließt ihr PR.
async function closeMergedIssues(
  deps: WithLog<IterationDeps>,
  issues: Assignment[],
): Promise<Assignment[]> {
  const { tracker, repo, log } = deps;
  const landed: Assignment[] = [];
  for (const issue of issues) {
    const into = issue.integrationBranch;
    if (!(await repo.contains(into, issue.branch))) {
      log(`  #${issue.id}: ${issue.branch} is not in ${into} - leaving the issue open.`);
      continue;
    }
    landed.push(issue);
    try {
      await tracker.close(Number(issue.id), `Completed by Sandcastle, merged into ${into}`);
      log(`  #${issue.id}: closed.`);
    } catch (error) {
      log(`  ! Could not close #${issue.id}: ${error}`);
    }
  }
  return landed;
}

// Ist der letzte PR von sandcastle/standalone gemergt, beginnt der Branch
// neu von MAIN_REF, damit der nächste PR nur neue Tickets enthält. Commits,
// die noch nicht gepusht sind, gehören nicht zu diesem PR; dann bleibt er stehen.
async function restartStandaloneAfterMerge(deps: WithLog<UpdateDeps>): Promise<void> {
  const { tracker, repo, log } = deps;
  if (!(await repo.branchExists(STANDALONE_BRANCH))) return;
  if ((await tracker.pullRequest(STANDALONE_BRANCH))?.state !== "merged") return;
  if (!(await repo.isPushed(STANDALONE_BRANCH))) {
    log(`  ! ${STANDALONE_BRANCH} has unpushed commits - not restarting from ${MAIN_REF}.`);
    return;
  }
  await repo.resetBranch(STANDALONE_BRANCH, await repo.head(MAIN_REF));
  log(`${STANDALONE_BRANCH}: pull request merged, restarted from ${MAIN_REF}.`);
}

// Hat sandcastle/standalone Commits, die MAIN_REF fehlen, wird der Branch
// gepusht. Sein PR wird angelegt oder, wenn er offen ist, um die gelandeten
// Tickets ergänzt.
async function publishStandalone(
  deps: WithLog<IterationDeps>,
  landed: Assignment[],
): Promise<void> {
  const { tracker, repo, log } = deps;
  if (!(await repo.branchExists(STANDALONE_BRANCH))) return;
  if (await repo.contains(MAIN_REF, STANDALONE_BRANCH)) return;
  try {
    await repo.push(STANDALONE_BRANCH);
    const tickets = landed
      .filter((i) => i.integrationBranch === STANDALONE_BRANCH)
      .map((i) => `- #${i.id}: ${i.title}`);
    const pr = await tracker.pullRequest(STANDALONE_BRANCH);
    if (pr?.state === "open") {
      const listed = pr.body.split("\n").filter((line) => line.startsWith("- #"));
      const body = standalonePrBody([...new Set([...listed, ...tickets])]);
      await tracker.updatePullRequest(pr.number, { title: pr.title, body });
      log(`\n${STANDALONE_BRANCH}: pushed, pull request #${pr.number} updated.`);
    } else {
      await tracker.createPullRequest({
        head: STANDALONE_BRANCH,
        base: MAIN_BRANCH,
        title: "Sandcastle: Tickets ohne Spec",
        body: standalonePrBody(tickets),
      });
      log(`\n${STANDALONE_BRANCH}: pushed, pull request opened.`);
    }
  } catch (error) {
    log(`  ! Publishing ${STANDALONE_BRANCH} failed: ${error}`);
  }
}

// Abschlussphase für jede Spec, deren Sub-Issues alle geschlossen sind und
// die noch keinen offenen PR hat, höchstens einmal je Lauf. Scheitert eine,
// kommen die anderen trotzdem dran.
async function finishCompletedSpecs(deps: WithLog<IterationDeps>): Promise<void> {
  const { log } = deps;
  for (const spec of await completedSpecs(deps)) {
    if (deps.finishAttempted.has(spec)) {
      log(`  spec #${spec}: closing phase already attempted in this run - next run retries.`);
      continue;
    }
    deps.finishAttempted.add(spec);
    try {
      await finishSpec(deps, spec);
    } catch (error) {
      log(`  ! Finishing spec #${spec} failed: ${error}`);
    }
  }
}

// Die Specs, deren Integrations-Branch bereit für den PR ist: Spec offen,
// alle Sub-Issues geschlossen, kein offener PR, Commits, die MAIN_REF noch
// fehlen, und nicht im Checkout des Hosts ausgecheckt.
async function completedSpecs(deps: WithLog<IterationDeps>): Promise<number[]> {
  const { tracker, repo, log } = deps;
  const host = await repo.hostBranch();
  const specs: number[] = [];
  for (const branch of await repo.branches(SPEC_PREFIX)) {
    const spec = specOfBranch(branch);
    if (spec === undefined) continue;
    if (deps.spec !== undefined && spec !== deps.spec) continue;
    if (branch === host) {
      log(`  ! ${checkedOutByHost(host)}`);
      continue;
    }
    try {
      const { open, subIssues } = await tracker.issue(spec);
      if (!open || subIssues.total === 0 || subIssues.completed !== subIssues.total) continue;
      if (await hasOpenPullRequest(tracker, spec)) continue;
      if (await repo.contains(MAIN_REF, branch)) continue;
    } catch (error) {
      log(`  ! ${branch}: could not check spec #${spec}, skipping: ${error}`);
      continue;
    }
    specs.push(spec);
  }
  return specs;
}

// Spec-Review, Behebung der Standards- und Korrektheitsbefunde, PR-Text,
// dann Push und PR. Endet die Behebung ohne Abschlusssignal, bleibt der PR
// aus; der nächste Lauf beginnt die Abschlussphase von vorn.
async function finishSpec(deps: WithLog<IterationDeps>, spec: number): Promise<void> {
  const { tracker, repo, agents, log } = deps;
  const branch = specBranch(spec);
  log(`\n=== Finishing spec #${spec} on ${branch} ===`);

  const review = await agents.reviewSpec(spec, branch);
  const toFix = [...review.standards, ...review.correctness];
  if (toFix.length > 0) {
    const fix = await agents.fixFindings(spec, branch, toFix);
    if (!fix.completed) {
      log(`  ! ${branch}: findings not fixed (no completion signal) - no pull request yet.`);
      return;
    }
  }

  const text = await agents.writePullRequest(spec, branch);
  await repo.push(branch);
  await tracker.createPullRequest({
    head: branch,
    base: MAIN_BRANCH,
    title: text.title,
    body: specPrBody(text.body, review.spec, spec),
  });
  log(`${branch}: pushed, pull request opened.`);
}

// Spec-Befunde entscheidet ein Mensch; sie stehen deshalb wörtlich im PR.
// `Closes` am Ende schließt die Spec beim Merge des PRs.
function specPrBody(body: string, openPoints: string[], spec: number): string {
  const parts = [body.trim()];
  if (openPoints.length > 0) {
    parts.push(["## Offene Punkte", "", ...openPoints.map((p) => `- ${p}`)].join("\n"));
  }
  parts.push(`Closes #${spec}`);
  return parts.join("\n\n");
}

// Der Text des Standalone-PRs: eine Zeile `- #<n>: <Titel>` je Ticket.
function standalonePrBody(ticketLines: string[]): string {
  return [
    "Von Sandcastle umgesetzte Tickets ohne Eltern-Spec, je Ticket reviewt:",
    "",
    ...ticketLines,
  ].join("\n");
}

/** Der Branch eines Tickets; der Planner vergibt ihn deterministisch (siehe plan-prompt.md). */
export function ticketBranch(issue: number): string {
  return `sandcastle/issue-${issue}`;
}

// Der Integrations-Branch einer Spec.
function specBranch(spec: number): string {
  return `${SPEC_PREFIX}${spec}`;
}

// Die Spec-Nummer eines Branches `spec/<n>`, sonst undefined.
function specOfBranch(branch: string): number | undefined {
  if (!branch.startsWith(SPEC_PREFIX)) return undefined;
  const spec = Number(branch.slice(SPEC_PREFIX.length));
  return Number.isInteger(spec) ? spec : undefined;
}

// Ticket mit Eltern-Spec n -> spec/<n>, sonst sandcastle/standalone.
function integrationBranchOf(spec: number | undefined): string {
  return spec === undefined ? STANDALONE_BRANCH : specBranch(spec);
}

// Die Nummer der Eltern-Spec, oder undefined, wenn das Eltern-Issue fehlt
// oder keine Spec ist.
function specOf(parent: IssueSummary | undefined): number | undefined {
  return parent && isSpec(parent) ? parent.number : undefined;
}

// Ob das Issue eine Spec ist (Label `Spec`).
function isSpec(issue: IssueSummary): boolean {
  return issue.labels.includes("Spec");
}
