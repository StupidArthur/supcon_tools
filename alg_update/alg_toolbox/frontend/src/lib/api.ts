import { EventsOn } from "../../wailsjs/runtime/runtime"
import {
  Connect,
  IsConnected,
  StartSync,
  ExportAlgorithms,
  LoadCSVFile,
  CompareAlgorithms,
  StartPublish,
  GetPublishedAlgorithms,
  StartRepublish,
  PickDirectory,
  PickCSVFile,
  SaveCSVFile,
} from "../../wailsjs/go/main/App"
import type { main } from "../../wailsjs/go/models"

export type {
  main,
}

export const api = {
  connect: Connect,
  isConnected: IsConnected,
  startSync: StartSync,
  exportAlgorithms: ExportAlgorithms,
  loadCSVFile: LoadCSVFile,
  compareAlgorithms: CompareAlgorithms,
  startPublish: StartPublish,
  getPublishedAlgorithms: GetPublishedAlgorithms,
  startRepublish: StartRepublish,
  pickDirectory: PickDirectory,
  pickCSVFile: PickCSVFile,
  saveCSVFile: SaveCSVFile,
  onLog: (channel: string, cb: (msg: string) => void) =>
    EventsOn("log:" + channel, cb),
  onDone: (channel: string, cb: () => void) =>
    EventsOn(channel + ":done", cb),
}
