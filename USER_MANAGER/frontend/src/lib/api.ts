// 业务侧对 Wails Go 绑定的统一封装。
// 组件只引 api，不直接 import wailsjs。

import {
  Login,
  Logout,
  IsLoggedIn,
  LoadLoginConfig,
  SaveLoginConfig,
  ListUsers,
  GetAllUsers,
  CreateUser,
  ResetPassword,
  PickExcelFile,
  ParseExcelFile,
  DownloadBatchTemplate,
  BatchCreateUsers,
  CancelBatch,
} from '../../wailsjs/go/main/App';
import type { api, excel } from '../../wailsjs/go/models';

// 业务类型重导出
export type User = api.User;
export type UserDraft = api.UserDraft;
export type PageResponse = api.PageResponse;
export type OperationStatus = api.OperationStatus;
export type LoginConfig = api.LoginConfig;
export type ParseResult = excel.ParseResult;
export type ParsedRow = excel.ParsedRow;
export type ParseErr = excel.ParseErr;

// 业务函数封装
export const apiClient = {
  login: Login,
  logout: Logout,
  isLoggedIn: IsLoggedIn,
  loadLoginConfig: LoadLoginConfig,
  saveLoginConfig: SaveLoginConfig,

  listUsers: ListUsers,
  getAllUsers: GetAllUsers,

  createUser: CreateUser,
  resetPassword: ResetPassword,

  pickExcelFile: PickExcelFile,
  parseExcelFile: ParseExcelFile,
  downloadBatchTemplate: DownloadBatchTemplate,
  batchCreateUsers: BatchCreateUsers,
  cancelBatch: CancelBatch,
};

// 事件订阅 helper（包装 Wails EventsOn）
import { EventsOn, EventsOff } from '../../wailsjs/runtime/runtime';

export function onBatchProgress(cb: (batchId: string, progress: any) => void): () => void {
  EventsOn('batch:progress', (data: any) => cb(data.batchId, data.progress));
  return () => EventsOff('batch:progress');
}

export function onBatchDone(cb: (batchId: string, summary: any, results: any[]) => void): () => void {
  EventsOn('batch:done', (data: any) => cb(data.batchId, data.summary, data.results));
  return () => EventsOff('batch:done');
}
