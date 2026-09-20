export function shouldSubmitOnEnter(
  key: string,
  shiftKey: boolean,
  isComposing: boolean,
): boolean {
  return key === "Enter" && !shiftKey && !isComposing;
}

export function shouldCloseOnEscape(key: string, hasOpenAlertDialog: boolean): boolean {
  return key === "Escape" && !hasOpenAlertDialog;
}

export function chatEnterAction(event: {key: string; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; isComposing: boolean; keyCode?: number}): 'send' | 'newline' | null {
  if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229) return null;
  return event.ctrlKey || event.metaKey || event.shiftKey ? 'newline' : 'send';
}
