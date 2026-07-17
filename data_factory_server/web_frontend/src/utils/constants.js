/**
 * 常量配置
 * 
 * 减少硬编码，统一管理常量
 */

// API 基础地址（开发环境通过代理，生产环境需要配置）
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

// 默认配置值
export const DEFAULT_CYCLE_TIME = 5
export const DEFAULT_PREVIEW_STEPS = 2000
export const DEFAULT_TOTAL_STEPS = 10000
// 2025-05-18 08:00:00 (UTC+8) 对应的秒级时间戳
export const DEFAULT_START_TIME = 1747526400

// 布局配置
export const CONFIG_PANEL_WIDTH = '35%'
export const CHART_PANEL_WIDTH = '65%'

// 表单配置
export const FORM_ITEM_LAYOUT = {
  labelCol: { span: 8 },
  wrapperCol: { span: 16 },
}

export const COMPACT_FORM_ITEM_LAYOUT = {
  labelCol: { span: 10 },
  wrapperCol: { span: 14 },
}

