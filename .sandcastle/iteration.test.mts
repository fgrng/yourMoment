import assert from "node:assert/strict";
import { test } from "node:test";
import { runIteration, updateIntegrationBranches } from "./iteration.mts";
import { FakeAgents, FakeRepo, FakeTracker, ticket } from "./testing/fakes.mts";

function setup(options: { spec?: number } = {}) {
  const tracker = new FakeTracker();
  const repo = new FakeRepo("main");
  const agents = new FakeAgents(repo);
  // Ein Lauf merkt sich wie in main.mts, welche Abschlussphasen er schon versucht hat.
  let finishAttempted = new Set<number>();
  const startNewRun = () => {
    finishAttempted = new Set();
  };
  // `overrides` ändert die Optionen für einen einzelnen Lauf, etwa `--spec`.
  const run = (overrides: { spec?: number } = {}) =>
    runIteration({ tracker, repo, agents, log: () => {}, finishAttempted, ...options, ...overrides });
  // Laufbeginn wie in main.mts: Fetch und Update der Integrations-Branches.
  const update = (overrides: { spec?: number } = {}) =>
    updateIntegrationBranches({ tracker, repo, agents, log: () => {}, ...options, ...overrides });
  return { tracker, repo, agents, run, update, startNewRun };
}

test("der Planner bekommt die Tickets aus dem Tracker-Filter", async () => {
  const { tracker, agents, run } = setup();
  tracker.addTicket(ticket(7, "Erstes"));
  tracker.addTicket(ticket(9, "Zweites"));

  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[7, 9]],
  );
});

test("ein gerade geschlossenes Ticket, das die Suche noch als offen führt, wird nicht erneut eingeplant", async () => {
  const { tracker, agents, run } = setup();
  tracker.addTicket(ticket(7));
  await run();
  tracker.staleSearch = true;

  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[7], []],
  );
});

test("ein fertiges Ticket wird reviewt, gemergt und geschlossen", async () => {
  const { tracker, repo, agents, run } = setup();
  tracker.addTicket(ticket(7));

  await run();

  assert.deepEqual(
    {
      reviewed: agents.reviewed,
      landed: await repo.contains("sandcastle/standalone", "sandcastle/issue-7"),
      open: tracker.isOpen(7),
    },
    { reviewed: ["7"], landed: true, open: false },
  );
});

test("ein einzelner Branch, der per Fast-Forward passt, landet ohne Merger", async () => {
  const { tracker, repo, agents, run } = setup();
  tracker.addTicket(ticket(7));

  await run();

  assert.deepEqual(
    {
      merged: agents.mergedWith,
      landed: await repo.contains("sandcastle/standalone", "sandcastle/issue-7"),
      open: tracker.isOpen(7),
    },
    { merged: [], landed: true, open: false },
  );
});

test("ist der Integrations-Branch weitergelaufen, mergt der Merger auch einen einzelnen Branch", async () => {
  const { tracker, agents, repo, run } = setup();
  tracker.addTicket(ticket(7));
  await repo.createBranch("sandcastle/standalone", "origin/main");
  await repo.createBranch("sandcastle/issue-7", "sandcastle/standalone");
  repo.commit("sandcastle/standalone");

  await run();

  assert.deepEqual(agents.mergedWith, [
    { into: "sandcastle/standalone", branches: ["sandcastle/issue-7"] },
  ]);
});

test("hat ein Worktree den Integrations-Branch ausgecheckt, mergt der Merger statt eines Fast-Forwards", async () => {
  const { tracker, agents, repo, run } = setup();
  tracker.addTicket(ticket(7));
  repo.checkedOutElsewhere.add("sandcastle/standalone");

  await run();

  assert.deepEqual(agents.mergedWith, [
    { into: "sandcastle/standalone", branches: ["sandcastle/issue-7"] },
  ]);
});

test("ohne Abschlusssignal gibt es kein Review und keinen Merge, das Ticket bleibt offen", async () => {
  const { tracker, agents, run } = setup();
  tracker.addTicket(ticket(7));
  agents.implementers.set("7", { commits: 2, completed: false });

  await run();

  assert.deepEqual(
    { reviewed: agents.reviewed, merged: agents.mergedWith, open: tracker.isOpen(7) },
    { reviewed: [], merged: [], open: true },
  );
});

test("geschlossen werden nur Tickets, deren Branch nachweislich gemergt ist", async () => {
  const { tracker, agents, run } = setup();
  tracker.addTicket(ticket(7));
  tracker.addTicket(ticket(8));
  agents.skipped.add("sandcastle/issue-8");

  await run();

  assert.deepEqual(
    tracker.closed.map((c) => c.number),
    [7],
  );
});

test("ohne Abschlusssignal des Mergers wird kein Ticket seines Integrations-Branches geschlossen", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(32), { parent: 30 });
  tracker.addTicket(ticket(7));
  agents.unmergeable.add("sandcastle/issue-32");

  await run();

  assert.deepEqual(
    tracker.closed.map((c) => c.number),
    [7],
  );
});

test("ohne Abschlusssignal des Mergers steht der Integrations-Branch wieder auf seinem Stand davor", async () => {
  const { tracker, repo, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(32), { parent: 30 });
  await repo.createBranch("spec/30", "origin/main");
  repo.commit("spec/30");
  const before = await repo.head("spec/30");
  agents.unmergeable.add("sandcastle/issue-32");

  await run();

  assert.equal(await repo.head("spec/30"), before);
});

test("ein fertiger Branch aus einer früheren Iteration wird ohne neue Commits gemergt", async () => {
  const { tracker, repo, agents, run } = setup();
  tracker.addTicket(ticket(7));
  await repo.createBranch("sandcastle/standalone", "origin/main");
  await repo.createBranch("sandcastle/issue-7", "sandcastle/standalone");
  repo.commit("sandcastle/issue-7");
  agents.implementers.set("7", { commits: 0, completed: true });

  await run();

  assert.equal(await repo.contains("sandcastle/standalone", "sandcastle/issue-7"), true);
});

test("ein Branch ohne Arbeit wird weder reviewt noch gemergt", async () => {
  const { tracker, agents, run } = setup();
  tracker.addTicket(ticket(7));
  agents.implementers.set("7", { commits: 0, completed: true });

  await run();

  assert.deepEqual({ reviewed: agents.reviewed, merged: agents.mergedWith }, { reviewed: [], merged: [] });
});

test("Tickets einer Spec werden nach dem Merge in spec/<n> geschlossen, die Spec bleibt offen", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(32), { parent: 30 });
  agents.deferred.add("32");

  await run();
  agents.deferred.clear();
  await run();

  assert.deepEqual(
    { closed: tracker.closed.map((c) => c.number), specOpen: tracker.isOpen(30) },
    { closed: [31, 32], specOpen: true },
  );
});

test("ohne Tickets meldet die Iteration einen leeren Backlog", async () => {
  const { run } = setup();

  assert.deepEqual(await run(), { planned: 0 });
});

test("ein Fehler bei einem Ticket hält die übrigen nicht auf", async () => {
  const { tracker, agents, run } = setup();
  tracker.addTicket(ticket(7));
  tracker.addTicket(ticket(8));
  agents.failing.add("7");

  await run();

  assert.deepEqual(tracker.closed.map((c) => c.number), [8]);
});

test("ein Ticket einer Spec zweigt von spec/<n> ab, das von main entsteht, und wird dorthin gemergt", async () => {
  const { tracker, repo, agents, run, update } = setup();
  repo.commitOnOrigin("main");
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });

  await update();
  await run();

  assert.deepEqual(
    {
      startedFrom: agents.startedFrom,
      specHasMain: await repo.contains("spec/30", "origin/main"),
      specHasTicket: await repo.contains("spec/30", "sandcastle/issue-31"),
      mainHasTicket: await repo.contains("origin/main", "sandcastle/issue-31"),
    },
    {
      startedFrom: [{ id: "31", base: "spec/30" }],
      specHasMain: true,
      specHasTicket: true,
      mainHasTicket: false,
    },
  );
});

test("je Integrations-Branch mit mehreren Branches läuft ein eigener Merger", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addSpec(40);
  tracker.addTicket(ticket(7));
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(41), { parent: 40 });
  tracker.addTicket(ticket(32), { parent: 30 });

  await run();

  assert.deepEqual(
    new Map(agents.mergedWith.map((m) => [m.into, m.branches.toSorted()])),
    new Map([
      ["spec/30", ["sandcastle/issue-31", "sandcastle/issue-32"]],
    ]),
  );
});

test("zu Laufbeginn bekommt ein Spec-Branch main sauber hineingemergt, ohne Agent", async () => {
  const { tracker, repo, agents, update } = setup();
  tracker.addSpec(30);
  await repo.createBranch("spec/30", "origin/main");
  repo.commitOnOrigin("main");

  await update();

  assert.deepEqual(
    { specHasMain: await repo.contains("spec/30", "origin/main"), merged: agents.mergedWith },
    { specHasMain: true, merged: [] },
  );
});

test("zu Laufbeginn holt der Lauf main von origin und mergt diesen Stand in den Spec-Branch", async () => {
  const { tracker, repo, update } = setup();
  tracker.addSpec(30);
  await repo.createBranch("spec/30", "origin/main");
  const merged = repo.commitOnOrigin("main");

  await update();

  assert.equal(repo.hasCommit("spec/30", merged), true);
});

test("bei einem Konflikt mit main löst der Merger auf genau diesem Branch auf", async () => {
  const { tracker, repo, agents, update } = setup();
  tracker.addSpec(30);
  await repo.createBranch("spec/30", "origin/main");
  repo.commitOnOrigin("main");
  repo.conflicting.add("spec/30");

  await update();

  assert.deepEqual(
    { specHasMain: await repo.contains("spec/30", "origin/main"), merged: agents.mergedWith },
    { specHasMain: true, merged: [{ into: "spec/30", branches: ["origin/main"] }] },
  );
});

test("scheitert die Auflösung, bleibt der Branch unverändert und der Lauf meldet ihn", async () => {
  const { tracker, repo, agents, update } = setup();
  tracker.addSpec(30);
  await repo.createBranch("spec/30", "origin/main");
  repo.commit("spec/30");
  repo.commitOnOrigin("main");
  repo.conflicting.add("spec/30");
  agents.unmergeable.add("origin/main");
  const before = await repo.head("spec/30");

  const result = await update();

  assert.deepEqual(
    { head: await repo.head("spec/30"), failed: result.failed },
    { head: before, failed: ["spec/30"] },
  );
});

test("der Branch einer geschlossenen Spec bekommt main nicht mehr hineingemergt", async () => {
  const { tracker, repo, update } = setup();
  tracker.addSpec(30, { open: false });
  await repo.createBranch("spec/30", "origin/main");
  repo.commitOnOrigin("main");

  await update();

  assert.equal(await repo.contains("spec/30", "origin/main"), false);
});

test("ein bestehender sandcastle/standalone bekommt main hineingemergt", async () => {
  const { repo, update } = setup();
  await repo.createBranch("sandcastle/standalone", "origin/main");
  repo.commitOnOrigin("main");

  await update();

  assert.equal(await repo.contains("sandcastle/standalone", "origin/main"), true);
});

test("mit --spec bekommt zu Laufbeginn nur dieser Spec-Branch main hineingemergt", async () => {
  const { tracker, repo, update } = setup({ spec: 30 });
  tracker.addSpec(30);
  tracker.addSpec(40);
  await repo.createBranch("spec/30", "origin/main");
  await repo.createBranch("spec/40", "origin/main");
  await repo.createBranch("sandcastle/standalone", "origin/main");
  repo.commitOnOrigin("main");

  await update();

  assert.deepEqual(
    {
      spec30: await repo.contains("spec/30", "origin/main"),
      spec40: await repo.contains("spec/40", "origin/main"),
      standalone: await repo.contains("sandcastle/standalone", "origin/main"),
    },
    { spec30: true, spec40: false, standalone: false },
  );
});

test("mit --spec beginnt sandcastle/standalone nach dem Merge seines PRs nicht neu", async () => {
  const { tracker, repo, run, update } = setup();
  tracker.addTicket(ticket(7));
  await run();
  tracker.mergePullRequest(tracker.pullRequests[0]!.number);

  await update({ spec: 30 });

  assert.equal(await repo.contains("sandcastle/standalone", "sandcastle/issue-7"), true);
});

test("mit --spec wird sandcastle/standalone weder gepusht noch bekommt es einen PR", async () => {
  const { tracker, repo, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(7));
  repo.pushFails = true;
  await run();
  repo.pushFails = false;

  await run({ spec: 30 });

  assert.deepEqual(
    { pushed: await repo.isPushed("sandcastle/standalone"), prs: tracker.pullRequests },
    { pushed: false, prs: [] },
  );
});

test("steht der Host auf spec/<n>, plant der Lauf die Tickets dieser Spec nicht ein", async () => {
  const { tracker, repo, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(7));
  repo.checkedOut = "spec/30";

  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[7]],
  );
});

test("steht der Host auf spec/<n>, bekommt der Branch zu Laufbeginn main nicht hineingemergt", async () => {
  const { tracker, repo, update } = setup();
  tracker.addSpec(30);
  await repo.createBranch("spec/30", "origin/main");
  const merged = repo.commitOnOrigin("main");
  repo.checkedOut = "spec/30";

  await update();

  assert.equal(repo.hasCommit("spec/30", merged), false);
});

test("steht der Host auf spec/<n>, startet für die fertige Spec keine Abschlussphase", async () => {
  const { tracker, repo, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  await tracker.close(31, "von Hand umgesetzt");
  await repo.createBranch("spec/30", "origin/main");
  repo.commit("spec/30");
  repo.checkedOut = "spec/30";

  await run();

  assert.deepEqual(agents.specSteps, []);
});

test("steht der Host auf sandcastle/standalone, beginnt der Branch nach dem Merge seines PRs nicht neu", async () => {
  const { tracker, repo, run, update } = setup();
  tracker.addTicket(ticket(7));
  await run();
  tracker.mergePullRequest(tracker.pullRequests[0]!.number);
  repo.checkedOut = "sandcastle/standalone";

  await update();

  assert.equal(await repo.contains("sandcastle/standalone", "sandcastle/issue-7"), true);
});

test("mit --spec <n> plant der Lauf nur die Sub-Issues von #n", async () => {
  const { tracker, agents, run } = setup({ spec: 30 });
  tracker.addSpec(30);
  tracker.addSpec(40);
  tracker.addTicket(ticket(7));
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(41), { parent: 40 });

  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[31]],
  );
});

test("ein geschlossener Blocker aus derselben Spec gibt sein Ticket frei", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(32), { parent: 30, blockedBy: [31] });

  await run();
  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[31], [32]],
  );
});

test("ein geschlossener Blocker aus einer anderen Spec hält sein Ticket zurück, solange seine Spec offen ist", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addSpec(40);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(41), { parent: 40, blockedBy: [31] });

  await run();
  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[31], []],
  );
});

test("ein Blocker aus einer anderen Spec zählt nicht, solange seine Spec offen ist, auch wenn ihr Branch auf main liegt", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addSpec(30);
  tracker.addSpec(40);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(41), { parent: 40, blockedBy: [31] });

  await run();
  repo.mergeOnOrigin("spec/30", "main");
  await update();
  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[31], []],
  );
});

test("ein Blocker aus einer geschlossenen Spec, deren Branch auf main liegt, gibt sein Ticket frei", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addSpec(30);
  tracker.addSpec(40);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(41), { parent: 40, blockedBy: [31] });

  await run();
  repo.mergeOnOrigin("spec/30", "main");
  await tracker.close(30, "PR gemergt");
  await update();
  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[31], [41]],
  );
});

test("ein Blocker aus einer geschlossenen Spec, deren PR gemergt ist, gibt sein Ticket frei", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(20, { open: false });
  tracker.addSpec(40);
  tracker.addTicket(ticket(21), { parent: 20 });
  await tracker.close(21, "von Hand umgesetzt");
  tracker.addTicket(ticket(41), { parent: 40, blockedBy: [21] });
  await tracker.createPullRequest({ head: "spec/20", base: "main", title: "Spec 20", body: "Closes #20" });
  tracker.mergePullRequest(tracker.pullRequests[0].number);

  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[41]],
  );
});

test("ein Blocker aus einer geschlossenen Spec, die nie nach main gemergt wurde, hält sein Ticket zurück", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(20, { open: false });
  tracker.addSpec(40);
  tracker.addTicket(ticket(21), { parent: 20 });
  await tracker.close(21, "von Hand umgesetzt");
  tracker.addTicket(ticket(41), { parent: 40, blockedBy: [21] });

  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[]],
  );
});

test("ein Blocker aus einer offenen Spec zählt nicht, auch wenn ein Commit auf main auf ihn verweist", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addSpec(20);
  tracker.addSpec(40);
  tracker.addTicket(ticket(21), { parent: 20 });
  await tracker.close(21, "von Hand umgesetzt");
  tracker.addTicket(ticket(41), { parent: 40, blockedBy: [21] });
  repo.commitOnOrigin("main", "Export ergänzen (#21, Spec #20)");

  await update();
  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[]],
  );
});

test("ein Blocker ohne Spec gibt ein Spec-Ticket frei, wenn ein Commit auf main auf ihn verweist", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addSpec(40);
  tracker.addTicket(ticket(7));
  await tracker.close(7, "von Hand umgesetzt");
  tracker.addTicket(ticket(41), { parent: 40, blockedBy: [7] });
  repo.commitOnOrigin("main", "Tippfehler beheben (#7)");

  await update();
  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[41]],
  );
});

test("ein Verweis auf ein anderes Issue mit gleichem Anfang gibt den Blocker ohne Spec nicht frei", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addSpec(40);
  tracker.addTicket(ticket(7));
  await tracker.close(7, "von Hand umgesetzt");
  tracker.addTicket(ticket(41), { parent: 40, blockedBy: [7] });
  repo.commitOnOrigin("main", "Tippfehler beheben (#70)");

  await update();
  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[]],
  );
});

test("ein Ticket ohne Spec zweigt von sandcastle/standalone ab, das von main entsteht, und wird dorthin gemergt", async () => {
  const { tracker, repo, agents, run, update } = setup();
  repo.commitOnOrigin("main");
  tracker.addTicket(ticket(7));

  await update();
  await run();

  assert.deepEqual(
    {
      startedFrom: agents.startedFrom,
      standaloneHasMain: await repo.contains("sandcastle/standalone", "origin/main"),
      standaloneHasTicket: await repo.contains("sandcastle/standalone", "sandcastle/issue-7"),
      mainHasTicket: await repo.contains("origin/main", "sandcastle/issue-7"),
    },
    {
      startedFrom: [{ id: "7", base: "sandcastle/standalone" }],
      standaloneHasMain: true,
      standaloneHasTicket: true,
      mainHasTicket: false,
    },
  );
});

test("neue Commits auf sandcastle/standalone werden gepusht und bekommen einen PR nach main", async () => {
  const { tracker, repo, run } = setup();
  tracker.addTicket(ticket(7, "Tippfehler beheben"));

  await run();

  assert.deepEqual(
    {
      pushed: await repo.isPushed("sandcastle/standalone"),
      prs: tracker.pullRequests.map(({ head, base, state }) => ({ head, base, state })),
      mentionsTicket: tracker.pullRequests[0]?.body.includes("#7: Tippfehler beheben"),
    },
    {
      pushed: true,
      prs: [{ head: "sandcastle/standalone", base: "main", state: "open" }],
      mentionsTicket: true,
    },
  );
});

test("ein offener Standalone-PR wird aktualisiert statt neu angelegt", async () => {
  const { tracker, repo, run } = setup();
  tracker.addTicket(ticket(7, "Erstes"));
  await run();
  tracker.addTicket(ticket(8, "Zweites"));

  await run();

  assert.deepEqual(
    {
      pushed: await repo.isPushed("sandcastle/standalone"),
      prs: tracker.pullRequests.map((pr) => pr.body.split("\n").filter((l) => l.startsWith("- "))),
    },
    { pushed: true, prs: [["- #7: Erstes", "- #8: Zweites"]] },
  );
});

test("ohne neue Commits auf sandcastle/standalone gibt es weder Push noch PR", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(7));
  agents.implementers.set("7", { commits: 1, completed: false });

  await run();

  assert.deepEqual(
    {
      pushed: await repo.isPushed("sandcastle/standalone"),
      prs: tracker.pullRequests.filter((pr) => pr.head === "sandcastle/standalone"),
    },
    { pushed: false, prs: [] },
  );
});

test("nach dem Merge des Standalone-PRs zweigt sandcastle/standalone im nächsten Lauf frisch von main ab", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addTicket(ticket(7, "Erstes"));
  await run();
  tracker.mergePullRequest(tracker.pullRequests[0]!.number);
  tracker.addTicket(ticket(8, "Zweites"));

  await update();
  await run();

  assert.deepEqual(
    {
      hasOldTicket: await repo.contains("sandcastle/standalone", "sandcastle/issue-7"),
      hasNewTicket: await repo.contains("sandcastle/standalone", "sandcastle/issue-8"),
      prs: tracker.pullRequests.map((pr) => ({
        state: pr.state,
        tickets: pr.body.split("\n").filter((l) => l.startsWith("- ")),
      })),
    },
    {
      hasOldTicket: false,
      hasNewTicket: true,
      prs: [
        { state: "merged", tickets: ["- #7: Erstes"] },
        { state: "open", tickets: ["- #8: Zweites"] },
      ],
    },
  );
});

test("scheitert der Push nach einem Neustart, gehen die neuen Commits nicht verloren", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addTicket(ticket(7));
  await run();
  tracker.mergePullRequest(tracker.pullRequests[0]!.number);
  tracker.addTicket(ticket(8));
  repo.pushFails = true;
  await update();
  await run();
  repo.pushFails = false;

  await update();
  await run();

  assert.deepEqual(
    {
      hasTicket: await repo.contains("sandcastle/standalone", "sandcastle/issue-8"),
      pushed: await repo.isPushed("sandcastle/standalone"),
      prStates: tracker.pullRequests.map((pr) => pr.state),
    },
    { hasTicket: true, pushed: true, prStates: ["merged", "open"] },
  );
});

test("nach dem Merge des Standalone-PRs entsteht ohne neue Tickets kein weiterer PR, auch wenn main weiter ist", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addTicket(ticket(7));
  await update();
  await run();
  tracker.mergePullRequest(tracker.pullRequests[0]!.number);
  repo.mergeOnOrigin("sandcastle/standalone", "main");
  repo.commitOnOrigin("main");

  await update();
  await run();

  assert.deepEqual(
    tracker.pullRequests.map((pr) => pr.state),
    ["merged"],
  );
});

test("ist das letzte Ticket einer Spec geschlossen, wird spec/<n> gepusht und bekommt einen PR nach main", async () => {
  const { tracker, repo, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });

  await run();

  assert.deepEqual(
    {
      pushed: await repo.isPushed("spec/30"),
      prs: tracker.pullRequests.map(({ head, base, state }) => ({ head, base, state })),
      closesSpec: tracker.pullRequests[0]?.body.trimEnd().endsWith("Closes #30"),
    },
    {
      pushed: true,
      prs: [{ head: "spec/30", base: "main", state: "open" }],
      closesSpec: true,
    },
  );
});

test("solange ein Sub-Issue der Spec offen ist, startet keine Abschlussphase", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(32), { parent: 30 });
  agents.deferred.add("32");

  await run();

  assert.deepEqual(
    { steps: agents.specSteps, prs: tracker.pullRequests },
    { steps: [], prs: [] },
  );
});

test("hat die Spec schon einen offenen PR, startet keine Abschlussphase", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(32), { parent: 30 });
  agents.deferred.add("32");
  await run();
  await tracker.createPullRequest({ head: "spec/30", base: "main", title: "Spec #30", body: "" });
  await tracker.close(32, "von Hand umgesetzt");

  await run();

  assert.deepEqual(
    { steps: agents.specSteps, prs: tracker.pullRequests.length, specBranchAhead: !(await repo.contains("origin/main", "spec/30")) },
    { steps: [], prs: 1, specBranchAhead: true },
  );
});

test("werden zwei Specs im selben Lauf fertig, bekommt jede ihre eigene Abschlussphase", async () => {
  const { tracker, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addSpec(40);
  tracker.addTicket(ticket(41), { parent: 40 });

  await run();

  assert.deepEqual(
    tracker.pullRequests.map((pr) => ({ head: pr.head, last: pr.body.split("\n").at(-1) })),
    [
      { head: "spec/30", last: "Closes #30" },
      { head: "spec/40", last: "Closes #40" },
    ],
  );
});

test("die Abschlussphase reviewt, behebt Standards- und Korrektheitsbefunde, schreibt den PR-Text und legt den PR an", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  agents.specReviews.set(30, {
    standards: ["Docstring fehlt"],
    correctness: ["Grenzfall falsch"],
    spec: ["Export fehlt"],
  });

  await run();

  assert.deepEqual(
    {
      steps: agents.specSteps,
      fixedWith: agents.fixedWith,
      prs: tracker.pullRequests.length,
      pushedWithFix: await repo.isPushed("spec/30"),
    },
    {
      steps: ["review #30", "fix #30", "pr-text #30"],
      fixedWith: [{ spec: 30, findings: ["Docstring fehlt", "Grenzfall falsch"] }],
      prs: 1,
      pushedWithFix: true,
    },
  );
});

test("Spec-Befunde stehen als offene Punkte im PR-Text vor Closes #<spec>", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  agents.specReviews.set(30, { standards: [], correctness: [], spec: ["Export fehlt"] });

  await run();

  assert.equal(
    tracker.pullRequests[0]?.body,
    "## Summary\n\nAlles zu #30.\n\n## Offene Punkte\n\n- Export fehlt\n\nCloses #30",
  );
});

test("ohne Standards- und Korrektheitsbefunde läuft kein Fix-Implementer", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  agents.specReviews.set(30, { standards: [], correctness: [], spec: ["Export fehlt"] });

  await run();

  assert.deepEqual(agents.specSteps, ["review #30", "pr-text #30"]);
});

test("endet die Behebung ohne Abschlusssignal, gibt es weder Push noch PR", async () => {
  const { tracker, repo, agents, run, update } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  agents.specReviews.set(30, { standards: ["Docstring fehlt"], correctness: [], spec: [] });
  agents.unfixable.add(30);

  await run();

  assert.deepEqual(
    { pushed: await repo.isPushed("spec/30"), prs: tracker.pullRequests },
    { pushed: false, prs: [] },
  );
});

test("scheitert die Abschlussphase, versucht der Lauf sie in späteren Iterationen nicht erneut", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  agents.specReviews.set(30, { standards: ["Docstring fehlt"], correctness: [], spec: [] });
  agents.unfixable.add(30);

  await run();
  await run();

  assert.deepEqual(agents.specSteps, ["review #30", "fix #30"]);
});

test("nach einer gescheiterten Abschlussphase beginnt der nächste Lauf sie von vorn", async () => {
  const { tracker, agents, run, startNewRun } = setup();
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  agents.specReviews.set(30, { standards: ["Docstring fehlt"], correctness: [], spec: [] });
  agents.unfixable.add(30);
  await run();
  agents.unfixable.clear();

  startNewRun();
  await run();

  assert.deepEqual(tracker.pullRequests.map((pr) => pr.head), ["spec/30"]);
});

test("mit --spec <n> wird nur Spec #n abgeschlossen", async () => {
  const { tracker, repo, run } = setup({ spec: 40 });
  tracker.addSpec(30);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addSpec(40);
  tracker.addTicket(ticket(41), { parent: 40 });
  await repo.createBranch("spec/30", "origin/main");
  repo.commit("spec/30");
  await tracker.close(31, "von Hand umgesetzt");

  await run();

  assert.deepEqual(
    tracker.pullRequests.map((pr) => pr.head),
    ["spec/40"],
  );
});

// Spec #30 hat einen offenen PR, Ticket 31 kommt als Nachzügler, Ticket 7 ist unabhängig.
async function setupLateTicket() {
  const context = setup();
  context.tracker.addSpec(30);
  context.tracker.addTicket(ticket(31), { parent: 30 });
  context.tracker.addTicket(ticket(7));
  await context.tracker.createPullRequest({ head: "spec/30", base: "main", title: "Spec #30", body: "" });
  return context;
}

test("hat die Spec eines Tickets einen offenen PR, fehlt das Ticket in der Frontier", async () => {
  const { agents, run } = await setupLateTicket();

  await run();

  assert.deepEqual(
    agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
    [[7]],
  );
});

test("ein Nachzügler einer Spec mit offenem PR wird über zwei Iterationen nur einmal kommentiert, mit Verweis auf eine neue Spec", async () => {
  const { tracker, run } = await setupLateTicket();

  await run();
  await run();

  assert.deepEqual(
    tracker.comments.map((c) => ({ number: c.number, pointsToNewSpec: /neue Spec/.test(c.comment) })),
    [{ number: 31, pointsToNewSpec: true }],
  );
});

test("ein Nachzügler einer Spec mit offenem PR bleibt offen und steht auf ready-for-human", async () => {
  const { tracker, run } = await setupLateTicket();

  await run();

  assert.deepEqual(
    { labels: (await tracker.issue(31)).labels, open: tracker.isOpen(31) },
    { labels: ["ready-for-human"], open: true },
  );
});

test("ein gemergter oder fehlender Spec-PR sperrt kein Ticket", async () => {
  const { tracker, agents, run } = setup();
  tracker.addSpec(30);
  tracker.addSpec(40);
  tracker.addTicket(ticket(31), { parent: 30 });
  tracker.addTicket(ticket(41), { parent: 40 });
  await tracker.createPullRequest({ head: "spec/30", base: "main", title: "Spec #30", body: "" });
  tracker.mergePullRequest(tracker.pullRequests[0].number);

  await run();

  assert.deepEqual(
    {
      planned: agents.plannedWith.map((tickets) => tickets.map((t) => t.number)),
      comments: tracker.comments,
    },
    { planned: [[31, 41]], comments: [] },
  );
});
