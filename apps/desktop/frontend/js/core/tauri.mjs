export function tauriApi(globalObject=globalThis){const api=globalObject.__TAURI__;if(!api?.core?.invoke)throw new Error("TAURI_UNAVAILABLE");return api}
export async function invoke(command,args={},globalObject=globalThis){return tauriApi(globalObject).core.invoke(command,args)}
export async function listen(event,callback,globalObject=globalThis){return tauriApi(globalObject).event.listen(event,callback)}
