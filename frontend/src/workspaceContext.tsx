import { createContext, useContext } from 'react';
import { createApi } from './api';
import { createResearchApi } from './researchApi';
import { createWikiApi } from './wikiApi';

export interface Workspace { id:string; name:string; goal:string; archived:boolean; available?:boolean; unavailable_reason?:string|null; }
export interface WorkspaceValue {
  workspace:Workspace;
  workspaces:Workspace[];
  api:ReturnType<typeof createApi>;
  researchApi:ReturnType<typeof createResearchApi>;
  wikiApi:ReturnType<typeof createWikiApi>;
  base:string;
  switchTo:(id:string)=>void;
  refresh:()=>Promise<void>;
}
export const WorkspaceContext=createContext<WorkspaceValue|null>(null);
export function useWorkspace() {
  const value=useContext(WorkspaceContext);
  if(!value) throw new Error('Research workspace is not selected');
  return value;
}
export function useApi(){return useWorkspace().api;}
export function workspaceDraftKey(workspaceId:string,key:string){
  return workspaceId==='legacy'?key:`pm-workspace-${workspaceId}:${key}`;
}
