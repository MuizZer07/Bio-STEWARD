// The ten panels by job (design v0.9 §3; RELEASE_vscode_0.3.0_SPEC E01), in one activity-bar container: each
// panel's view, group, name, refresh command and the one sentence on how it helps when developing with agents.
// Pure: no `vscode` import (the approvals page and the unit tests read it).

export type PanelGroup = 'Now' | 'Quality' | 'Work' | 'Direction' | 'Agents';

export interface Panel {
  readonly view: string;
  readonly group: PanelGroup;
  readonly name: string;
  readonly refresh: string;
  // One sentence on how the panel helps when developing with agents: the first words of its empty states and of
  // its `?` help (media/help/panels.md).
  readonly helps: string;
}

// In the order of the activity-bar container (package.json contributes.views keeps the same order).
export const PANELS = Object.freeze({
  today: {
    view: 'bioSteward.today', group: 'Now', name: 'Today', refresh: 'bioSteward.today.refresh',
    helps: 'Today shows what waits for you and what your agents are on, so each session starts where the work is.',
  },
  approvals: {
    view: 'bioSteward.approvals', group: 'Now', name: 'Approvals', refresh: 'bioSteward.approvals.refresh',
    helps: 'Approvals lists what your agents prepared that only you can sign, with the exact text you approve.',
  },
  overview: {
    view: 'bioSteward.overview', group: 'Quality', name: 'Overview', refresh: 'bioSteward.overview.refresh',
    helps: 'Overview shows whether your agents\' work passes this project\'s checks and may move on.',
  },
  results: {
    view: 'bioSteward.results', group: 'Quality', name: 'Results', refresh: 'bioSteward.results.refresh',
    helps: 'Results lists every check result, so you can hand one problem at a time to an agent.',
  },
  tasks: {
    view: 'bioSteward.tasks', group: 'Work', name: 'Tasks', refresh: 'bioSteward.tasks.refresh',
    helps: 'Tasks lists every task your agents work on, the latest change first.',
  },
  sprint: {
    view: 'bioSteward.sprint', group: 'Work', name: 'Sprint', refresh: 'bioSteward.sprint.refresh',
    helps: 'Sprint shows what each agent of a running sprint is doing and which of its checks passed.',
  },
  tokens: {
    view: 'bioSteward.tokens', group: 'Work', name: 'Tokens', refresh: 'bioSteward.tokens.refresh',
    helps: 'Tokens shows what each agent task cost, counted from the agents\' own logs on this machine.',
  },
  drift: {
    view: 'bioSteward.drift', group: 'Direction', name: 'Milestones and Drift', refresh: 'bioSteward.drift.refresh',
    helps: 'Milestones and Drift shows whether the work your agents do keeps to the plan, the latest target first.',
  },
  decisions: {
    view: 'bioSteward.decisions', group: 'Direction', name: 'Decisions', refresh: 'bioSteward.decisions.refresh',
    helps: 'Decisions keeps the owner\'s decisions one click away, so you and your agents work from the same record.',
  },
  skills: {
    view: 'bioSteward.skills', group: 'Agents', name: 'Agent Skills', refresh: 'bioSteward.refreshSkills',
    helps: 'Agent Skills shows whether every agent in this project reads the same working rules.',
  },
} satisfies Record<string, Panel>);

export type PanelId = keyof typeof PANELS;

// The name a panel shows in its header: its group, then its own name ("Work · Tasks").
export const panelTitle = (panel: Panel) => `${panel.group} · ${panel.name}`;
