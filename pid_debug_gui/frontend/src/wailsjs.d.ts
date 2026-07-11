declare module '../../wailsjs/go/bindings/DebugBinding' {
  export function Connect(url: string): Promise<string>
  export function Disconnect(): Promise<void>
  export function GetStatus(): Promise<string>
  export function GetMeta(): Promise<string>
  export function SetParam(name: string, param: string, value: number): Promise<void>
  export function Override(tag: string, value: number): Promise<void>
  export function ExportCsv(path: string): Promise<string>
  export function GetDisplayVariables(): Promise<string>
  export function GetLastSnapshot(): Promise<string>
  export function GetSnapshotHistory(): Promise<string>
  export function IsConnected(): Promise<boolean>
}

declare module '../../wailsjs/runtime/runtime' {
  export function EventsOn(event: string, callback: (...args: any[]) => void): () => void
  export function EventsEmit(event: string, ...data: any): void
}
