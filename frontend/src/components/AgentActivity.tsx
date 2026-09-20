export function AgentActivity({label, stopping = false}: {label: string; stopping?: boolean}) {
  return <div className={`agent-activity ${stopping ? 'is-stopping' : ''}`} role="status">
    <span className="agent-orbit" aria-hidden="true"><span /></span>
    <div><span className="agent-activity-label">{label}</span><span className="agent-activity-caption">{stopping ? '已请求停止，等待当前调用结束' : '研究助手正在处理，可继续准备下一条问题'}</span></div>
    {!stopping && <span className="agent-dots" aria-hidden="true"><i /><i /><i /></span>}
  </div>;
}
