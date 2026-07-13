export interface SessionInfo {
  loggedIn: boolean;
  url: string;
  tenantId: string;
}

export interface DataSource {
  id: number;
  name: string;
  url: string;
  dsType: number;
  dsSubType: number;
  alive: boolean;
  dsStatus: number;
}

export interface Tag {
  id: number;
  tagName: string;
  tagBaseName: string;
  tagType: number;
  dsId: number;
  dsName: string;
  dataType: number;
  dataTypeName: string;
  tagValue?: string;
  tagTime: string;
  quality: number;
  groupName: string;
}

export interface RTValue {
  tagName: string;
  value: string;
  tagTime: string;
  appTime: string;
  quality: number;
  dataType: number;
  dsId: number;
  isSuccess: boolean;
  message?: string;
}

export interface WriteResult {
  written: string[];
  fails?: Record<string, string>;
  readback?: RTValue[];
}

export interface HistoryRow {
  tagName: string;
  value: string;
  appTime: string;
  quality: number;
}

export interface PublicError {
  code: string;
  message: string;
  kind: string;
}
