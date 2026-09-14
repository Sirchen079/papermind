import { parseApiErrorMessage } from './pages/apiErrorModel';
import type { Workspace } from './workspaceContext';

export async function workspaceRequest(path = '', body?: unknown, method = 'POST'): Promise<any> {
  const response = await fetch('/api/workspaces' + path, body === undefined ? undefined : {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(parseApiErrorMessage(response.status, await response.text()));
  return response.json();
}

export function listWorkspaces(): Promise<Workspace[]> { return workspaceRequest(); }
