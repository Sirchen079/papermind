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
