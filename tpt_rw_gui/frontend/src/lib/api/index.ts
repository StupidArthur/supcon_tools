// 收口:不让组件直接 import "../../../wailsjs/..."。所有调用经此文件。
//
// `wails dev` / `wails build` 后会在 frontend/wailsjs/go/bindings/{SessionBinding,RWBinding}.ts
// 生成精确类型的桥函数,内部调用 window.go.bindings.*。本文件静态 re-export 它们,以满足:
//   1) dev-skill wails-backend §十三:组件不直接 import wailsjs,统一经 lib/api。
//   2) 类型清晰:走强类型,不再有"动态查找绑定"的 stub 兜底。
//
// 命名空间原因:组件 import "@/lib/api" 而非 "@/wailsjs/go/bindings/RWBinding",统一边界。

import * as SessionBinding from '../../../wailsjs/go/bindings/SessionBinding';
import * as RWBinding from '../../../wailsjs/go/bindings/RWBinding';

import type {
  SessionInfo,
  DataSource,
  Tag,
  RTValue,
  WriteResult,
  HistoryRow,
  PublicError,
} from './types';

export type {
  SessionInfo,
  DataSource,
  Tag,
  RTValue,
  WriteResult,
  HistoryRow,
  PublicError,
} from './types';

export interface SessionApi {
  login: (req: {
    url: string;
    username: string;
    password: string;
    tenantId: string;
    timeoutSec: number;
  }) => Promise<SessionInfo>;
  logout: () => Promise<void>;
  status: () => Promise<SessionInfo>;
}

export interface RwApi {
  listDataSources: () => Promise<DataSource[]>;
  listTags: (req: {
    dsId?: number;
    keyword: string;
    page: number;
    pageSize: number;
  }) => Promise<Tag[]>;
  readRealtime: (tagNames: string[]) => Promise<RTValue[]>;
  writeValues: (req: {
    values: Record<string, unknown>;
    readbackDelayMs: number;
  }) => Promise<WriteResult>;
  readHistory: (req: {
    tagNames: string[];
    begTime: string;
    endTime: string;
    interval: number;
    isSecond: boolean;
    isSource: boolean;
    offset: number;
    option: number;
    page: number;
    pageSize: number;
    sort: string;
    mode: string;
    numberToString: boolean;
  }) => Promise<HistoryRow[]>;
}

export const sessionApi: SessionApi = {
  login: SessionBinding.Login,
  logout: SessionBinding.Logout,
  status: SessionBinding.Status,
};

export const rwApi: RwApi = {
  listDataSources: RWBinding.ListDataSources,
  listTags: RWBinding.ListTags,
  readRealtime: RWBinding.ReadRealtime,
  writeValues: RWBinding.WriteValues,
  readHistory: RWBinding.ReadHistory,
};

// 检测后端返回的 auth 错误(PublicErrorDTO.Error() 格式: "[auth] ..." 或 "[auth:code] ...")
export function isAuthError(e: unknown): boolean {
  return e instanceof Error && e.message.startsWith('[auth');
}
