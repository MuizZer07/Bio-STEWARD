import * as vscode from 'vscode';
import { isRuleId } from '../cli/commands';
import { projectFiles, resultAnchors, severityFor, type Severity, type UnknownSeverity } from '../model/findings';
import { gateTags, type LoadedReport } from '../model/views';
import { commandUri, EXPLAIN_COMMAND } from './explain';

export const DIAGNOSTIC_SOURCE = 'Bio-STEWARD';
const SEVERITY: Record<Severity, vscode.DiagnosticSeverity> = {
  error: vscode.DiagnosticSeverity.Error,
  warning: vscode.DiagnosticSeverity.Warning,
  information: vscode.DiagnosticSeverity.Information,
};

export class ProblemsView implements vscode.Disposable {
  readonly #collection = vscode.languages.createDiagnosticCollection('bioSteward');
  #published = new Map<string, vscode.Uri>();
  #generation = 0;
  #report: LoadedReport | undefined;
  #unknown: UnknownSeverity | undefined;

  constructor(private readonly root: vscode.Uri) {}

  async update(loaded: LoadedReport | undefined, unknown: UnknownSeverity): Promise<void> {
    if (loaded === this.#report && unknown === this.#unknown) return;
    this.#report = loaded;
    this.#unknown = unknown;
    const generation = ++this.#generation;
    const next = new Map<string, [vscode.Uri, vscode.Diagnostic[]]>();
    if (loaded) {
      const file = projectFiles(this.root.fsPath);
      const uriFor = (path: string) => vscode.Uri.joinPath(this.root, path);
      for (const result of loaded.report.verdict.results) {
        if (generation !== this.#generation) return;
        const severity = severityFor(result.status, unknown);
        if (!severity) continue;
        const anchors = await resultAnchors(result, file);
        if (!anchors.length) continue;
        const tags = gateTags(loaded.report, result, loaded.partial);
        if (loaded.freshness !== 'fresh') tags.push(`from a ${loaded.freshness === 'stale' ? 'stale' : 'freshness-unknown'} report`);
        const message = [result.reason, ...tags].join(' · ');
        const related: vscode.DiagnosticRelatedInformation[] = [];
        for (const evidence of result.evidence) {
          const path = await file(evidence.path);
          if (path) related.push(new vscode.DiagnosticRelatedInformation(
            new vscode.Location(uriFor(path), new vscode.Position(0, 0)), evidence.path));
        }
        for (const anchor of anchors) {
          const uri = uriFor(anchor.path);
          const line = anchor.line - 1;
          const diagnostic = new vscode.Diagnostic(new vscode.Range(line, 0, line, 0), message, SEVERITY[severity]);
          diagnostic.source = DIAGNOSTIC_SOURCE;
          diagnostic.code = isRuleId(result.rule)
            ? { value: anchor.code ?? result.rule, target: commandUri(EXPLAIN_COMMAND, [result.rule, anchor.code]) }
            : result.rule;
          diagnostic.relatedInformation = related;
          const key = uri.toString();
          const entry = next.get(key);
          if (entry) entry[1].push(diagnostic);
          else next.set(key, [uri, [diagnostic]]);
        }
      }
    }
    if (generation !== this.#generation) return;
    const batch: [vscode.Uri, vscode.Diagnostic[] | undefined][] = [...next.values()];
    for (const [key, uri] of this.#published) {
      if (!next.has(key)) batch.push([uri, undefined]);
    }
    this.#collection.set(batch);
    this.#published = new Map([...next].map(([key, [uri]]) => [key, uri]));
  }

  dispose(): void {
    this.#generation++;
    this.#collection.dispose();
  }
}
