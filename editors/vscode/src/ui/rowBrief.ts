import * as vscode from 'vscode';
import { boundedBrief } from '../model/agent';
import { copyText } from './clipboard';

export async function copyBriefText(command: string, stdout: string): Promise<string> {
  const text = boundedBrief(stdout);
  await copyText(text);
  const shortened = text === stdout ? '' : ' · truncated';
  void vscode.window.showInformationMessage(`Bio-STEWARD: Copied ${Buffer.byteLength(text)} bytes from ${command} for your agent${shortened}.`);
  return text;
}
