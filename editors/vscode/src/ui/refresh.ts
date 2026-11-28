// The refresh button every panel has in its title bar (RELEASE_vscode_0.3.0_SPEC E01; roadmap §2 item 7). A refresh
// runs that panel's CLI commands again at once, past the debounce timers and the sprint view's one-read-a-second
// pacing, and shows VS Code's progress bar in the panel while they run. It runs nothing in an untrusted workspace.
import * as vscode from 'vscode';
import { PANELS, type PanelId } from '../model/panels';

export { PANELS, panelTitle, type Panel, type PanelGroup, type PanelId } from '../model/panels';

export interface RefreshRecord {
  readonly panel: PanelId;
  readonly started: number;
  ended: number | undefined;
}

// Every refresh that ran (bounded), for the host tests.
export class Refreshes {
  readonly records: RefreshRecord[] = [];

  // Run `work` with the panel's progress bar shown; resolves when it ends. Untrusted: runs nothing.
  run<T>(panel: PanelId, trusted: boolean, work: () => Promise<T>): Thenable<T | undefined> {
    if (!trusted) return Promise.resolve(undefined);
    const record: RefreshRecord = { panel, started: Date.now(), ended: undefined };
    this.records.push(record);
    if (this.records.length > 200) this.records.splice(0, this.records.length - 200);
    return vscode.window.withProgress({ location: { viewId: PANELS[panel].view }, title: `Refreshing ${PANELS[panel].name}` },
      async () => {
        try {
          return await work();
        } finally {
          record.ended = Date.now();
        }
      });
  }
}
