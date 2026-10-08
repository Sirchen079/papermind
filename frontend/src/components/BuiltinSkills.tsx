import { useEffect, useRef, useState } from 'react';
import { useWorkspace } from '../workspaceContext';

type Skill={id:string;slug:string;description:string;version:string;files:number};
type Family={id:string;name:string;source:string;revision:string;file_count:number;skills:Skill[]};
type Resource={text?:string;binary?:boolean;next_start:number|null;download_url:string;total_chars?:number};

export function BuiltinSkills(){
  const {base}=useWorkspace();
  const [families,setFamilies]=useState<Family[]>([]),[selected,setSelected]=useState('');
  const [files,setFiles]=useState<string[]>([]),[path,setPath]=useState('SKILL.md'),[filter,setFilter]=useState('');
  const [resource,setResource]=useState<Resource|null>(null),[error,setError]=useState('');
  const generation=useRef(0);
  async function request<T,>(suffix:string):Promise<T>{const r=await fetch(base+'/builtin-skills'+suffix);if(!r.ok)throw new Error('技能资源读取失败');return r.json();}
  useEffect(()=>{let alive=true;request<Family[]>('').then(x=>{if(alive)setFamilies(x);}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[base]);
  useEffect(()=>{const g=++generation.current;setResource(null);setFiles([]);setPath('SKILL.md');setFilter('');setError('');if(!selected)return;
    Promise.all([request<string[]>('/resources?skill_id='+encodeURIComponent(selected)),request<Resource>('/resource?'+new URLSearchParams({skill_id:selected,path:'SKILL.md'}))])
    .then(([f,r])=>{if(g===generation.current){setFiles(f);setResource(r);}}).catch(e=>{if(g===generation.current)setError(e.message);});
    return()=>{++generation.current;};
  },[selected,base]);
  async function read(nextPath:string,start=0){const g=++generation.current;setError('');if(!start)setResource(null);setPath(nextPath);
    try{const r=await request<Resource>('/resource?'+new URLSearchParams({skill_id:selected,path:nextPath,start:String(start)}));
      if(g===generation.current)setResource(old=>({...r,text:start?(old?.text??'')+(r.text??''):r.text}));
    }catch(e){if(g===generation.current)setError((e as Error).message);}}
  return <section className="card space-y-4"><h2 className="text-lg font-semibold">内置科研技能库</h2>
    <p className="text-sm text-muted">完整技能与引用资料随应用提供。问答可选择技能并按需读取资料；专题综述自动使用 Nature Writing 和 Oh My Paper。</p>
    {families.map(f=><details key={f.id} className="space-y-2"><summary className="cursor-pointer">{f.name} · {f.skills.length} 个技能 · {f.file_count} 个资源文件</summary>
      <a className="text-sm underline" href={f.source} target="_blank" rel="noreferrer">项目来源</a>
      <div className="grid gap-2 sm:grid-cols-2">{f.skills.map(s=><button key={s.id} className="shelf-paper text-left min-w-0" onClick={()=>setSelected(s.id)}><span className="break-words">{s.slug}</span><span className="text-xs text-muted">{s.version&&' · v'+s.version} · {s.files} 个文件</span></button>)}</div>
    </details>)}
    {error&&<p role="alert" className="text-red-600">{error}</p>}
    {selected&&<div className="space-y-3 border-t pt-3"><div className="flex flex-wrap justify-between gap-2"><h3 className="break-all font-medium">{selected}</h3><button className="btn-ghost" onClick={()=>setSelected('')}>收起资源</button></div>
      <input className="input w-full" aria-label="筛选技能资源" placeholder="查找引用、模板、脚本或共享文件" value={filter} onChange={e=>setFilter(e.target.value)}/>
      <select className="input w-full font-mono text-xs" aria-label="技能资源文件" value={path} onChange={e=>read(e.target.value)}>{files.filter(p=>p===path||p.toLowerCase().includes(filter.toLowerCase())).map(p=><option key={p}>{p}</option>)}</select>
      {resource&&<><a className="btn-ghost inline-block" href={resource.download_url.replace(/^\/api/,base)} download>下载原始文件</a>{resource.binary?<p className="text-sm text-muted">此资源为图片或二进制文件，可下载查看。</p>:<pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded border p-3 font-mono text-xs" aria-label="内置技能原文">{resource.text}</pre>}
      {resource.next_start!==null&&resource.next_start!==undefined&&<button className="btn-ghost" onClick={()=>read(path,resource.next_start!)}>继续读取</button>}</>}
    </div>}
  </section>;
}
